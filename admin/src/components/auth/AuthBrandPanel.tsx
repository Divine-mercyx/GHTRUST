export function AuthBrandPanel() {
  return (
    <div className="auth-brand-panel relative hidden lg:flex flex-col justify-between overflow-hidden bg-navy text-white p-12 xl:p-16">
      <div className="auth-brand-noise pointer-events-none" aria-hidden />
      <div className="auth-brand-shapes pointer-events-none" aria-hidden>
        <div className="auth-shape auth-shape-1" />
        <div className="auth-shape auth-shape-2" />
        <div className="auth-shape auth-shape-3" />
        <div className="auth-shape auth-shape-4" />
      </div>

      <div className="relative">
        <p className="text-[11px] font-semibold tracking-[0.2em] uppercase text-white/40">
          GH Trust MFB
        </p>
      </div>

      <div className="relative space-y-6 max-w-md">
        <h1 className="text-4xl xl:text-5xl font-extrabold leading-tight tracking-tight">
          Hello GH Trust!
        </h1>
        <p className="text-white/60 text-base leading-relaxed">
          Your staff portal for loan operations, application reviews, and branch
          administration. Secure, OTP-verified access for authorized personnel only.
        </p>
      </div>

      <p className="relative text-white/30 text-xs">
        © {new Date().getFullYear()} GH Trust International Ltd · Staff Portal
      </p>
    </div>
  )
}
