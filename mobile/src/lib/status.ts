import type { ApplicationStatus } from '@/api/types';

export type Tone = 'neutral' | 'info' | 'progress' | 'success' | 'warning' | 'danger';

type StatusCopy = { label: string; tone: Tone; hint: string };

/**
 * Internal workflow states collapse into what a customer can act on or wait for.
 * Staff-only stages (product gate, fee paid…) read as "In review" / "Being prepared".
 */
const APPLICATION: Record<ApplicationStatus, StatusCopy> = {
  draft: { label: 'Draft', tone: 'neutral', hint: 'Finish and submit your application.' },
  submitted: { label: 'Submitted', tone: 'info', hint: "We've received your application." },
  under_review: { label: 'In review', tone: 'progress', hint: 'A loan officer is reviewing your application.' },
  documents_incomplete: {
    label: 'Action needed',
    tone: 'warning',
    hint: 'Some documents need attention. Check them and upload again.',
  },
  approved: { label: 'Approved', tone: 'success', hint: 'Your loan is approved. Review and accept your offer to get it paid out.' },
  offer_sent: {
    label: 'Offer ready',
    tone: 'success',
    hint: 'Your loan offer is ready. Review the terms in the app and accept or decline.',
  },
  offer_accepted: { label: 'Offer accepted', tone: 'success', hint: 'Your loan is being prepared for payout.' },
  product_gate_pending: { label: 'In review', tone: 'progress', hint: 'Final checks are in progress.' },
  processing_fee_paid: { label: 'Being prepared', tone: 'progress', hint: 'Your loan is being prepared for payout.' },
  ready_to_disburse: { label: 'Paying out', tone: 'success', hint: 'Your money is on its way to your bank account.' },
  disbursed: { label: 'Paid out', tone: 'success', hint: 'The money has been sent to your bank account.' },
  rejected: { label: 'Declined', tone: 'danger', hint: "Unfortunately we couldn't approve this application." },
  withdrawn: { label: 'Withdrawn', tone: 'neutral', hint: 'This application was withdrawn.' },
  expired: { label: 'Expired', tone: 'neutral', hint: 'This draft expired. Start a new application.' },
};

export const applicationStatus = (s: string): StatusCopy =>
  APPLICATION[s as ApplicationStatus] ?? { label: s, tone: 'neutral', hint: '' };

/** Customer-facing progress track for a submitted application. */
export const APPLICATION_TRACK = ['Submitted', 'In review', 'Approved', 'Paid out'] as const;

export function trackIndex(s: string): number {
  switch (s) {
    case 'draft':
      return -1;
    case 'submitted':
      return 0;
    case 'under_review':
    case 'documents_incomplete':
    case 'product_gate_pending':
      return 1;
    case 'approved':
    case 'offer_sent':
    case 'offer_accepted':
    case 'processing_fee_paid':
    case 'ready_to_disburse':
      return 2;
    case 'disbursed':
      return 3;
    default:
      return -1;
  }
}

export const isClosedApplication = (s: string) => ['disbursed', 'rejected', 'withdrawn', 'expired'].includes(s);

const LOAN: Record<string, StatusCopy> = {
  active: { label: 'Active', tone: 'info', hint: '' },
  overdue: { label: 'Overdue', tone: 'danger', hint: 'A repayment is overdue. Please pay as soon as you can.' },
  completed: { label: 'Paid off', tone: 'success', hint: 'This loan is fully repaid.' },
  written_off: { label: 'Closed', tone: 'neutral', hint: 'Contact your branch about this loan.' },
};

export const loanStatus = (s: string): StatusCopy => LOAN[s] ?? { label: s, tone: 'neutral', hint: '' };

const INSTALLMENT: Record<string, StatusCopy> = {
  pending: { label: 'Upcoming', tone: 'neutral', hint: '' },
  partial: { label: 'Part paid', tone: 'warning', hint: '' },
  paid: { label: 'Paid', tone: 'success', hint: '' },
  overdue: { label: 'Overdue', tone: 'danger', hint: '' },
};

export const installmentStatus = (s: string): StatusCopy => INSTALLMENT[s] ?? { label: s, tone: 'neutral', hint: '' };

export const DOCUMENT_STATUS: Record<string, StatusCopy> = {
  pending: { label: 'Uploaded', tone: 'info', hint: 'Waiting for review' },
  verified: { label: 'Verified', tone: 'success', hint: '' },
  rejected: { label: 'Re-upload', tone: 'danger', hint: '' },
};

export const CADENCE: Record<string, string> = {
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
  salary_date: 'On salary day',
};
