import { useCallback, useEffect, useState } from 'react'
import clsx from 'clsx'
import {
  ArrowLeft,
  CheckCircle2,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { ApiError, adminAuthApi } from '../lib/api'
import { useAuth } from '../lib/auth'
import { AuthBrandPanel } from '../components/auth/AuthBrandPanel'
import { OtpInput } from '../components/auth/OtpInput'
import { takeSignOutReason } from '../lib/signOutReason'

type Step = 'phone' | 'otp' | 'success'

function formatPhoneDisplay(raw: string): string {
  const digits = raw.replace(/\D/g, '')
  if (digits.startsWith('234')) return `+${digits}`
  if (digits.startsWith('0')) return digits
  return digits
}

function BrandLogo() {
  return (
    <div className="flex items-center gap-3">
      <div className="h-10 w-10 rounded-lg bg-navy flex items-center justify-center text-white font-bold text-sm">
        GH
      </div>
      <div>
        <p className="text-sm font-bold text-navy tracking-tight">GH Trust</p>
        <p className="text-xs text-slate-500">Microfinance Bank</p>
      </div>
    </div>
  )
}

export function LoginPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [step, setStep] = useState<Step>('phone')
  const [phone, setPhone] = useState('')
  const [otp, setOtp] = useState('')
  const [maskedPhone, setMaskedPhone] = useState('')
  const [expiresIn, setExpiresIn] = useState(600)
  const [resendIn, setResendIn] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [staffName, setStaffName] = useState('')
  // Shown once: why the last session ended.
  const [signedOutIdle] = useState(() => takeSignOutReason() === 'idle')

  useEffect(() => {
    if (resendIn <= 0) return
    const t = setTimeout(() => setResendIn((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [resendIn])

  const handleRequestOtp = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!phone.trim()) {
      setError('Enter your registered staff phone number')
      return
    }
    setError('')
    setLoading(true)
    try {
      const res = await adminAuthApi.requestOtp(phone.trim())
      setMaskedPhone(res.phone_masked)
      setExpiresIn(res.expires_in)
      setResendIn(60)
      setOtp('')
      setStep('otp')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send OTP. Try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleResend = async () => {
    if (resendIn > 0 || loading) return
    setError('')
    setLoading(true)
    try {
      const res = await adminAuthApi.resendOtp(phone.trim())
      setMaskedPhone(res.phone_masked)
      setExpiresIn(res.expires_in)
      setResendIn(60)
      setOtp('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Resend failed')
    } finally {
      setLoading(false)
    }
  }

  const verifyOtp = useCallback(async (code: string) => {
    if (code.length < 6 || loading) return
    setError('')
    setLoading(true)
    try {
      const res = await adminAuthApi.verifyOtp(phone.trim(), code)
      setStaffName(res.staff.full_name)
      login(res.access_token, res.refresh_token, res.staff)
      setStep('success')
      setTimeout(() => navigate('/dashboard', { replace: true }), 1200)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Invalid or expired code')
      setOtp('')
    } finally {
      setLoading(false)
    }
  }, [phone, loading, login, navigate])

  useEffect(() => {
    if (step === 'otp' && otp.length === 6) verifyOtp(otp)
  }, [otp, step, verifyOtp])

  const goBack = () => {
    setStep('phone')
    setOtp('')
    setError('')
  }

  return (
    <div className="min-h-screen grid lg:grid-cols-2 auth-enter">
      <AuthBrandPanel />

      <div className="flex flex-col justify-center bg-white px-8 sm:px-12 lg:px-16 xl:px-20 py-12 min-h-screen">
        <div className="w-full max-w-md mx-auto">
          <div className="mb-10 lg:mb-12">
            <BrandLogo />
          </div>

          {step === 'success' ? (
            <div className="text-center py-8 auth-fade-in">
              <div className="mx-auto h-16 w-16 rounded-full bg-emerald-50 flex items-center justify-center mb-5">
                <CheckCircle2 className="h-8 w-8 text-emerald-600" />
              </div>
              <h1 className="text-2xl font-bold text-slate-900">
                Welcome, {staffName.split(' ')[0]}!
              </h1>
              <p className="text-slate-500 text-sm mt-2">Redirecting to your dashboard…</p>
              <Loader2 className="h-5 w-5 animate-spin text-navy mx-auto mt-6" />
            </div>
          ) : (
            <div className="auth-fade-in">
              <div className="flex items-start justify-between mb-2">
                <h1 className="text-3xl sm:text-4xl font-bold text-slate-900 tracking-tight">
                  {step === 'phone' ? 'Welcome Back!' : 'Verify Code'}
                </h1>
                {step === 'otp' && (
                  <button
                    type="button"
                    onClick={goBack}
                    className="p-2 -mr-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-50 transition-colors"
                    title="Change number"
                  >
                    <ArrowLeft className="h-5 w-5" />
                  </button>
                )}
              </div>

              <p className="text-slate-500 text-sm mb-8">
                {step === 'phone'
                  ? 'Sign in with your registered staff phone number'
                  : `Enter the 6-digit code sent to ${maskedPhone}`}
              </p>

              {signedOutIdle && !error && step === 'phone' && (
                <div className="mb-6 px-4 py-3 rounded-lg bg-amber-50 text-amber-800 text-sm border border-amber-100" role="status">
                  You were signed out after a period of inactivity. Sign in again to continue.
                </div>
              )}

              {error && (
                <div className="mb-6 px-4 py-3 rounded-lg bg-rose-50 text-rose-700 text-sm border border-rose-100 auth-shake">
                  {error}
                </div>
              )}

              {step === 'phone' ? (
                <form onSubmit={handleRequestOtp} className="space-y-8">
                  <div>
                    <label htmlFor="phone" className="block text-sm font-medium text-slate-700 mb-3">
                      Phone number
                    </label>
                    <input
                      id="phone"
                      type="tel"
                      autoFocus
                      autoComplete="tel"
                      value={phone}
                      onChange={(e) => {
                        setPhone(formatPhoneDisplay(e.target.value))
                        setError('')
                      }}
                      placeholder="Enter your phone number"
                      className="auth-input w-full"
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={loading || !phone.trim()}
                    className="auth-btn w-full py-3.5 rounded-lg text-white font-semibold text-base transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {loading ? (
                      <Loader2 className="h-5 w-5 animate-spin mx-auto" />
                    ) : (
                      'Send verification code'
                    )}
                  </button>

                  <p className="text-center text-xs text-slate-400">
                    Inactive staff accounts cannot sign in
                  </p>
                </form>
              ) : (
                <div className="space-y-8">
                  <OtpInput
                    value={otp}
                    onChange={(v) => {
                      setOtp(v)
                      setError('')
                    }}
                    disabled={loading}
                    error={!!error}
                    variant="light"
                  />

                  <div className="text-center space-y-3">
                    {loading && (
                      <p className="text-sm text-slate-500 flex items-center justify-center gap-2">
                        <Loader2 className="h-4 w-4 animate-spin text-navy" />
                        Verifying…
                      </p>
                    )}

                    <button
                      type="button"
                      onClick={handleResend}
                      disabled={resendIn > 0 || loading}
                      className={clsx(
                        'inline-flex items-center gap-2 text-sm font-medium transition-colors',
                        resendIn > 0 || loading
                          ? 'text-slate-300 cursor-not-allowed'
                          : 'text-navy hover:text-navy-dark',
                      )}
                    >
                      <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
                      {resendIn > 0 ? `Resend code in ${resendIn}s` : 'Resend code'}
                    </button>

                    <p className="text-xs text-slate-400">
                      OTP valid for {Math.floor(expiresIn / 60)} minutes · Dev mode: check API console
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}

          <p className="mt-12 text-xs text-slate-400 text-center lg:text-left">
            Need help?{' '}
            <a href="mailto:admin@ghtrust.com" className="text-navy hover:underline">
              admin@ghtrust.com
            </a>
          </p>
        </div>
      </div>
    </div>
  )
}
