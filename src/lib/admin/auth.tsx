"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { API_BASE, COOKIE_TRANSPORT, refreshAccessToken, tokenStore } from "./api";
import { clearResourceCache } from "./cache";
import {
  broadcastSignOut,
  hadSession,
  markTabSignedIn,
  mayResume,
  setHadSession,
  setIdleLimitMinutes,
  startSessionWatch,
  type SignOutReason,
} from "./session";
import { authApi } from "./endpoints";
import type { StaffProfile } from "./types";

/** Permission keys (backend/app/modules/admin/permissions.py). */
export const P = {
  STAFF_READ: "staff:read",
  STAFF_CREATE: "staff:create",
  STAFF_UPDATE: "staff:update",
  STAFF_ACTIVATE: "staff:activate",
  ROLE_READ: "role:read",
  ROLE_CREATE: "role:create",
  ROLE_UPDATE: "role:update",
  ROLE_DELETE: "role:delete",
  LOAN_READ: "loan:read",
  LOAN_REVIEW: "loan:review",
  LOAN_VERIFY_DOCS: "loan:verify_documents",
  LOAN_DISBURSE: "loan:disburse",
  LOAN_RECORD_REPAYMENT: "loan:record_repayment",
  LOAN_CONFIGURE_WORKFLOW: "loan:configure_workflow",
  PAYMENT_READ: "payment:read",
} as const;

export const PERMISSION_LABELS: Record<string, string> = {
  [P.STAFF_READ]: "View staff",
  [P.STAFF_CREATE]: "Create staff",
  [P.STAFF_UPDATE]: "Edit staff",
  [P.STAFF_ACTIVATE]: "Activate / deactivate staff",
  [P.ROLE_READ]: "View roles",
  [P.ROLE_CREATE]: "Create roles",
  [P.ROLE_UPDATE]: "Edit roles",
  [P.ROLE_DELETE]: "Delete roles",
  [P.LOAN_READ]: "View loans & customers",
  [P.LOAN_REVIEW]: "Review applications",
  [P.LOAN_VERIFY_DOCS]: "Verify documents",
  [P.LOAN_DISBURSE]: "Disburse loans",
  [P.LOAN_RECORD_REPAYMENT]: "Record repayments",
  [P.LOAN_CONFIGURE_WORKFLOW]: "Configure products & workflows",
  [P.PAYMENT_READ]: "View payment transactions",
};

export function hasPermission(staff: StaffProfile | null | undefined, permission: string): boolean {
  if (!staff) return false;
  return staff.is_super_admin || staff.permissions.includes(permission);
}

interface AuthValue {
  staff: StaffProfile | null;
  signedIn: boolean;
  /** True until we know whether this page load may resume a session. */
  loading: boolean;
  can: (permission: string) => boolean;
  signIn: (access: string, staff: StaffProfile) => void;
  signOut: (reason?: SignOutReason) => Promise<void>;
  /** Why the last session ended (shown on the sign-in screen). */
  lastSignOut: SignOutReason | null;
  /** Milliseconds left before an idle sign-out, while the warning is showing. */
  idleWarningMs: number | null;
  /** Dismiss the idle warning ("Stay signed in"). */
  stayActive: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

// Set by an explicit sign-out so the session guard doesn't add ?next= (which would
// send whoever signs in next straight back to the previous person's page).
let signOutRequested = false;

/** True once after an explicit sign-out. */
export function consumeSignOutRequest(): boolean {
  const requested = signOutRequested;
  signOutRequested = false;
  return requested;
}

/**
 * Decide once per page load whether to resume (React runs mount effects twice in
 * development; this must not refresh or sign out twice).
 */
let startup: Promise<StaffProfile | null> | null = null;

function resumeOnce(): Promise<StaffProfile | null> {
  startup ??= (async () => {
    if ((await mayResume()) && (await refreshAccessToken())) {
      try {
        return await authApi.me();
      } catch {
        return null; // 401 handled by the token store
      }
    }
    markTabSignedIn(false);
    // Cold launch: end the leftover server session — only if there could be one.
    if (hadSession()) {
      await endServerSession();
      setHadSession(false);
    }
    return null;
  })();
  return startup;
}

/** End the server session tied to the refresh cookie (works without an access token). */
async function endServerSession() {
  const headers = new Headers(COOKIE_TRANSPORT.headers);
  if (tokenStore.access) headers.set("Authorization", `Bearer ${tokenStore.access}`);
  try {
    await fetch(`${API_BASE}/api/v1/admin/auth/logout`, { method: "POST", credentials: "include", headers });
  } catch {
    /* offline: the server's idle timeout ends it */
  }
}

export function StaffAuthProvider({ children }: { children: ReactNode }) {
  // Start identical on server and client (no storage access during render) so
  // hydration matches; whether to resume is decided right after mount.
  const [staff, setStaff] = useState<StaffProfile | null>(null);
  const [signedIn, setSignedIn] = useState(false);
  const [loading, setLoading] = useState(true);
  const [lastSignOut, setLastSignOut] = useState<SignOutReason | null>(null);
  const [idleWarningMs, setIdleWarningMs] = useState<number | null>(null);
  const signedInRef = useRef(false);
  signedInRef.current = signedIn;

  const finishSignOut = useCallback((reason: SignOutReason) => {
    signedInRef.current = false; // before clearing the token, so the listener below stays quiet
    markTabSignedIn(false);
    setHadSession(false);
    clearResourceCache(); // no previous user's data survives in memory
    tokenStore.clear();
    setStaff(null);
    setSignedIn(false);
    setIdleWarningMs(null);
    setLastSignOut(reason);
  }, []);

  // Any 401 the client couldn't recover from (revoked, idle-expired) ends the session.
  useEffect(
    () =>
      tokenStore.subscribe((access) => {
        if (!access && signedInRef.current) finishSignOut("expired");
      }),
    [finishSignOut],
  );

  // Page load: resume only when allowed; otherwise make sure no stale session lingers.
  useEffect(() => {
    let cancelled = false;
    resumeOnce().then((profile) => {
      if (cancelled) return;
      if (profile) {
        setStaff(profile);
        setSignedIn(true);
        markTabSignedIn(true);
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const signOut = useCallback(
    async (reason: SignOutReason = "manual") => {
      if (reason === "manual") signOutRequested = true;
      broadcastSignOut(reason);
      await endServerSession();
      finishSignOut(reason);
    },
    [finishSignOut],
  );

  // While signed in: background/idle limits and sign-outs from other tabs.
  useEffect(() => {
    if (!signedIn) return;
    return startSessionWatch({
      onSignOut: (reason) => {
        if (reason === "background" || reason === "idle") void signOut(reason);
        else finishSignOut(reason); // another tab already ended the server session
      },
      onIdleWarning: setIdleWarningMs,
      reportActivity: () => authApi.activity().then((r) => setIdleLimitMinutes(r.effective_idle_minutes)),
    });
  }, [signedIn, signOut, finishSignOut]);

  const signIn = useCallback((access: string, profile: StaffProfile) => {
    tokenStore.set(access);
    markTabSignedIn(true);
    setHadSession(true);
    setStaff(profile);
    setSignedIn(true);
    setLastSignOut(null);
  }, []);

  const stayActive = useCallback(() => {
    markTabSignedIn(true); // refreshes the activity timestamps
    setIdleWarningMs(null);
    void authApi.activity().catch(() => undefined); // restart the server's clock too
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      staff,
      signedIn,
      loading,
      can: (permission: string) => hasPermission(staff, permission),
      signIn,
      signOut,
      lastSignOut,
      idleWarningMs,
      stayActive,
    }),
    [staff, signedIn, loading, signIn, signOut, lastSignOut, idleWarningMs, stayActive],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useStaffAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useStaffAuth must be used inside StaffAuthProvider");
  return ctx;
}
