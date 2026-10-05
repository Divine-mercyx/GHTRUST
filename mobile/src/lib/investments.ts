import type { Investment, InvestmentPlan } from '@/api/types';
import { API_ORIGIN } from '@/api/config';
import type { Tone } from '@/lib/status';

/**
 * Same sum as the server (backend investments/service.py projected_return): simple interest at
 * the plan's yearly rate, rounded to kobo. The server's figure is the one that counts.
 */
export function projectedReturn(amount: number, yearlyRate: number, months: number): number {
  return Math.round(amount * (yearlyRate / 100) * (months / 12) * 100) / 100;
}

/** The date an investment started today would pay out (same month arithmetic as the server). */
export function maturityFrom(months: number, start = new Date()): Date {
  const d = new Date(start.getFullYear(), start.getMonth() + months, 1);
  const lastDay = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
  d.setDate(Math.min(start.getDate(), lastDay));
  return d;
}

export const RISK: Record<string, { label: string; tone: Tone }> = {
  low: { label: 'Low risk', tone: 'success' },
  medium: { label: 'Medium risk', tone: 'warning' },
  high: { label: 'High risk', tone: 'danger' },
};

export const planImage = (p: Pick<InvestmentPlan, 'image_url'>) => (p.image_url ? `${API_ORIGIN}${p.image_url}` : null);

/** How far an investment is towards maturity, 0..1. */
export function progress(inv: Investment, now = Date.now()): number {
  const start = new Date(inv.start_date).getTime();
  const end = new Date(inv.maturity_date).getTime();
  if (inv.status !== 'active' || end <= start) return 1;
  return Math.max(0, Math.min(1, (now - start) / (end - start)));
}

export function investAmountError(amount: string, plan: InvestmentPlan): string | null {
  if (!amount) return null;
  const v = Number(amount);
  if (v < Number(plan.min_amount)) return `The minimum for this plan is ₦${Number(plan.min_amount).toLocaleString('en-NG')}.`;
  if (plan.max_amount && v > Number(plan.max_amount))
    return `The maximum for this plan is ₦${Number(plan.max_amount).toLocaleString('en-NG')}.`;
  return null;
}
