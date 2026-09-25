/**
 * Customer session lifecycle.
 *
 *   loading ──► signedOut ──(OTP)──► signedIn ◄──(unlock)── locked
 *                   ▲                    │                     ▲
 *                   └──── sign out / ────┘── 5 min background ─┘
 *                         revoked
 *
 * Start-up never waits on the network: a stored refresh token means the app
 * opens to the lock screen (or straight in when the device has no lock set),
 * and the first API call refreshes the access token.
 */
import { useQueryClient } from '@tanstack/react-query';
import { createContext, use, useCallback, useEffect, useMemo, useRef, useState, type PropsWithChildren } from 'react';
import { AppState } from 'react-native';

import { configureClient, setAccessToken } from '@/api/client';
import { auth } from '@/api/endpoints';
import type { AuthTokens } from '@/api/types';

import { lockKind, RELOCK_AFTER_MS, type LockKind } from './lock';
import { tokenStore } from './storage';

export type SessionStatus = 'loading' | 'signedOut' | 'locked' | 'signedIn';
export type Gate = { code: 'APP_UPDATE_REQUIRED' | 'MAINTENANCE_MODE'; message: string } | null;

type SessionValue = {
  status: SessionStatus;
  firstName: string | null;
  lock: LockKind;
  gate: Gate;
  clearGate: () => void;
  signIn: (tokens: AuthTokens) => Promise<void>;
  signOut: (opts?: { everywhere?: boolean }) => Promise<void>;
  unlocked: () => void;
  /** Forget the saved session from the lock screen ("Not you?"). */
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
  const [lock, setLock] = useState<LockKind>('none');
  const [gate, setGate] = useState<Gate>(null);
  const backgroundedAt = useRef<number | null>(null);

  const reset = useCallback(async () => {
    setAccessToken(null);
    await tokenStore.clear();
    queryClient.clear();
    setFirstName(null);
    setStatus('signedOut');
  }, [queryClient]);

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
      const [refresh, name, kind] = await Promise.all([tokenStore.getRefresh(), tokenStore.getName(), lockKind()]);
      setLock(kind);
      setFirstName(name);
      if (!refresh) setStatus('signedOut');
      else setStatus(kind === 'none' ? 'signedIn' : 'locked');
    })();
  }, [queryClient]);

  // Re-lock after a long background stint.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'background') {
        backgroundedAt.current = Date.now();
      } else if (next === 'active' && backgroundedAt.current) {
        const away = Date.now() - backgroundedAt.current;
        backgroundedAt.current = null;
        if (away > RELOCK_AFTER_MS && lock !== 'none') {
          setStatus((s) => (s === 'signedIn' ? 'locked' : s));
        }
      }
    });
    return () => sub.remove();
  }, [lock]);

  const signIn = useCallback(
    async (tokens: AuthTokens) => {
      setAccessToken(tokens.access_token);
      await tokenStore.setRefresh(tokens.refresh_token);
      await tokenStore.setName(tokens.customer.first_name);
      queryClient.setQueryData(['me'], tokens.customer);
      setFirstName(tokens.customer.first_name);
      setLock(await lockKind());
      setStatus('signedIn');
    },
    [queryClient],
  );

  const signOut = useCallback(
    async ({ everywhere = false } = {}) => {
      // Best effort: the local sign-out must succeed even offline.
      await Promise.race([
        (everywhere ? auth.logoutAll() : auth.logout()).catch(() => undefined),
        new Promise((r) => setTimeout(r, 4000)),
      ]);
      await reset();
    },
    [reset],
  );

  const value = useMemo<SessionValue>(
    () => ({
      status,
      firstName,
      lock,
      gate,
      clearGate: () => setGate(null),
      signIn,
      signOut,
      unlocked: () => setStatus('signedIn'),
      forget: () => signOut(),
    }),
    [status, firstName, lock, gate, signIn, signOut],
  );

  return <SessionContext value={value}>{children}</SessionContext>;
}
