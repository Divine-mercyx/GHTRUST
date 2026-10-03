/**
 * When the app locks (asks for the sign-in PIN or biometrics again).
 *
 * The customer chooses in Security how long the app may stay away (in the background)
 * before it locks: immediately, or after 1, 5, 15 or 30 minutes. The same time also
 * applies while the app is open but untouched, never less than MIN_INACTIVE_MS, so
 * someone typing a long form isn't locked out mid-sentence (typing isn't a touch).
 *
 * The app's own flows that briefly leave it (camera, photo and document pickers,
 * permission prompts) pause the lock: picking a photo must not lock the app.
 */

export type LockChoice = { ms: number; label: string; hint: string };

export const LOCK_CHOICES: LockChoice[] = [
  { ms: 0, label: 'Immediately', hint: 'Every time you leave the app' },
  { ms: 60_000, label: 'After 1 minute', hint: 'Away from the app for a minute' },
  { ms: 5 * 60_000, label: 'After 5 minutes', hint: 'Recommended' },
  { ms: 15 * 60_000, label: 'After 15 minutes', hint: 'Away from the app for 15 minutes' },
  { ms: 30 * 60_000, label: 'After 30 minutes', hint: 'The longest we allow' },
];

export const DEFAULT_LOCK_AFTER_MS = 5 * 60_000;
export const MIN_INACTIVE_MS = 5 * 60_000;

/** A stored value that isn't one of the choices (old or tampered) falls back to the default. */
export function parseLockAfter(raw: string | null): number {
  const ms = Number(raw);
  return raw !== null && LOCK_CHOICES.some((c) => c.ms === ms) ? ms : DEFAULT_LOCK_AFTER_MS;
}

export const lockLabel = (ms: number) => (LOCK_CHOICES.find((c) => c.ms === ms) ?? LOCK_CHOICES[2]).label;

/** Back from the background after `awayMs`: lock? */
export function shouldLockAfterAway(awayMs: number, lockAfterMs: number): boolean {
  return lockAfterMs === 0 ? awayMs > 0 : awayMs > lockAfterMs;
}

/** Open but untouched for `idleMs`: lock? */
export function shouldLockWhenInactive(idleMs: number, lockAfterMs: number): boolean {
  return idleMs > Math.max(lockAfterMs, MIN_INACTIVE_MS);
}

// ── Activity (touches anywhere in the app) ───────────────────────────────────

let lastTouch = Date.now();
export const noteActivity = () => {
  lastTouch = Date.now();
};
export const inactiveFor = (now = Date.now()) => now - lastTouch;

// ── Pausing the lock during the app's own flows ─────────────────────────────

let paused = 0;
// The app reports "active" again around when the picker's promise settles; keep the
// pause a moment longer so that return isn't counted as coming back from away.
const RESUME_GRACE_MS = 1500;

export const lockPaused = () => paused > 0;

/** Run `fn` (a picker, the camera, a permission prompt) without the app locking meanwhile. */
export async function withLockPaused<T>(fn: () => Promise<T>): Promise<T> {
  paused += 1;
  try {
    return await fn();
  } finally {
    setTimeout(() => {
      paused = Math.max(0, paused - 1);
      noteActivity();
    }, RESUME_GRACE_MS);
  }
}
