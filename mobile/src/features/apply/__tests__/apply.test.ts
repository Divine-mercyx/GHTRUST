import { describe, expect, it } from '@jest/globals';
import type { FieldDef } from '../config';
import { guarantorOptional, maxTenureMonths, pagesFor, submitProblems } from '../config';
import { isPhone, payloadFor, validateField, validateGuarantors, type Draft } from '../draft';

const field = (kind: FieldDef['kind'], extra: Partial<FieldDef> = {}): FieldDef =>
  ({ key: 'x', target: 'form', label: 'X', kind, ...extra }) as FieldDef;

describe('field validation', () => {
  it('requires required fields with wording that fits the kind', () => {
    expect(validateField(field('money', { required: true }), ' ')).toBe('Enter an amount.');
    expect(validateField(field('select', { required: true }), '')).toBe('Choose an option.');
    expect(validateField(field('text'), '')).toBeNull();
  });
  it('checks Nigerian phone numbers', () => {
    for (const ok of ['08035794364', '+2348035794364', '0803 579 4364', '07012345678']) expect(isPhone(ok)).toBe(true);
    for (const bad of ['0803579436', '05035794364', '12345']) expect(isPhone(bad)).toBe(false);
  });
  it('checks names, emails and number ranges', () => {
    expect(validateField(field('name'), 'Adaeze')).toBe('Enter first and last name.');
    expect(validateField(field('name'), 'Adaeze Okafor')).toBeNull();
    expect(validateField(field('email'), 'ada@x')).toBe('Enter a valid email address.');
    expect(validateField(field('money', { min: 50000 }), '1000')).toBe('Must be at least ₦50,000.');
    expect(validateField(field('integer', { max: 12 }), '13')).toBe('Must be 12 or less.');
  });
  it('needs a named guarantor with a real phone and relationship', () => {
    expect(validateGuarantors([])).toBe('Add at least one guarantor.');
    expect(validateGuarantors([{ full_name: 'Tolu', phone: '08031234567', relationship: 'Friend' }])).toMatch(/full name/);
    expect(validateGuarantors([{ full_name: 'Tolu Ade', phone: '123', relationship: 'Friend' }])).toMatch(/phone/);
    expect(validateGuarantors([{ full_name: 'Tolu Ade', phone: '08031234567', relationship: 'Friend' }])).toBeNull();
  });
});

describe('tenure limits', () => {
  it('turns the product limit in days into whole months', () => {
    expect(maxTenureMonths(null)).toBe(24);
    expect(maxTenureMonths(180)).toBe(6);
    expect(maxTenureMonths(20)).toBe(1);
  });
  it('caps the tenure field and always ends on review', () => {
    const pages = pagesFor(['universal_form', 'business_details', 'documents'], 90);
    const tenure = pages.flatMap((p) => p.fields ?? []).find((f) => f.key === 'tenure_months');
    expect(tenure?.max).toBe(3);
    expect(pages[pages.length - 1].id).toBe('review');
    expect(pages.find((p) => p.id === 'business')?.stepIndex).toBe(2);
  });
});

describe('submit problems', () => {
  it('turns server checks into customer instructions linked to a screen', () => {
    const problems = submitProblems([
      'Missing universal form field: bank_code',
      'Missing universal form field: bank_account_number',
      'Missing document: Bank statement (6 months)',
      'At least one guarantor is required',
    ]);
    expect(problems).toEqual([
      { text: 'Add the bank account for your loan.', page: 'bank' },
      { text: 'Upload your bank statement (6 months).', page: 'documents' },
      { text: 'Add at least one guarantor.', page: 'guarantor' },
    ]);
  });
});

describe('payloadFor', () => {
  it('sends numbers as numbers and leaves out empty fields', () => {
    const [request] = pagesFor(['universal_form'], null).filter((p) => p.id === 'request');
    const draft: Draft = {
      form: { requested_amount: '250000', purpose: '' },
      product: {},
      guarantors: [],
      collaterals: [],
    };
    const payload = payloadFor(request, request.fields ?? [], draft, 4);
    expect(payload.step).toBe(request.stepIndex);
    expect(payload.universal_form).toMatchObject({ requested_amount: 250000 });
    expect(payload.universal_form).not.toHaveProperty('purpose');
  });
});

describe('website catalogue', () => {
  it('asks LPO applicants when their client pays, repaid in one payment', () => {
    const request = pagesFor(['universal_form', 'lpo_details'], null).find((p) => p.id === 'request')!;
    const tenure = request.fields!.find((f) => f.key === 'tenure_months')!;
    expect(tenure.label).toMatch(/client pay/);
    expect(pagesFor(['lpo_details'], null).map((p) => p.id)).toContain('lpo');
    expect(pagesFor(['group_details'], null).map((p) => p.id)).toContain('group');
  });
  it('makes the guarantor optional below the business loan amount', () => {
    const rules = { security_from_amount: 100000 };
    expect(guarantorOptional(rules)).toBe(true);
    expect(guarantorOptional({})).toBe(false);
    expect(validateGuarantors([], true)).toBeNull();
    expect(validateGuarantors([])).toBe('Add at least one guarantor.');
    const guarantor = pagesFor(['guarantor_collateral'], null, rules).find((p) => p.id === 'guarantor')!;
    expect(guarantor.subtitle).toMatch(/Optional below ₦100,000/);
  });
  it('points the new submit checks at the right screen', () => {
    const problems = submitProblems([
      'For loans of ₦100,000 and above, add a guarantor with their ID and photo, or upload your collateral documents',
      'A group needs between 2 and 15 members',
      'LPO details are required: the issuing organisation and the contract value',
    ]);
    expect(problems.map((p) => p.page)).toEqual(['guarantor', 'group', 'lpo']);
  });
});

