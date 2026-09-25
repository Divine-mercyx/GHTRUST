/**
 * Loan application wizard, driven by each product's `workflow_steps` from the API.
 * Backend steps map to one or more screens; screens declare their fields here.
 */
export type Target = 'form' | 'product';
export type FieldKind = 'text' | 'name' | 'phone' | 'email' | 'integer' | 'money' | 'date' | 'select' | 'multiline';

export type FieldDef = {
  key: string;
  target: Target;
  label: string;
  kind: FieldKind;
  required?: boolean;
  options?: string[];
  placeholder?: string;
  hint?: string;
  min?: number;
  max?: number;
};

export type PageId =
  | 'about'
  | 'request'
  | 'bank'
  | 'kin'
  | 'business'
  | 'employment'
  | 'student'
  | 'guardian'
  | 'asset'
  | 'guarantor'
  | 'documents'
  | 'review';

export type PageDef = { id: PageId; title: string; subtitle: string; fields?: FieldDef[] };

const RELATIONSHIPS = ['Spouse', 'Parent', 'Sibling', 'Child', 'Relative', 'Friend', 'Colleague', 'Business partner', 'Other'];

const form = (key: string, label: string, kind: FieldKind, extra: Partial<FieldDef> = {}): FieldDef => ({
  key,
  target: 'form',
  label,
  kind,
  ...extra,
});
const product = (key: string, label: string, kind: FieldKind, extra: Partial<FieldDef> = {}): FieldDef => ({
  key,
  target: 'product',
  label,
  kind,
  ...extra,
});

export const PAGES: Record<PageId, PageDef> = {
  about: {
    id: 'about',
    title: 'About you',
    subtitle: "We've filled in what we have from your BVN. Check it and add anything missing.",
    fields: [
      form('full_name', 'Full name', 'name', { required: true }),
      form('phone', 'Phone number', 'phone', { required: true }),
      form('email', 'Email', 'email'),
      form('gender', 'Gender', 'select', { options: ['Male', 'Female'] }),
      form('date_of_birth', 'Date of birth', 'date'),
      form('marital_status', 'Marital status', 'select', { options: ['Single', 'Married', 'Divorced', 'Widowed'] }),
      form('residential_address', 'Home address', 'multiline', { required: true }),
      form('residential_landmark', 'Nearest landmark', 'text'),
      form('id_type', 'ID type', 'select', {
        options: ['National ID (NIN)', "Driver's licence", "Voter's card", 'International passport'],
      }),
      form('id_number', 'ID number', 'text'),
    ],
  },
  request: {
    id: 'request',
    title: 'Your loan',
    subtitle: 'Tell us how much you need and how you plan to repay.',
    fields: [
      form('requested_amount', 'How much do you need?', 'money', { required: true, min: 10_000 }),
      product('tenure_months', 'Repay over (months)', 'integer', { required: true, min: 1, max: 24 }),
      form('purpose', 'What is the loan for?', 'multiline', { required: true }),
      form('monthly_income', 'Monthly income', 'money', { required: true, min: 1 }),
      form('source_of_repayment', 'How will you repay?', 'select', {
        required: true,
        options: ['Business income', 'Salary', 'Contract / project income', 'Rental income', 'Other'],
      }),
      form('proposed_monthly_repayment', 'What can you repay monthly?', 'money'),
    ],
  },
  bank: {
    id: 'bank',
    title: 'Bank account',
    subtitle: "Where we'll pay the loan. It must be an account in your name.",
  },
  kin: {
    id: 'kin',
    title: 'Next of kin',
    subtitle: 'Someone we can contact if we cannot reach you.',
    fields: [
      form('next_of_kin_name', 'Full name', 'name', { required: true }),
      form('next_of_kin_phone', 'Phone number', 'phone', { required: true }),
      form('next_of_kin_relationship', 'Relationship', 'select', { required: true, options: RELATIONSHIPS }),
      form('next_of_kin_address', 'Address', 'multiline'),
      form('next_of_kin_email', 'Email', 'email'),
    ],
  },
  business: {
    id: 'business',
    title: 'Your business',
    subtitle: 'Business loans are for traders operating for 3 years or more.',
    fields: [
      product('trade_type', 'What do you sell?', 'text', { required: true, placeholder: 'e.g. Provisions, textiles' }),
      product('years_in_operation', 'Years in business', 'integer', {
        required: true,
        min: 3,
        max: 80,
        hint: 'At least 3 years.',
      }),
      form('nature_of_business', 'Type of business', 'select', {
        options: ['Retail', 'Wholesale', 'Manufacturing', 'Services', 'Agriculture', 'Other'],
      }),
      form('office_shop_address', 'Shop / office address', 'multiline'),
      product('monthly_cash_flow', 'Average monthly sales', 'money'),
    ],
  },
  employment: {
    id: 'employment',
    title: 'Your employment',
    subtitle: 'Payday loans are repaid from your salary on pay day.',
    fields: [
      product('employer_name', 'Employer', 'text', { required: true }),
      form('place_of_work', 'Office address', 'multiline'),
      product('salary_pay_day', 'Day of the month you are paid', 'integer', { required: true, min: 1, max: 31 }),
      product('monthly_salary', 'Monthly salary (net)', 'money'),
    ],
  },
  student: {
    id: 'student',
    title: 'Student & school',
    subtitle: 'Details of the student this loan is for.',
    fields: [
      product('student_full_name', "Student's full name", 'name', { required: true }),
      product('school_name', 'School', 'text', { required: true }),
      product('school_country', 'Country of study', 'text'),
      product('course_of_study', 'Course', 'text'),
      product('tuition_total', 'Total tuition', 'money'),
    ],
  },
  guardian: {
    id: 'guardian',
    title: 'Guardian',
    subtitle: 'As guardian, you apply on behalf of the student.',
    fields: [
      product('relationship_to_student', 'Relationship to student', 'select', {
        required: true,
        options: ['Parent', 'Guardian', 'Sibling', 'Relative', 'Sponsor'],
      }),
      product('guardian_employer', 'Your employer', 'text'),
      product('guardian_years_employed', 'Years with this employer', 'integer', { min: 0, max: 60 }),
    ],
  },
  asset: {
    id: 'asset',
    title: 'The asset',
    subtitle: 'The asset stays in GH Trust’s name until the loan is fully repaid.',
    fields: [
      product('asset_description', 'What are you buying?', 'text', { required: true, placeholder: 'e.g. Toyota Corolla 2020' }),
      product('asset_value', 'Price of the asset', 'money', { required: true, min: 1 }),
      product('vendor_name', 'Seller / vendor', 'text'),
    ],
  },
  guarantor: {
    id: 'guarantor',
    title: 'Guarantor',
    subtitle: 'At least one person who will guarantee this loan.',
  },
  documents: {
    id: 'documents',
    title: 'Documents',
    subtitle: 'Take clear photos or upload PDFs. Everything must be readable.',
  },
  review: {
    id: 'review',
    title: 'Review & submit',
    subtitle: 'Check everything before you send it.',
  },
};

const STEP_PAGES: Record<string, PageId[]> = {
  universal_form: ['about', 'request', 'bank', 'kin'],
  business_details: ['business'],
  employment_details: ['employment'],
  student_school_details: ['student'],
  guardian_details: ['guardian'],
  asset_details: ['asset'],
  guarantor_collateral: ['guarantor'],
  documents: ['documents'],
  review_submit: ['review'],
};

export type WizardPage = PageDef & { stepIndex: number };

/** Screens for a product, each tagged with its backend step (1-based, for `step`). */
export function pagesFor(workflowSteps: string[]): WizardPage[] {
  const pages: WizardPage[] = [];
  workflowSteps.forEach((step, i) => {
    for (const id of STEP_PAGES[step] ?? []) pages.push({ ...PAGES[id], stepIndex: i + 1 });
  });
  if (!pages.some((p) => p.id === 'review')) pages.push({ ...PAGES.review, stepIndex: workflowSteps.length });
  return pages;
}

/** What to tell the customer for each required universal-form field the server reports missing. */
const MISSING_FIELD: Record<string, { text: string; page: PageId }> = {
  full_name: { text: 'Add your full name.', page: 'about' },
  phone: { text: 'Add your phone number.', page: 'about' },
  residential_address: { text: 'Add your home address.', page: 'about' },
  bvn: { text: 'Your BVN is missing. Please contact GH Trust.', page: 'about' },
  requested_amount: { text: 'Tell us how much you need.', page: 'request' },
  purpose: { text: 'Tell us what the loan is for.', page: 'request' },
  monthly_income: { text: 'Add your monthly income.', page: 'request' },
  repayment_period: { text: 'Choose how many months you’ll repay over.', page: 'request' },
  source_of_repayment: { text: 'Tell us how you’ll repay.', page: 'request' },
  bank_name: { text: 'Add the bank account for your loan.', page: 'bank' },
  bank_code: { text: 'Add the bank account for your loan.', page: 'bank' },
  bank_account_number: { text: 'Add the bank account for your loan.', page: 'bank' },
  bank_account_name: { text: 'Add the bank account for your loan.', page: 'bank' },
  next_of_kin_name: { text: 'Add your next of kin’s details.', page: 'kin' },
  next_of_kin_phone: { text: 'Add your next of kin’s details.', page: 'kin' },
  next_of_kin_relationship: { text: 'Add your next of kin’s details.', page: 'kin' },
};

export type SubmitProblem = { text: string; page: PageId | null };

/**
 * Turn the server's submit checks (written for developers, e.g. "Missing universal
 * form field: bank_code") into customer instructions linked to the screen that fixes
 * them. Unrecognised messages become one generic line; server text is never shown.
 */
export function submitProblems(errors: string[]): SubmitProblem[] {
  const out: SubmitProblem[] = [];
  const add = (p: SubmitProblem) => {
    if (!out.some((o) => o.text === p.text)) out.push(p);
  };
  for (const raw of errors) {
    const e = raw.trim();
    const field = /^Missing universal form field: (\w+)$/.exec(e);
    const doc = /^Missing document: (.+)$/.exec(e);
    const lower = e.toLowerCase();
    if (field) add(MISSING_FIELD[field[1]] ?? { text: 'Some of your details are missing.', page: 'about' });
    else if (doc) add({ text: `Upload your ${doc[1].charAt(0).toLowerCase()}${doc[1].slice(1)}.`, page: 'documents' });
    else if (lower.includes('guarantor')) add({ text: 'Add at least one guarantor.', page: 'guarantor' });
    else if (lower.includes('3 years')) add({ text: 'Business loans need a business that has run for at least 3 years.', page: 'business' });
    else if (lower.includes('trade type')) add({ text: 'Tell us what your business sells.', page: 'business' });
    else if (lower.includes('employer') || lower.includes('salary')) add({ text: 'Add your employer and the day you’re paid.', page: 'employment' });
    else if (lower.includes('student') || lower.includes('school')) add({ text: 'Add the student’s and school’s details.', page: 'student' });
    else if (lower.includes('asset')) add({ text: 'Describe the asset and add its price.', page: 'asset' });
    else add({ text: 'Some details are missing. Please check each step.', page: null });
  }
  return out;
}
