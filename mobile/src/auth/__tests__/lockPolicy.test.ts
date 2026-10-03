import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';

import {
  DEFAULT_LOCK_AFTER_MS,
  LOCK_CHOICES,
  inactiveFor,
  lockLabel,
  lockPaused,
  noteActivity,
  parseLockAfter,
  shouldLockAfterAway,
  shouldLockWhenInactive,
  withLockPaused,
} from '../lockPolicy';

const MIN = 60_000;

describe('lock choices', () => {
  it('offers immediately, 1, 5, 15 and 30 minutes, defaulting to 5', () => {
    expect(LOCK_CHOICES.map((c) => c.ms)).toEqual([0, MIN, 5 * MIN, 15 * MIN, 30 * MIN]);
    expect(DEFAULT_LOCK_AFTER_MS).toBe(5 * MIN);
    expect(lockLabel(0)).toBe('Immediately');
  });

  it('ignores stored values that are not a choice', () => {
    expect(parseLockAfter(String(15 * MIN))).toBe(15 * MIN);
    expect(parseLockAfter('0')).toBe(0);
    expect(parseLockAfter(null)).toBe(DEFAULT_LOCK_AFTER_MS);
    expect(parseLockAfter(String(24 * 60 * MIN))).toBe(DEFAULT_LOCK_AFTER_MS); // no "never"
    expect(parseLockAfter('nonsense')).toBe(DEFAULT_LOCK_AFTER_MS);
  });
});

describe('locking after time away', () => {
  it('"Immediately" locks on any return', () => {
    expect(shouldLockAfterAway(500, 0)).toBe(true);
  });
  it('a timer locks only once it has passed', () => {
    expect(shouldLockAfterAway(4 * MIN, 5 * MIN)).toBe(false);
    expect(shouldLockAfterAway(5 * MIN + 1, 5 * MIN)).toBe(true);
    expect(shouldLockAfterAway(20 * MIN, 30 * MIN)).toBe(false);
  });
});

describe('locking while open but untouched', () => {
  it('uses the chosen time, never less than 5 minutes', () => {
    expect(shouldLockWhenInactive(3 * MIN, 0)).toBe(false); // typing a form isn't a touch
    expect(shouldLockWhenInactive(5 * MIN + 1, 0)).toBe(true);
    expect(shouldLockWhenInactive(10 * MIN, 15 * MIN)).toBe(false);
    expect(shouldLockWhenInactive(15 * MIN + 1, 15 * MIN)).toBe(true);
  });

  it('a touch restarts the clock', () => {
    noteActivity();
    expect(inactiveFor()).toBeLessThan(1000);
  });
});

describe("the app's own flows pause the lock", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  it('stays paused while a picker is open and briefly after it returns', async () => {
    let finish: (v: string) => void = () => undefined;
    const picking = withLockPaused(() => new Promise<string>((r) => (finish = r)));
    expect(lockPaused()).toBe(true);
    finish('photo');
    await expect(picking).resolves.toBe('photo');
    expect(lockPaused()).toBe(true); // the "active again" event may still be on its way
    jest.advanceTimersByTime(2000);
    expect(lockPaused()).toBe(false);
  });

  it('a failed picker still releases the pause', async () => {
    await expect(withLockPaused(() => Promise.reject(new Error('denied')))).rejects.toThrow('denied');
    jest.advanceTimersByTime(2000);
    expect(lockPaused()).toBe(false);
  });
});
