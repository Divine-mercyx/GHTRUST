import type { Application, CollateralInput, GuarantorInput, StepUpdate } from '@/api/types';

import type { FieldDef, WizardPage } from './config';

type Values = Record<string, string>;

/** Everything the wizard edits, as strings (what inputs hold). */
export type Draft = {
  form: Values;
  product: Values;
  guarantors: GuarantorInput[];
  collaterals: CollateralInput[];
};

const asString = (v: unknown): string => (v === null || v === undefined ? '' : String(v));

/** Money fields arrive as "150000.00"; the amount input holds whole naira digits. */
function normalise(values: Record<string, unknown> | null | undefined): Values {
  const out: Values = {};
  for (const [k, v] of Object.entries(values ?? {})) {
    const s = asString(v);
    out[k] = /^\d+\.0+$/.test(s) ? s.replace(/\.0+$/, '') : s;
  }
  return out;
}

export function draftFrom(app: Application): Draft {
  return {
    form: normalise(app.universal_form as Record<string, unknown>),
    product: normalise(app.product_data as Record<string, unknown>),
    guarantors: app.guarantors.map((g) => ({
      full_name: g.full_name,
      phone: g.phone,
      relationship: g.relationship,
      address: g.address,
    })),
    collaterals: app.collaterals.map((c) => ({
      collateral_type: c.collateral_type,
      description: c.description,
      estimated_value: c.estimated_value,
    })),
  };
}

export const getValue = (draft: Draft, def: FieldDef) => (def.target === 'form' ? draft.form : draft.product)[def.key] ?? '';

export function setValue(draft: Draft, def: FieldDef, value: string): Draft {
  return def.target === 'form'
    ? { ...draft, form: { ...draft.form, [def.key]: value } }
    : { ...draft, product: { ...draft.product, [def.key]: value } };
}

const PHONE = /^(\+?234|0)[789]\d{9}$/;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export const isPhone = (v: string) => PHONE.test(v.replace(/[\s-]/g, ''));

// Shown right under the field, so it needn't repeat the label.
const REQUIRED: Record<FieldDef['kind'], string> = {
  text: 'This is required.',
  name: 'Enter a full name.',
  phone: 'Enter a phone number.',
  email: 'Enter an email address.',
  integer: 'Enter a number.',
  money: 'Enter an amount.',
  date: 'Enter a date.',
  select: 'Choose an option.',
  multiline: 'This is required.',
};

export function validateField(def: FieldDef, raw: string): string | null {
  const v = raw.trim();
  if (!v) return def.required ? REQUIRED[def.kind] : null;
  switch (def.kind) {
    case 'phone':
      return isPhone(v) ? null : 'Enter a valid Nigerian phone number.';
    case 'email':
      return EMAIL.test(v) ? null : 'Enter a valid email address.';
    case 'name':
      return v.length >= 3 && /\s/.test(v) ? null : 'Enter first and last name.';
    case 'integer':
    case 'money': {
      const n = Number(v);
      if (!Number.isFinite(n)) return 'Enter a number.';
      if (def.min !== undefined && n < def.min) {
        return def.kind === 'money' ? `Must be at least ₦${def.min.toLocaleString()}.` : `Must be at least ${def.min}.`;
      }
      if (def.max !== undefined && n > def.max) return `Must be ${def.max} or less.`;
      return null;
    }
    default:
      return null;
  }
}

export function validatePage(fields: FieldDef[], draft: Draft): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const def of fields) {
    const error = validateField(def, getValue(draft, def));
    if (error) errors[def.key] = error;
  }
  return errors;
}

export function validateGuarantors(list: GuarantorInput[]): string | null {
  if (!list.length) return 'Add at least one guarantor.';
  for (const g of list) {
    if (!g.full_name?.trim() || !/\s/.test(g.full_name.trim())) return "Enter each guarantor's full name.";
    if (!g.phone || !isPhone(g.phone)) return "Enter a valid phone number for each guarantor.";
    if (!g.relationship) return 'Choose how each guarantor is related to you.';
  }
  return null;
}

/** What this screen sends. Partial updates merge server-side. */
export function payloadFor(page: WizardPage, fields: FieldDef[], draft: Draft, totalSteps: number): StepUpdate {
  const update: StepUpdate = { step: page.stepIndex, total_steps: totalSteps };
  const form: Record<string, unknown> = {};
  const productData: Record<string, unknown> = {};

  for (const def of fields) {
    const raw = getValue(draft, def).trim();
    const value = raw === '' ? null : def.kind === 'integer' || def.kind === 'money' ? Number(raw) : raw;
    // Empty fields are omitted: the API validates email/date formats, and merges partial updates.
    if (value === null) continue;
    if (def.target === 'form') form[def.key] = value;
    else productData[def.key] = value;
  }

  if (page.id === 'request' && draft.product.tenure_months) {
    // The paper form's "repayment period"; the servicing engine reads tenure_months.
    const months = Number(draft.product.tenure_months);
    form.repayment_period = `${months} month${months === 1 ? '' : 's'}`;
  }
  if (page.id === 'bank') {
    for (const key of ['bank_name', 'bank_code', 'bank_account_number', 'bank_account_name']) {
      if (draft.form[key]) form[key] = draft.form[key];
    }
  }
  if (page.id === 'guarantor') {
    // Half-filled rows are dropped so "Save & exit" never fails on them.
    update.guarantors = draft.guarantors
      .filter((g) => g.full_name?.trim().length >= 2)
      .map((g) => ({ ...g, full_name: g.full_name.trim() }));
    update.collaterals = draft.collaterals
      .filter((c) => (c.description?.trim().length ?? 0) >= 3)
      .map((c) => ({ ...c, description: c.description.trim(), estimated_value: c.estimated_value || null }));
  }

  if (Object.keys(form).length) update.universal_form = form as StepUpdate['universal_form'];
  if (Object.keys(productData).length) update.product_data = productData as StepUpdate['product_data'];
  return update;
}
