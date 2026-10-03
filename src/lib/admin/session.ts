"use client";

/**
 * Session lifecycle for the staff portal (browser side).
 *
 * - A fresh launch never signs in automatically. The access token lives only in
 *   memory, so a new page load must be vouched for: either this same tab was
 *   signed in moments ago (a reload), or another open portal tab answers a ping.
 *   Otherwise the sign-in screen shows and any leftover cookie session is ended.
 * - "Background": when no portal tab has been visible for BACKGROUND_LIMIT_MS,
 *   the session ends and re-authentication is required.
 * - "Idle": no keyboard/mouse/touch activity in any tab for the idle limit signs out,
 *   with a countdown for the last IDLE_WARNING_MS. The limit comes from the server
 *   (a super admin sets it; staff may choose shorter), and activity is reported to the
 *   server, which enforces the same limit. The countdown runs from the last *reported*
 *   activity so it matches the server's clock.
 * - Signing out in one tab signs out every tab.
 *
 * Only non-secret timestamps/flags are kept in storage; tokens never are.
 */

export const BACKGROUND_LIMIT_MS = 5 * 60_000;
export const IDLE_WARNING_MS = 60_000;
/** Report activity to the server at most this often (a trailing report always follows). */
export const ACTIVITY_REPORT_MS = 30_000;

let idleLimitMs = 30 * 60_000; // until the server says otherwise
export const idleLimit = () => idleLimitMs;
export function setIdleLimitMinutes(minutes: number) {
  if (minutes > 0) idleLimitMs = minutes * 60_000;
}

const TAB_FLAG = "ghtrust_tab_signed_in"; // sessionStorage: this tab had a live session
const VISIBLE_AT = "ghtrust_visible_at"; // localStorage: last time any portal tab was visible
const ACTIVE_AT = "ghtrust_active_at"; // localStorage: last user interaction in any tab
const HAD_SESSION = "ghtrust_had_session"; // localStorage: a session may still exist server-side
const CHANNEL = "ghtrust-staff-session";

export type SignOutReason = "manual" | "background" | "idle" | "expired";

type Message = { type: "ping"; id: string } | { type: "pong"; id: string } | { type: "signout"; reason: SignOutReason };

function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

const now = () => Date.now();
const readTime = (key: string) => Number(safe(() => localStorage.getItem(key), null) ?? 0);
const writeTime = (key: string, t = now()) => safe(() => localStorage.setItem(key, String(t)), undefined);

// Earlier versions kept tokens and the staff profile in localStorage. Wipe them:
// a leftover refresh token there would still be usable until it expired.
if (typeof window !== "undefined") {
  safe(() => ["ghtrust_staff_access", "ghtrust_staff_refresh", "ghtrust_staff_profile"].forEach((k) => localStorage.removeItem(k)), undefined);
}

let channel: BroadcastChannel | null = null;
function bus(): BroadcastChannel | null {
  if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") return null;
  channel ??= new BroadcastChannel(CHANNEL);
  return channel;
}

// ── This tab's signed-in flag ────────────────────────────────────────────────

export function markTabSignedIn(on: boolean) {
  safe(() => (on ? sessionStorage.setItem(TAB_FLAG, "1") : sessionStorage.removeItem(TAB_FLAG)), undefined);
  if (on) {
    writeTime(VISIBLE_AT);
    writeTime(ACTIVE_AT);
  }
}

/**
 * Whether a refresh cookie might still be live. Lets a cold launch skip the
 * "end leftover session" call entirely when there was never a session.
 */
export function hadSession(): boolean {
  return safe(() => localStorage.getItem(HAD_SESSION) === "1", false);
}

export function setHadSession(on: boolean) {
  safe(() => (on ? localStorage.setItem(HAD_SESSION, "1") : localStorage.removeItem(HAD_SESSION)), undefined);
}

/** Was the portal in the background (no visible tab) for longer than the limit? */
export function backgroundExpired(): boolean {
  const seen = readTime(VISIBLE_AT);
  return !seen || now() - seen > BACKGROUND_LIMIT_MS;
}

export function idleFor(): number {
  const active = readTime(ACTIVE_AT);
  return active ? now() - active : Infinity;
}

/**
 * Decide on page load whether we may resume via the refresh cookie.
 * - Reload of a signed-in tab that hasn't sat in the background too long → yes.
 * - Another open, signed-in portal tab answers → yes (new tab / opened link).
 * - Anything else (cold launch, restored tabs after a while) → no.
 */
export async function mayResume(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  if (idleFor() > idleLimitMs) return false;
  const tabFlag = safe(() => sessionStorage.getItem(TAB_FLAG) === "1", false);
  if (tabFlag && !backgroundExpired()) return true;
  return askOtherTabs();
}

function askOtherTabs(timeoutMs = 250): Promise<boolean> {
  const ch = bus();
  if (!ch) return Promise.resolve(false);
  const id = Math.random().toString(36).slice(2);
  return new Promise((resolve) => {
    const onMessage = (e: MessageEvent<Message>) => {
      if (e.data?.type === "pong" && e.data.id === id) done(true);
    };
    const timer = setTimeout(() => done(false), timeoutMs);
    function done(ok: boolean) {
      clearTimeout(timer);
      ch!.removeEventListener("message", onMessage);
      resolve(ok);
    }
    ch.addEventListener("message", onMessage);
    ch.postMessage({ type: "ping", id } satisfies Message);
  });
}

// ── Live-session wiring (while signed in) ────────────────────────────────────

/**
 * Start tracking visibility/activity and listening to other tabs.
 * `onSignOut` fires when any tab signs out or a limit is hit here.
 * `onIdleWarning(msLeft)` fires once the idle countdown starts; `msLeft === null` clears it.
 */
export function startSessionWatch({
  onSignOut,
  onIdleWarning,
  reportActivity,
}: {
  onSignOut: (reason: SignOutReason) => void;
  onIdleWarning: (msLeft: number | null) => void;
  /** Tell the server the staff member is active; resolves when it has recorded it. */
  reportActivity: () => Promise<void>;
}): () => void {
  const ch = bus();
  let warned = false;
  let ended = false;
  const end = (reason: SignOutReason) => {
    if (ended) return; // fire once, however many ticks/messages arrive before unmount
    ended = true;
    onSignOut(reason);
  };
  let lastReport = 0;
  let pending = false;

  const report = () => {
    const sentAt = now();
    lastReport = sentAt;
    pending = false;
    // The server's idle clock restarts when it records this; a 401 signs out via the API client.
    reportActivity().then(() => writeTime(ACTIVE_AT, sentAt), () => undefined);
  };

  const touchActive = () => {
    // While the countdown shows, only "Stay signed in" keeps the session.
    if (warned) return;
    if (now() - lastReport >= ACTIVITY_REPORT_MS) report();
    else pending = true;
  };

  const tick = () => {
    if (document.visibilityState === "visible") writeTime(VISIBLE_AT);
    else if (backgroundExpired()) return end("background");

    if (pending && now() - lastReport >= ACTIVITY_REPORT_MS) report();
    const idle = idleFor();
    if (idle >= idleLimitMs) return end("idle");
    if (idle >= idleLimitMs - IDLE_WARNING_MS) {
      warned = true;
      onIdleWarning(idleLimitMs - idle);
    } else if (warned) {
      warned = false;
      onIdleWarning(null);
    }
  };

  const onVisibility = () => {
    // Coming back after the background limit: lock before showing any data.
    if (document.visibilityState === "visible" && backgroundExpired()) return end("background");
    tick();
  };

  const onMessage = (e: MessageEvent<Message>) => {
    if (e.data?.type === "ping") ch?.postMessage({ type: "pong", id: e.data.id } satisfies Message);
    else if (e.data?.type === "signout") end(e.data.reason);
  };

  const activity = ["pointerdown", "keydown", "wheel", "touchstart"] as const;
  activity.forEach((ev) => window.addEventListener(ev, touchActive, { passive: true }));
  document.addEventListener("visibilitychange", onVisibility);
  ch?.addEventListener("message", onMessage);
  const interval = window.setInterval(tick, 1_000);
  report(); // signing in, or resuming, counts as activity
  tick();

  return () => {
    activity.forEach((ev) => window.removeEventListener(ev, touchActive));
    document.removeEventListener("visibilitychange", onVisibility);
    ch?.removeEventListener("message", onMessage);
    window.clearInterval(interval);
  };
}

/** Tell every other portal tab to sign out. */
export function broadcastSignOut(reason: SignOutReason) {
  bus()?.postMessage({ type: "signout", reason } satisfies Message);
}
