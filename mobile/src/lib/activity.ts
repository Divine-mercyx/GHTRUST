import type Ionicons from '@expo/vector-icons/Ionicons';

import type { ApplicationSummary, Loan, WalletTransaction } from '@/api/types';

import { productName } from '@/lib/products';
import { applicationStatus, loanStatus, type Tone } from './status';

/** One row of "Recent activity" on the home screen. */
export type Activity = {
  id: string;
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  subtitle: string;
  amount: string | null;
  /** Money coming to the customer shows in green with a plus. */
  direction: 'in' | 'out' | 'none';
  status: { label: string; tone: Tone };
  at: string;
  href: `/loans/${string}` | `/applications/${string}` | `/apply/${string}` | `/transactions/${string}`;
};

const TX_STATUS: Record<WalletTransaction['status'], { label: string; tone: Tone }> = {
  completed: { label: 'Completed', tone: 'success' },
  pending: { label: 'Pending', tone: 'warning' },
  failed: { label: 'Failed', tone: 'danger' },
};

const TX_ICON: Record<WalletTransaction['kind'], keyof typeof Ionicons.glyphMap> = {
  funding: 'arrow-down',
  loan_payout: 'cash',
  withdrawal: 'arrow-up',
  repayment: 'checkmark-done',
  investment: 'trending-up',
  investment_payout: 'sparkles',
};

/** "******6789" → "•••• 6789", short enough to fit next to a bank name. */
export const shortAccount = (text: string) => text.replace(/\*+(\d{4})/, '•••• $1');

export const transactionStatus = (s: WalletTransaction['status']) => TX_STATUS[s] ?? TX_STATUS.pending;
export const transactionIcon = (k: WalletTransaction['kind']) => TX_ICON[k] ?? 'swap-vertical';

/** Subtitle for a wallet transaction: the loan it paid, the bank it went to, or how it came in. */
export function transactionDetail(tx: WalletTransaction): string {
  if (tx.kind === 'repayment') return tx.loan_product ? productName(tx.loan_product) : 'From your wallet';
  if (tx.kind === 'loan_payout') return tx.loan_product ? productName(tx.loan_product) : 'Loan';
  return tx.detail ? shortAccount(tx.detail) : '';
}

export function fromTransaction(tx: WalletTransaction): Activity {
  return {
    id: `tx-${tx.id}`,
    icon: transactionIcon(tx.kind),
    title: tx.title,
    subtitle: transactionDetail(tx),
    amount: String(tx.amount),
    // A failed withdrawal never left, so it isn't shown as money out.
    direction: tx.direction === 'in' ? 'in' : tx.status === 'failed' ? 'none' : 'out',
    status: transactionStatus(tx.status),
    at: tx.created_at,
    href: `/transactions/${tx.id}`,
  };
}

/**
 * The customer's latest events, newest first: wallet money in and out (when the wallet is
 * on), loans paid out, and applications.
 */
export function recentActivity(
  loans: Loan[],
  applications: ApplicationSummary[],
  transactions: WalletTransaction[] = [],
  limit = 5,
): Activity[] {
  const items: Activity[] = transactions.map(fromTransaction);

  for (const loan of loans) {
    const s = loanStatus(loan.status);
    items.push({
      id: `loan-${loan.id}`,
      icon: loan.status === 'overdue' ? 'alert-circle' : loan.status === 'active' ? 'cash' : 'checkmark-done',
      title: productName(loan.product_type),
      subtitle: 'Paid out',
      amount: loan.principal,
      direction: 'in',
      status: { label: s.label, tone: s.tone },
      at: loan.disbursement_date ?? loan.created_at,
      href: `/loans/${loan.id}`,
    });
  }

  for (const app of applications) {
    // A paid-out application already shows as its loan.
    if (app.status === 'disbursed') continue;
    const s = applicationStatus(app.status);
    const draft = app.status === 'draft';
    items.push({
      id: `app-${app.id}`,
      icon: draft ? 'create' : 'document-text',
      // Titles stay short so they fit narrow phones; the badge carries the state.
      title: app.product_name,
      subtitle: draft ? 'Tap to finish' : 'Application',
      amount: app.approved_amount ?? app.requested_amount,
      direction: 'none',
      status: { label: s.label, tone: s.tone },
      at: app.submitted_at ?? app.created_at,
      href: draft ? `/apply/${app.id}` : `/applications/${app.id}`,
    });
  }

  return items.sort((a, b) => b.at.localeCompare(a.at)).slice(0, limit);
}

/** "Today", "Yesterday", "3 days ago", else "12 Aug"; with `withTime`, "Today, 2:05 pm". */
export function activityWhen(value: string, now = new Date(), withTime = false): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(d)) / 86_400_000);
  const day =
    days <= 0
      ? 'Today'
      : days === 1
        ? 'Yesterday'
        : days < 7 && !withTime
          ? `${days} days ago`
          : `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  if (!withTime) return day;
  const h = d.getHours();
  return `${day}, ${h % 12 || 12}:${String(d.getMinutes()).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
