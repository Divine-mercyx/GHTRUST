/**
 * Customer session lifecycle.
 *
 *   loading ──► signedOut ──(SMS code / PIN)──► signedIn ◄──(PIN / biometrics)── locked
 *                   ▲                              │                               ▲
 *                   └────── sign out / revoked ────┘── away / untouched too long ───┘
 *
 * How long is the customer's choice in Security ("Lock app", lockPolicy.ts).
 *
 * Start-up never waits on the network: a stored refresh token means the app opens to
 * the lock screen, and the first API call refreshes the access token.
 *
 * A phone that signed in before keeps a device token (see storage.ts). While it does,
 * a signed-out customer can sign back in here with their 6-digit PIN.
 */
import { useQueryClient } from '@tanstack/react-query';
import { createContext, use, useCallback, useEffect, useMemo, useRef, useState, type PropsWithChildren } from 'react';
import { AppState } from 'react-native';

import { configureClient, setAccessToken } from '@/api/client';
import { auth } from '@/api/endpoints';
import type { AuthTokens } from '@/api/types';

import { biometricKind, type BiometricKind } from './lock';
import {
  DEFAULT_LOCK_AFTER_MS,
  inactiveFor,
  lockPaused,
  noteActivity,
  parseLockAfter,
  shouldLockAfterAway,
  shouldLockWhenInactive,
} from './lockPolicy';
import { tokenStore } from './storage';

export type SessionStatus = 'loading' | 'signedOut' | 'locked' | 'signedIn';
export type Gate = { code: 'APP_UPDATE_REQUIRED' | 'MAINTENANCE_MODE'; message: string } | null;

type SessionValue = {
  status: SessionStatus;
  firstName: string | null;
  /** This phone is trusted: a signed-out customer can sign back in with their PIN. */
  trusted: boolean;
  /** Biometrics the customer turned on for this phone and that still work, if any. */
  biometric: BiometricKind | null;
  /** What this phone offers, whether or not it's turned on. */
  biometricAvailable: BiometricKind | null;
  setBiometric: (on: boolean) => Promise<void>;
  /** How long the app may be away (or untouched) before it locks, in ms; 0 = immediately. */
  lockAfterMs: number;
  setLockAfter: (ms: number) => Promise<void>;
  gate: Gate;
  clearGate: () => void;
  signIn: (tokens: AuthTokens) => Promise<void>;
  signOut: (opts?: { everywhere?: boolean; forget?: boolean }) => Promise<void>;
  unlocked: () => void;
  /** "Not you?": sign out and stop trusting this phone. */
  forget: () => Promise<void>;
};

const SessionContext = createContext<SessionValue | null>(null);

export function useSession() {
  const value = use(SessionContext);
  if (!value) throw new Error('useSession must be used inside <SessionProvider>');
  return value;
}

export function SessionProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [firstName, setFirstName] = useState<string | null>(null);
  const [trusted, setTrusted] = useState(false);
  const [biometricOn, setBiometricOn] = useState(false);
  const [available, setAvailable] = useState<BiometricKind | null>(null);
  const [gate, setGate] = useState<Gate>(null);
  const [lockAfterMs, setLockAfterMs] = useState(DEFAULT_LOCK_AFTER_MS);
  // Read by AppState and timer callbacks, which shouldn't re-subscribe on every change.
  const lockAfterRef = useRef(DEFAULT_LOCK_AFTER_MS);
  useEffect(() => {
    lockAfterRef.current = lockAfterMs;
  }, [lockAfterMs]);
  const backgroundedAt = useRef<number | null>(null);

  const reset = useCallback(
    async ({ forget = false } = {}) => {
      setAccessToken(null);
      await tokenStore.clear();
      if (forget) {
        await tokenStore.forgetDevice();
        setTrusted(false);
        setFirstName(null);
        setBiometricOn(false);
      }
      queryClient.clear();
      setStatus('signedOut');
    },
    [queryClient],
  );

  // Boot: decide the first screen from local state only.
  useEffect(() => {
    configureClient({
      onSessionEnded: () => {
        queryClient.clear();
        setStatus('signedOut');
      },
      onGate: (code, message) => setGate({ code, message }),
    });
    (async () => {
      const [refresh, name, deviceToken, bio, kind, lockAfter] = await Promise.all([
        tokenStore.getRefresh(),
        tokenStore.getName(),
        tokenStore.getDeviceToken(),
        tokenStore.getBiometric(),
        biometricKind(),
        tokenStore.getLockAfter(),
      ]);
      setLockAfterMs(parseLockAfter(lockAfter));
      setFirstName(name);
      setTrusted(!!deviceToken);
      setBiometricOn(bio);
      setAvailable(kind);
      setStatus(refresh ? 'locked' : 'signedOut');
    })();
  }, [queryClient]);

  const lock = useCallback(() => setStatus((s) => (s === 'signedIn' ? 'locked' : s)), []);

  // Lock after the chosen time away; re-check biometrics on return (the customer may
  // have removed their fingerprints in Settings meanwhile). The app's own pickers and
  // permission prompts pause this (lockPolicy.withLockPaused).
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'background') {
        backgroundedAt.current = lockPaused() ? null : Date.now();
      } else if (next === 'active') {
        biometricKind().then(setAvailable);
        if (backgroundedAt.current && !lockPaused()) {
          const away = Date.now() - backgroundedAt.current;
          if (shouldLockAfterAway(away, lockAfterRef.current)) lock();
        }
        backgroundedAt.current = null;
        noteActivity();
      }
    });
    return () => sub.remove();
  }, [lock]);

  // Lock when the app is open but nobody has touched it for the chosen time.
  useEffect(() => {
    if (status !== 'signedIn') return;
    noteActivity();
    const id = setInterval(() => {
      if (AppState.currentState !== 'active' || lockPaused()) return;
      if (shouldLockWhenInactive(inactiveFor(), lockAfterRef.current)) lock();
    }, 10_000);
    return () => clearInterval(id);
  }, [status, lock]);

  const setLockAfter = useCallback(async (ms: number) => {
    await tokenStore.setLockAfter(ms);
    setLockAfterMs(ms);
  }, []);

  const signIn = useCallback(
    async (tokens: AuthTokens) => {
      setAccessToken(tokens.access_token);
      await tokenStore.setRefresh(tokens.refresh_token);
      await tokenStore.setName(tokens.customer.first_name);
      if (tokens.device_token) {
        await tokenStore.setDeviceToken(tokens.device_token);
        setTrusted(true);
      }
      queryClient.setQueryData(['me'], tokens.customer);
      setFirstName(tokens.customer.first_name);
      setStatus('signedIn');
    },
    [queryClient],
  );

  const signOut = useCallback(
    async ({ everywhere = false, forget = false } = {}) => {
      // Best effort: the local sign-out must succeed even offline.
      await Promise.race([
        (everywhere ? auth.logoutAll() : auth.logout(forget)).catch(() => undefined),
        new Promise((r) => setTimeout(r, 4000)),
      ]);
      await reset({ forget });
    },
    [reset],
  );

  const setBiometric = useCallback(async (on: boolean) => {
    await tokenStore.setBiometric(on);
    setBiometricOn(on);
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      status,
      firstName,
      trusted,
      biometric: biometricOn ? available : null,
      biometricAvailable: available,
      setBiometric,
      lockAfterMs,
      setLockAfter,
      gate,
      clearGate: () => setGate(null),
      signIn,
      signOut,
      unlocked: () => setStatus('signedIn'),
      forget: () => signOut({ forget: true }),
    }),
    [status, firstName, trusted, biometricOn, available, setBiometric, lockAfterMs, setLockAfter, gate, signIn, signOut],
  );

  return <SessionContext value={value}>{children}</SessionContext>;
}
