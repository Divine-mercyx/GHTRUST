import { humanize } from '@/lib/format';

/**
 * Plain-English lines for a loan product's eligibility rules, so customers can compare
 * products before applying. Staff set the rules per product; the common ones get a
 * written sentence, anything else falls back to "Label: value".
 */
const KNOWN: Record<string, (v: unknown) => string | null> = {
  min_years_in_business: (v) => `In business for at least ${v} years`,
  business_type: (v) => `For ${humanize(String(v)).toLowerCase()}s`,
  requires_shop_proof: (v) => (v ? 'Proof of your shop or business premises' : null),
  requires_cash_flow_proof: (v) => (v ? 'Proof of your cash flow' : null),
  borrower_type: (v) => `For ${humanize(String(v)).toLowerCase()}s`,
  min_salary_statement_months: (v) => `${v} months of salary statements`,
  requires_remita_mandate: (v) => (v ? 'Salary repayment mandate (Remita)' : null),
  no_cash_repayment: (v) => (v ? 'Repaid from your salary, not in cash' : null),
  ghtrust_contribution_pct: (v) => `We pay ${v}% of the fees`,
  applicant_contribution_pct: (v) => `You contribute ${v}%`,
  guardian_min_years_employed: (v) => `Guardian employed for ${v}+ years`,
  guardian_max_age: (v) => `Guardian aged ${v} or under`,
  guardian_resident_nigeria: (v) => (v ? 'Guardian lives in Nigeria' : null),
  disburse_to: (v) => `Paid to the ${humanize(String(v)).toLowerCase()}`,
  processing_days: (v) => `Decision in about ${v} days`,
  min_age: (v) => `Aged ${v} or over`,
  max_age: (v) => `Aged ${v} or under`,
  min_amount: (v) => `From ₦${Number(v).toLocaleString()}`,
  max_amount: (v) => `Up to ₦${Number(v).toLocaleString()}`,
};

export function eligibilityLines(rules: Record<string, unknown> | null | undefined): string[] {
  const lines: string[] = [];
  for (const [key, value] of Object.entries(rules ?? {})) {
    if (value === null || value === undefined || value === false || value === '') continue;
    const known = KNOWN[key];
    const line = known ? known(value) : value === true ? humanize(key) : `${humanize(key)}: ${String(value)}`;
    if (line) lines.push(line);
  }
  return lines;
}
