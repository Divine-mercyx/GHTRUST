import { describe, expect, it } from '@jest/globals';
import type { WalletTransaction } from '@/api/types';

import { activityWhen, fromTransaction, recentActivity, shortAccount } from '../activity';
import { applicationStatus, trackIndex } from '../status';

const tx = (over: Partial<WalletTransaction>): WalletTransaction =>
  ({
    id: 'w_1',
    kind: 'withdrawal',
    direction: 'out',
    amount: 25000,
    status: 'pending',
    title: 'Withdrawal',
    detail: 'GTBank · ******6789',
    reference: 'ref',
    loan_id: null,
    loan_product: null,
    note: null,
    created_at: '2026-09-29T20:00:00Z',
    completed_at: null,
    ...over,
  }) as WalletTransaction;

describe('wallet transactions in activity', () => {
  it('shows withdrawals as money out with a short account number', () => {
    const row = fromTransaction(tx({}));
    expect(row.direction).toBe('out');
    expect(row.subtitle).toBe('GTBank · •••• 6789');
    expect(row.href).toBe('/transactions/w_1');
    expect(row.status.label).toBe('Pending');
  });
  it("doesn't count a failed withdrawal as money out", () => {
    expect(fromTransaction(tx({ status: 'failed' })).direction).toBe('none');
  });
  it('names the loan a repayment went to', () => {
    const row = fromTransaction(tx({ id: 'j_1', kind: 'repayment', loan_product: 'business_loan', detail: null }));
    expect(row.subtitle).toBe('Business loan');
  });
  it('merges loans, applications and transactions newest first, capped', () => {
    const items = recentActivity(
      [],
      [],
      [tx({ id: 'w_old', created_at: '2026-01-01T00:00:00Z' }), tx({ id: 'w_new', created_at: '2026-09-01T00:00:00Z' })],
      1,
    );
    expect(items.map((i) => i.id)).toEqual(['tx-w_new']);
  });
  it('masks accounts consistently', () => {
    expect(shortAccount('******6789')).toBe('•••• 6789');
  });
});

describe('activityWhen', () => {
  const now = new Date(2026, 8, 29, 18, 0);
  it('says today, yesterday, days ago, then a date', () => {
    expect(activityWhen(new Date(2026, 8, 29, 9, 0).toISOString(), now)).toBe('Today');
    expect(activityWhen(new Date(2026, 8, 28, 9, 0).toISOString(), now)).toBe('Yesterday');
    expect(activityWhen(new Date(2026, 8, 25, 9, 0).toISOString(), now)).toBe('4 days ago');
    expect(activityWhen(new Date(2026, 7, 1, 9, 0).toISOString(), now)).toBe('1 Aug');
  });
  it('adds a time for history lists', () => {
    expect(activityWhen(new Date(2026, 8, 29, 14, 5).toISOString(), now, true)).toBe('Today, 2:05 pm');
  });
});

describe('application status for customers', () => {
  it('hides internal stages behind plain words', () => {
    expect(applicationStatus('product_gate_pending').label).toBe('In review');
    expect(applicationStatus('ready_to_disburse').label).toBe('Paying out');
  });
  it('places each status on the progress track', () => {
    expect(trackIndex('draft')).toBe(-1);
    expect(trackIndex('documents_incomplete')).toBe(1);
    expect(trackIndex('approved')).toBe(2);
    expect(trackIndex('disbursed')).toBe(3);
  });
});

describe('loans paid into the wallet', () => {
  it('show as money in, named after the loan', () => {
    const row = fromTransaction(
      tx({ kind: 'loan_payout', direction: 'in', status: 'completed', title: 'Loan paid out', loan_product: 'business_loan', loan_id: 'l1' }),
    );
    expect(row.direction).toBe('in');
    expect(row.icon).toBe('cash');
    expect(row.subtitle).toMatch(/Business/);
  });
});
