/** Money arrives from the API as decimal strings; never do float maths on it for display. */
export function naira(value: string | number | null | undefined, opts: { kobo?: boolean } = {}): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return '—';
  const kobo = opts.kobo ?? !Number.isInteger(n);
  return `₦${n.toLocaleString('en-NG', { minimumFractionDigits: kobo ? 2 : 0, maximumFractionDigits: kobo ? 2 : 0 })}`;
}

/** Compact for tight spaces: ₦1.2m, ₦850k. */
export function nairaShort(value: string | number | null | undefined): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  if (Math.abs(n) >= 1_000_000) return `₦${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}m`;
  if (Math.abs(n) >= 1_000) return `₦${Math.round(n / 1_000)}k`;
  return naira(n);
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Parse "YYYY-MM-DD" as a calendar date (not UTC midnight, which shifts the day). */
function parse(value: string): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(value);
}

export function date(value: string | null | undefined): string {
  if (!value) return '—';
  const d = parse(value);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  const h = d.getHours();
  const time = `${h % 12 || 12}:${String(d.getMinutes()).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`;
  return `${date(value.slice(0, 10))}, ${time}`;
}

/** Whole days from today to a calendar date (negative = past). */
export function daysUntil(value: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((parse(value).getTime() - today.getTime()) / 86_400_000);
}

export function relativeDue(value: string | null | undefined): string {
  if (!value) return '';
  const d = daysUntil(value);
  if (d === 0) return 'Due today';
  if (d === 1) return 'Due tomorrow';
  if (d > 1) return `Due in ${d} days`;
  return d === -1 ? '1 day overdue' : `${-d} days overdue`;
}

export function humanize(value: string | null | undefined): string {
  if (!value) return '';
  const s = value.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Keep digits only; used for phone, BVN, OTP and amount inputs. */
export const digits = (value: string) => value.replace(/\D+/g, '');

/** "1234567" → "1,234,567" while typing an amount. */
export function groupThousands(raw: string): string {
  const d = digits(raw).replace(/^0+(?=\d)/, '');
  return d.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

export function greeting(now = new Date()): string {
  const h = now.getHours();
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}
