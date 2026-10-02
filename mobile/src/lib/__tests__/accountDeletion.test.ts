import { describe, expect, it } from '@jest/globals';

import { ApiError, messageFor } from '@/api/errors';

import { alreadyDeleted, blockedByServer, canConfirmDeletion, noReply } from '../accountDeletion';
import { eligibilityLines } from '../eligibility';

const err = (status: number, code: string) => new ApiError(status, code, code);

describe('account deletion', () => {
  it('needs a 6-digit PIN and the word DELETE before the button works', () => {
    expect(canConfirmDeletion('123456', 'DELETE')).toBe(true);
    expect(canConfirmDeletion('123456', ' delete ')).toBe(true);
    expect(canConfirmDeletion('12345', 'DELETE')).toBe(false);
    expect(canConfirmDeletion('123456', 'yes')).toBe(false);
  });

  it('treats a 401 as "already deleted" only after an attempt that got no reply', () => {
    expect(alreadyDeleted(err(401, 'SESSION_REVOKED'), true)).toBe(true);
    expect(alreadyDeleted(err(401, 'ACCOUNT_INACTIVE'), true)).toBe(true);
    // First attempt: a revoked session is just a revoked session.
    expect(alreadyDeleted(err(401, 'SESSION_REVOKED'), false)).toBe(false);
    // A wrong PIN is never "deleted".
    expect(alreadyDeleted(err(401, 'PIN_ATTEMPTS_EXCEEDED'), true)).toBe(false);
    expect(alreadyDeleted(err(400, 'LOGIN_PIN_INVALID'), true)).toBe(false);
  });

  it('spots requests that got no reply, and server-side blocks', () => {
    expect(noReply(err(0, 'TIMEOUT'))).toBe(true);
    expect(noReply(err(500, 'INTERNAL_ERROR'))).toBe(false);
    expect(blockedByServer(err(409, 'LOAN_OUTSTANDING'))).toBe(true);
  });

  it('explains an outstanding loan in the words agreed for the store review', () => {
    expect(messageFor(err(409, 'LOAN_OUTSTANDING'))).toBe(
      'Account deletion cannot be processed while you have an active loan or outstanding repayment balance. Please settle all pending dues before requesting deletion.',
    );
    expect(messageFor(err(409, 'WALLET_NOT_EMPTY'))).toMatch(/Withdraw it/);
  });
});

describe('loan eligibility', () => {
  it('turns product rules into readable lines and skips switched-off ones', () => {
    expect(
      eligibilityLines({
        min_years_in_business: 3,
        requires_shop_proof: true,
        requires_cash_flow_proof: false,
        minimum_turnover: 500000,
        has_bvn: true,
      }),
    ).toEqual(['In business for at least 3 years', 'Proof of your shop or business premises', 'Minimum turnover: 500000', 'Has bvn']);
    expect(eligibilityLines(null)).toEqual([]);
  });
});
