import { ApiError } from '@/api/errors';

export const DELETE_WORD = 'DELETE';

/** The final button only works with a 6-digit PIN and the word typed out. */
export function canConfirmDeletion(pin: string, word: string): boolean {
  return /^\d{6}$/.test(pin) && word.trim().toUpperCase() === DELETE_WORD;
}

/** The request failed without any reply from the server (status 0: timeout or no connection). */
export const noReply = (error: unknown) => error instanceof ApiError && error.status === 0;

/**
 * A retry after a request whose reply never arrived (timeout, lost connection) can find
 * the account already deleted: the server has ended the session, so it answers 401.
 * Only then is a 401 read as "done"; a wrong PIN is a 401 too, but with its own code.
 */
export function alreadyDeleted(error: unknown, afterUncertain: boolean): boolean {
  return (
    afterUncertain &&
    error instanceof ApiError &&
    error.status === 401 &&
    (error.code === 'SESSION_REVOKED' || error.code === 'ACCOUNT_INACTIVE')
  );
}

/** Something opened since the check (a loan, a credit): the screen re-checks. */
export const blockedByServer = (error: unknown) => error instanceof ApiError && error.status === 409;
