import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import { X } from 'lucide-react'
import { ApiError } from '../../lib/api'
import type { LoanProduct, LoanProductInput } from '../../lib/loansApi'

/**
 * New loan product. The options mirror the server's rules (backend CreateLoanProductRequest):
 * only steps the customer apps have screens for, known document types, and the repayment
 * schedules the servicing engine supports.
 */

// Same labels as backend/app/modules/loans/constants.py DOCUMENT_LABELS.
const DOCUMENTS: [string, string][] = [
  ['valid_id', 'Valid means of identification'],
  ['bvn', 'BVN verification'],
  ['passport_photo', 'Recent passport photograph'],
  ['passport_photo_2', 'Second passport photograph'],
  ['shop_rent_receipt', 'Shop rent receipt / proof of ownership'],
  ['cash_flow_proof', 'Verifiable cash flow proof'],
  ['salary_statement_6m', '6 months salary account statement'],
  ['staff_id', 'Staff ID card'],
  ['utility_bill', 'Utility bill (not older than 3 months)'],
  ['presigned_cheque', 'Pre-signed cheque on salary account'],
  ['collateral_affidavit', 'Affidavit for collateral'],
  ['collateral_original', 'Original collateral documents'],
  ['collateral_c_of_o', 'Collateral C of O (Lagos property)'],
  ['guarantor_id', 'Guarantor valid ID'],
  ['guarantor_photo', 'Guarantor passport photograph'],
  ['guarantor_photo_2', 'Guarantor second passport photograph'],
  ['admission_letter', 'Student admission letter'],
  ['relationship_proof', 'Proof of relationship with student'],
  ['offer_letter_signed', 'Signed offer letter'],
  ['court_affidavit', 'Court affidavit (asset as collateral)'],
  ['income_proof', 'Proof of verifiable income'],
]

// Optional application sections, in the order the app shows them. Product selection,
// the applicant form, documents and review are always included.
const OPTIONAL_STEPS: [string, string, string][] = [
  ['business_details', 'Business details', 'Trade, years in business, monthly sales'],
  ['employment_details', 'Employment details', 'Employer and salary pay day'],
  ['student_school_details', 'Student & school', 'Student, school and tuition'],
  ['guardian_details', 'Guardian details', 'Guardian applying for a student'],
  ['asset_details', 'Asset details', 'The item being financed and its price'],
  ['guarantor_collateral', 'Guarantor & collateral', 'At least one guarantor, optional collateral'],
]
const STEP_ORDER = [
  'product_selection',
  'universal_form',
  ...OPTIONAL_STEPS.map(([id]) => id),
  'documents',
  'review_submit',
]

const CADENCES: [string, string][] = [
  ['monthly', 'Monthly'],
  ['weekly', 'Weekly'],
  ['daily', 'Daily'],
  ['salary_date', 'On salary date'],
  ['end_of_term', 'Once, at the end'],
]

const DAYS_PER_MONTH = 30 // matches the servicing engine

function slugify(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 50)
  return /^[a-z]/.test(slug) ? slug : slug ? `loan_${slug}`.slice(0, 50) : ''
}

interface Props {
  open: boolean
  existingCodes: string[]
  onClose: () => void
  onCreate: (input: LoanProductInput) => Promise<LoanProduct>
}

export function CreateProductDialog({ open, existingCodes, onClose, onCreate }: Props) {
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [codeEdited, setCodeEdited] = useState(false)
  const [description, setDescription] = useState('')
  const [rate, setRate] = useState('')
  const [fee, setFee] = useState('3')
  const [method, setMethod] = useState<'flat' | 'reducing_balance' | 'one_off'>('flat')
  const [maxMonths, setMaxMonths] = useState('')
  const [penalty, setPenalty] = useState('')
  const [cadences, setCadences] = useState<string[]>(['monthly'])
  const [steps, setSteps] = useState<string[]>(['guarantor_collateral'])
  const [docs, setDocs] = useState<string[]>(['valid_id', 'bvn'])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (!open) return
    setName('')
    setCode('')
    setCodeEdited(false)
    setDescription('')
    setRate('')
    setFee('3')
    setMethod('flat')
    setMaxMonths('')
    setPenalty('')
    setCadences(['monthly'])
    setSteps(['guarantor_collateral'])
    setDocs(['valid_id', 'bvn'])
    setError('')
    setTouched(false)
  }, [open])

  const effectiveCode = codeEdited ? code : slugify(name)

  const problems = useMemo(() => {
    const p: Record<string, string> = {}
    if (name.trim().length < 3) p.name = 'Enter a name of at least 3 characters.'
    if (!/^[a-z][a-z0-9_]{2,49}$/.test(effectiveCode))
      p.code = 'Lower-case letters, numbers and underscores; starts with a letter; 3–50 characters.'
    else if (existingCodes.includes(effectiveCode)) p.code = 'A product already uses this code.'
    const r = Number(rate)
    if (!rate || !(r > 0) || r > 20) p.rate = 'Enter a monthly rate above 0 and up to 20%.'
    const f = Number(fee)
    if (fee === '' || !(f >= 0) || f > 20) p.fee = 'Enter a fee from 0 to 20%.'
    if (maxMonths) {
      const m = Number(maxMonths)
      if (!Number.isInteger(m) || m < 1 || m > 60) p.maxMonths = 'Whole months from 1 to 60.'
    }
    if (penalty) {
      const pen = Number(penalty)
      if (!(pen >= 0) || pen > 5) p.penalty = 'From 0 to 5% per day.'
    }
    if (!cadences.length) p.cadences = 'Choose at least one repayment schedule.'
    if (!docs.length) p.docs = 'Choose at least one document.'
    return p
  }, [name, effectiveCode, existingCodes, rate, fee, maxMonths, penalty, cadences, docs])

  if (!open) return null

  const toggle = (list: string[], value: string, set: (next: string[]) => void) =>
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (Object.keys(problems).length) return
    setSaving(true)
    setError('')
    try {
      const chosen = new Set(['product_selection', 'universal_form', ...steps, 'documents', 'review_submit'])
      await onCreate({
        code: effectiveCode,
        name: name.trim(),
        description: description.trim() || null,
        interest_rate_pct_monthly: Number(rate).toFixed(2),
        processing_fee_pct: Number(fee).toFixed(2),
        interest_method: method,
        max_tenure_days: maxMonths ? Number(maxMonths) * DAYS_PER_MONTH : null,
        default_penalty_pct_daily: penalty ? Number(penalty).toFixed(2) : null,
        repayment_cadence_options: cadences,
        required_document_types: DOCUMENTS.map(([id]) => id).filter((id) => docs.includes(id)),
        workflow_steps: STEP_ORDER.filter((s) => chosen.has(s)),
      })
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the product.')
    } finally {
      setSaving(false)
    }
  }

  const show = (key: string) => (touched ? problems[key] : undefined)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button type="button" aria-label="Close" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <form
        onSubmit={submit}
        className="relative w-full max-w-2xl max-h-[calc(100vh-2rem)] flex flex-col bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200 overflow-hidden"
        aria-label="New loan product"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 shrink-0">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">New loan product</h3>
            <p className="text-[12px] text-slate-400 mt-0.5">
              Created switched off. Customers see it once its approval pipeline is published and it's switched on.
            </p>
          </div>
          <button type="button" onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:bg-slate-100" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="overflow-y-auto px-6 py-5 space-y-6">
          <Section title="Basics">
            <div className="grid sm:grid-cols-2 gap-3">
              <Field label="Product name" error={show('name')}>
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={150} placeholder="e.g. Agric Loan" className={input} autoFocus />
              </Field>
              <Field label="Product code" hint="Permanent ID used by the apps. Can't be changed later." error={show('code')}>
                <input
                  value={effectiveCode}
                  onChange={(e) => {
                    setCodeEdited(true)
                    setCode(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_'))
                  }}
                  maxLength={50}
                  placeholder="agric_loan"
                  className={clsx(input, 'font-mono')}
                />
              </Field>
            </div>
            <Field label="Description" hint="Shown to customers when they choose a loan.">
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} rows={2} className={clsx(input, 'resize-none')} />
            </Field>
          </Section>

          <Section title="Pricing & terms">
            <div className="grid sm:grid-cols-3 gap-3">
              <Field label="Interest (% per month)" error={show('rate')}>
                <input value={rate} onChange={(e) => setRate(e.target.value)} inputMode="decimal" placeholder="8" className={input} />
              </Field>
              <Field label="Processing fee (%)" error={show('fee')}>
                <input value={fee} onChange={(e) => setFee(e.target.value)} inputMode="decimal" className={input} />
              </Field>
              <Field label="Interest method">
                <select value={method} onChange={(e) => setMethod(e.target.value as typeof method)} className={input}>
                  <option value="flat">Flat</option>
                  <option value="reducing_balance">Reducing balance</option>
                  <option value="one_off">One-off charge (rate charged once, e.g. LPO)</option>
                </select>
              </Field>
              <Field label="Longest tenure (months)" hint="Blank = no limit (app allows up to 24)." error={show('maxMonths')}>
                <input value={maxMonths} onChange={(e) => setMaxMonths(e.target.value)} inputMode="numeric" placeholder="12" className={input} />
              </Field>
              <Field label="Late penalty (% per day)" hint="Optional." error={show('penalty')}>
                <input value={penalty} onChange={(e) => setPenalty(e.target.value)} inputMode="decimal" placeholder="0.5" className={input} />
              </Field>
            </div>
            <Field label="Repayment schedules offered" error={show('cadences')}>
              <div className="flex flex-wrap gap-1.5">
                {CADENCES.map(([id, label]) => (
                  <Chip key={id} on={cadences.includes(id)} onClick={() => toggle(cadences, id, setCadences)}>
                    {label}
                  </Chip>
                ))}
              </div>
            </Field>
          </Section>

          <Section title="Application form" hint="Every product asks for the applicant's details, documents and a final review. Add the sections this product also needs.">
            <div className="grid sm:grid-cols-2 gap-2">
              {OPTIONAL_STEPS.map(([id, label, hint]) => (
                <Check key={id} checked={steps.includes(id)} onChange={() => toggle(steps, id, setSteps)} label={label} hint={hint} />
              ))}
            </div>
          </Section>

          <Section title="Required documents" error={show('docs')}>
            <div className="grid sm:grid-cols-2 gap-x-4 gap-y-1">
              {DOCUMENTS.map(([id, label]) => (
                <Check key={id} checked={docs.includes(id)} onChange={() => toggle(docs, id, setDocs)} label={label} />
              ))}
            </div>
          </Section>
        </div>

        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-slate-100 bg-slate-50/60 shrink-0">
          <p className="text-[12px] text-rose-600 font-medium min-h-[1em]">
            {error || (touched && Object.keys(problems).length ? 'Fix the highlighted fields.' : '')}
          </p>
          <div className="flex gap-2 shrink-0">
            <button type="button" onClick={onClose} className="px-4 py-2.5 rounded-lg text-[13px] font-semibold text-slate-600 hover:bg-slate-100">
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-5 py-2.5 rounded-lg bg-[#1b2f6b] text-white text-[13px] font-semibold hover:bg-[#141f45] disabled:opacity-50"
            >
              {saving ? 'Creating…' : 'Create product'}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}

const input =
  'w-full text-[13px] ring-1 ring-slate-200 rounded-lg px-3 py-2.5 bg-white focus:ring-[#1b2f6b]/40 outline-none'

function Section({ title, hint, error, children }: { title: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h4 className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">{title}</h4>
        {hint && <p className="text-[12px] text-slate-500 mt-1">{hint}</p>}
        {error && <p className="text-[12px] text-rose-600 mt-1">{error}</p>}
      </div>
      {children}
    </section>
  )
}

function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[12px] font-medium text-slate-700 mb-1.5">{label}</span>
      {children}
      {error ? (
        <span className="block text-[11px] text-rose-600 mt-1">{error}</span>
      ) : hint ? (
        <span className="block text-[11px] text-slate-400 mt-1">{hint}</span>
      ) : null}
    </label>
  )
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={clsx(
        'px-3 py-1.5 rounded-lg text-[12px] font-medium ring-1 transition-colors',
        on ? 'bg-[#1b2f6b] text-white ring-[#1b2f6b]' : 'bg-white text-slate-600 ring-slate-200 hover:bg-slate-50',
      )}
    >
      {children}
    </button>
  )
}

function Check({ checked, onChange, label, hint }: { checked: boolean; onChange: () => void; label: string; hint?: string }) {
  return (
    <label className="flex items-start gap-2.5 py-1.5 cursor-pointer">
      <input type="checkbox" checked={checked} onChange={onChange} className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-[#1b2f6b]" />
      <span>
        <span className="block text-[13px] text-slate-700">{label}</span>
        {hint && <span className="block text-[11px] text-slate-400">{hint}</span>}
      </span>
    </label>
  )
}
