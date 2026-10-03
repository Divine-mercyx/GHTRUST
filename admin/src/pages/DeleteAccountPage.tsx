import { useState } from 'react'
import { AlertTriangle, CheckCircle2, Loader2, Trash2 } from 'lucide-react'
import { API_BASE } from '../lib/api'

/**
 * Public page for customers to delete their GH Trust account without the app (Google
 * Play's account-deletion URL). It proves ownership the same way the app does: an SMS
 * code to the account's phone, plus the sign-in PIN, plus typing DELETE. Nothing here
 * uses the staff session.
 */

type Step = 'phone' | 'confirm' | 'done'

interface Problem {
  message: string
  reasons: string[]
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/v1${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw { message: "We couldn't reach GH Trust. Check your connection and try again.", reasons: [] } as Problem
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const reasons: string[] = Array.isArray(data.errors)
      ? data.errors.map((e: { message?: string } | string) => (typeof e === 'string' ? e : e.message ?? '')).filter(Boolean)
      : []
    const message =
      res.status === 429
        ? 'Too many attempts. Please wait a few minutes and try again.'
        : typeof data.detail === 'string'
          ? data.detail
          : 'Something went wrong. Please try again.'
    throw { message, reasons: reasons.length > 1 ? reasons : [] } as Problem
  }
  return data as T
}

const DELETED = [
  'Your sign-in on every phone, saved phones and notifications',
  'Your PINs, profile photo and BVN photo',
  'Your contact details, address and payout bank account',
  'Unfinished loan applications and their documents',
  'The text of your support messages',
]
const KEPT = [
  'Loans, repayments, wallet and payment records, signed loan agreements and applications you submitted: financial records the law requires us to keep for at least 5 years after you leave',
  'With those records, only your BVN, name, date of birth and account number. If you never had a loan or payment with us, these are deleted too',
]

export function DeleteAccountPage() {
  const [step, setStep] = useState<Step>('phone')
  const [phone, setPhone] = useState('')
  const [otp, setOtp] = useState('')
  const [pin, setPin] = useState('')
  const [word, setWord] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<Problem | null>(null)

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setProblem(null)
    try {
      await fn()
    } catch (e) {
      setProblem(e as Problem)
    } finally {
      setBusy(false)
    }
  }

  const sendCode = () =>
    run(async () => {
      await post('/auth/account-deletion/request-otp', { phone })
      setStep('confirm')
    })

  const confirmDelete = () =>
    run(async () => {
      await post('/auth/account-deletion/confirm', { phone, otp, pin, confirmation: word })
      setStep('done')
    })

  const phoneOk = phone.replace(/\D/g, '').length >= 10
  const confirmOk = /^\d{4,8}$/.test(otp) && /^\d{6}$/.test(pin) && word.trim().toUpperCase() === 'DELETE'

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-10">
      <div className="mx-auto max-w-xl space-y-6">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-navy flex items-center justify-center text-white font-bold text-sm">GH</div>
          <div>
            <p className="text-sm font-bold text-navy tracking-tight">GH Trust</p>
            <p className="text-xs text-slate-500">Delete your account</p>
          </div>
        </div>

        <div className="dash-card p-6 space-y-4">
          <h1 className="text-xl font-bold text-slate-900">Delete your GH Trust account</h1>
          <p className="text-[14px] text-slate-600">
            The quickest way is in the app: <strong>Profile → Delete account</strong>. If you no longer have the app, you
            can do it here. Deleting your account is permanent and can't be undone.
          </p>
          <p className="text-[14px] text-slate-600">
            You can't delete your account while you have a loan or repayment outstanding, an application being processed,
            money in your wallet, or a withdrawal on its way.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <p className="text-[12px] font-semibold uppercase tracking-wide text-rose-700">What we delete</p>
              <ul className="mt-2 space-y-1.5 text-[13px] text-slate-700 list-disc pl-4">
                {DELETED.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-[12px] font-semibold uppercase tracking-wide text-slate-500">What we have to keep</p>
              <ul className="mt-2 space-y-1.5 text-[13px] text-slate-700 list-disc pl-4">
                {KEPT.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <div className="dash-card p-6 space-y-4">
          {step === 'done' ? (
            <div className="text-center space-y-3 py-4">
              <CheckCircle2 className="h-12 w-12 text-emerald-600 mx-auto" />
              <h2 className="text-lg font-bold text-slate-900">Your account has been deleted</h2>
              <p className="text-[14px] text-slate-600">
                You've been signed out on every phone. Thank you for banking with GH Trust.
              </p>
            </div>
          ) : step === 'phone' ? (
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault()
                if (phoneOk && !busy) void sendCode()
              }}
            >
              <label className="block">
                <span className="text-[13px] font-semibold text-slate-700">Your account's phone number</span>
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="0803 000 0000"
                  className="mt-1 w-full rounded-xl ring-1 ring-slate-200 px-3 py-2.5 text-[14px] outline-none focus:ring-navy/30"
                />
              </label>
              <p className="text-[12px] text-slate-500">We'll text a code to this number to check it's you.</p>
              <button
                type="submit"
                disabled={!phoneOk || busy}
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-navy text-white text-[14px] font-semibold disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Send code
              </button>
            </form>
          ) : (
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault()
                if (!confirmOk || busy) return
                if (window.confirm('Delete your GH Trust account? This cannot be undone.')) void confirmDelete()
              }}
            >
              <p className="text-[13px] text-slate-600">
                If an account uses <strong>{phone}</strong>, we've texted it a code.{' '}
                <button type="button" className="text-navy font-semibold underline" onClick={() => setStep('phone')}>
                  Change number
                </button>
              </p>
              <Input label="Code from the SMS" value={otp} onChange={(v) => setOtp(v.replace(/\D/g, '').slice(0, 8))} numeric />
              <Input label="Your 6-digit sign-in PIN" value={pin} onChange={(v) => setPin(v.replace(/\D/g, '').slice(0, 6))} numeric secret />
              <Input label="Type DELETE to confirm" value={word} onChange={setWord} />
              <button
                type="submit"
                disabled={!confirmOk || busy}
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-rose-600 text-white text-[14px] font-semibold disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />} Delete my account
              </button>
            </form>
          )}

          {problem ? (
            <div className="flex gap-3 rounded-xl bg-amber-50 p-4 ring-1 ring-amber-200 text-[13px] text-amber-900" role="alert">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <div className="space-y-1">
                {problem.reasons.length ? (
                  <ul className="list-disc pl-4 space-y-1">
                    {problem.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                ) : (
                  <p>{problem.message}</p>
                )}
              </div>
            </div>
          ) : null}
        </div>

        <p className="text-center text-[12px] text-slate-400">
          Need help? Use Help &amp; support in the app, or contact GH Trust.
        </p>
      </div>
    </div>
  )
}

function Input({
  label,
  value,
  onChange,
  numeric,
  secret,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  numeric?: boolean
  secret?: boolean
}) {
  return (
    <label className="block">
      <span className="text-[13px] font-semibold text-slate-700">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        type={secret ? 'password' : 'text'}
        inputMode={numeric ? 'numeric' : undefined}
        autoComplete="off"
        className="mt-1 w-full rounded-xl ring-1 ring-slate-200 px-3 py-2.5 text-[14px] outline-none focus:ring-navy/30"
      />
    </label>
  )
}
