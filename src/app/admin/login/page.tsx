"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, CheckCircle2, Lock, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/admin/Page";
import { InlineError, Notice } from "@/components/admin/States";
import { useStaffAuth } from "@/lib/admin/auth";
import { authApi } from "@/lib/admin/endpoints";
import { errorMessage } from "@/lib/admin/hooks";

const RESEND_AFTER = 30;

const SIGN_OUT_MESSAGES = {
  background: "The portal was in the background for more than 5 minutes. Sign in again to continue.",
  idle: "There was no activity for a while, so we ended your session to protect customer data.",
  expired: "Your session ended. Sign in again to continue.",
  manual: "",
} as const;

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/admin";
  const { signedIn, signIn, lastSignOut } = useStaffAuth();

  const [step, setStep] = useState<"phone" | "otp">("phone");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [maskedPhone, setMaskedPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const submitted = useRef<string | null>(null);

  useEffect(() => {
    if (signedIn) router.replace(next.startsWith("/admin") ? next : "/admin");
  }, [signedIn, next, router]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  async function requestCode(e?: React.FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = step === "otp" ? await authApi.resendOtp(phone.trim()) : await authApi.requestOtp(phone.trim());
      setMaskedPhone(res.phone_masked);
      setStep("otp");
      setOtp("");
      submitted.current = null;
      setCooldown(RESEND_AFTER);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function verify(code: string) {
    if (submitted.current === code) return; // don't resubmit the same code twice
    submitted.current = code;
    setBusy(true);
    setError(null);
    try {
      const res = await authApi.verifyOtp(phone.trim(), code);
      signIn(res.access_token, res.staff);
    } catch (err) {
      setError(errorMessage(err));
      setOtp("");
      submitted.current = null;
    } finally {
      setBusy(false);
    }
  }

  // Sign in as soon as all six digits are entered.
  useEffect(() => {
    if (step === "otp" && otp.length === 6 && !busy) verify(otp);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [otp, step]);

  return (
    <div className="grid min-h-dvh bg-canvas lg:grid-cols-[minmax(420px,5fr)_7fr]">
      <aside className="relative hidden overflow-hidden gradient-navy p-12 text-white lg:flex lg:flex-col lg:justify-between">
        {/* Ambient light: two soft orbs drifting behind the grid. */}
        <div className="pointer-events-none absolute -left-24 -top-24 h-96 w-96 animate-drift rounded-full bg-cyan-bright/25 blur-3xl" aria-hidden />
        <div
          className="pointer-events-none absolute -bottom-32 right-[-10%] h-[28rem] w-[28rem] animate-drift rounded-full bg-[#3B5BDB]/30 blur-3xl [animation-delay:-9s]"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage: "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
          aria-hidden
        />
        <div className="relative flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-sm font-bold text-navy">GH</span>
          <span className="leading-tight">
            <span className="block font-semibold">GH Trust International</span>
            <span className="block text-xs text-white/60">Secure Today. Grow Tomorrow.</span>
          </span>
        </div>
        <div className="stagger relative max-w-md">
          <p className="text-2xs font-semibold uppercase tracking-[0.2em] text-cyan-bright">Staff portal</p>
          <h1 className="mt-3 text-[32px] font-semibold leading-tight tracking-tight">Lending operations, in one place.</h1>
          <ul className="mt-8 space-y-3 text-sm text-white/80">
            {["Review applications through your approval stage", "Verify documents and disburse with a full audit trail", "Service the loan book and record repayments"].map((t) => (
              <li key={t} className="flex items-start gap-2.5">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-cyan-bright" /> {t}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative flex items-center gap-2 text-xs text-white/50">
          <Lock className="h-3.5 w-3.5" /> Access is limited to activated GH Trust staff. Every action is logged.
        </p>
      </aside>

      <main className="flex items-center justify-center px-4 py-10 sm:px-6">
        <div className="w-full max-w-[400px]">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-navy text-sm font-bold text-white">GH</span>
            <span className="font-semibold text-ink">GH Trust staff portal</span>
          </div>

          <div className="animate-rise-in rounded-2xl border border-line bg-white p-7 shadow-pop sm:p-8">
            <div className="mb-6">
              <span className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-soft">
                <ShieldCheck className="h-5 w-5 text-cyan" />
              </span>
              <h2 className="text-xl font-semibold text-ink">{step === "phone" ? "Sign in" : "Enter your code"}</h2>
              <p className="mt-1 text-sm text-ink-3">
                {step === "phone" ? "We'll text a one-time code to your registered phone." : <>We sent a 6-digit code to <strong className="font-semibold text-ink-2">{maskedPhone}</strong>.</>}
              </p>
            </div>

            {lastSignOut && lastSignOut !== "manual" && step === "phone" && (
              <Notice tone="warning" className="mb-4" title="You were signed out">
                {SIGN_OUT_MESSAGES[lastSignOut]}
              </Notice>
            )}
            {step === "phone" ? (
              <form key="phone" onSubmit={requestCode} className="animate-fade-up space-y-4" noValidate>
                <Field label="Phone number">
                  {(id) => (
                    <input
                      id={id}
                      className="input h-11 text-[15px]"
                      type="tel"
                      inputMode="tel"
                      autoComplete="tel"
                      placeholder="0803 000 0000"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      autoFocus
                      required
                      minLength={10}
                    />
                  )}
                </Field>
                <InlineError message={error} />
                <Button type="submit" size="lg" className="w-full" loading={busy} disabled={phone.trim().length < 10}>
                  Send code
                </Button>
              </form>
            ) : (
              <form
                key="otp"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (otp.length === 6) verify(otp);
                }}
                className="animate-fade-up space-y-4"
              >
                <Field label="6-digit code">
                  {(id) => (
                    <input
                      id={id}
                      className="input num h-12 text-center font-mono text-xl tracking-[0.5em]"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={6}
                      value={otp}
                      onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                      autoFocus
                      required
                      aria-invalid={!!error || undefined}
                    />
                  )}
                </Field>
                <InlineError message={error} />
                <Button type="submit" size="lg" className="w-full" loading={busy} disabled={otp.length !== 6}>
                  Verify & sign in
                </Button>
                <div className="flex items-center justify-between pt-1 text-[13px]">
                  <button
                    type="button"
                    className="flex items-center gap-1 rounded font-medium text-ink-3 hover:text-ink"
                    onClick={() => {
                      setStep("phone");
                      setError(null);
                    }}
                  >
                    <ArrowLeft className="h-3.5 w-3.5" /> Change number
                  </button>
                  <button type="button" className="rounded font-semibold text-cyan hover:text-navy disabled:text-ink-3" disabled={busy || cooldown > 0} onClick={() => requestCode()}>
                    {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

export default function StaffLoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
