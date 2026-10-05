import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { CalendarClock, ImagePlus, Pencil, Plus, TrendingUp, Trash2, Wallet, X } from 'lucide-react'
import { AdminLayout } from '../components/AdminLayout'
import { PermissionGate } from '../components/PermissionGate'
import { StatCard } from '../components/ui'
import { API_BASE, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { hasPermission } from '../lib/permissions'
import {
  investmentsApi,
  type Holding,
  type HoldingsPage,
  type InvestmentPlan,
  type PlanInput,
  type Risk,
} from '../lib/investmentsApi'

/**
 * Investment plans customers can buy with wallet money, and who holds what.
 * Rules (backend app/modules/investments/service.py): simple interest at the plan's yearly
 * rate, fixed when the customer invests; no early withdrawal; paid into the wallet at maturity.
 */

const naira = (v: string | number | null | undefined) =>
  `₦${Number(v ?? 0).toLocaleString('en-NG', { maximumFractionDigits: 2 })}`

const RISK: Record<Risk, { label: string; className: string }> = {
  low: { label: 'Low risk', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  medium: { label: 'Medium risk', className: 'bg-amber-50 text-amber-700 ring-amber-200' },
  high: { label: 'High risk', className: 'bg-rose-50 text-rose-700 ring-rose-200' },
}

export function InvestmentsPage() {
  return (
    <PermissionGate permission="investment:read">
      <InvestmentsPageContent />
    </PermissionGate>
  )
}

function InvestmentsPageContent() {
  const { token, staff } = useAuth()
  const canManage = hasPermission(staff, 'investment:manage')
  const [plans, setPlans] = useState<InvestmentPlan[]>([])
  const [holdings, setHoldings] = useState<HoldingsPage | null>(null)
  const [holdingFilter, setHoldingFilter] = useState<'active' | 'paid_out' | ''>('active')
  const [editing, setEditing] = useState<InvestmentPlan | 'new' | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!token) return
    setError('')
    try {
      const [p, h] = await Promise.all([
        investmentsApi.plans(token),
        investmentsApi.holdings(token, holdingFilter || undefined),
      ])
      setPlans(p)
      setHoldings(h)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load investments')
    } finally {
      setLoading(false)
    }
  }, [token, holdingFilter])

  useEffect(() => {
    load()
  }, [load])

  const replace = (p: InvestmentPlan) => setPlans((cur) => cur.map((x) => (x.id === p.id ? p : x)))

  return (
    <AdminLayout title="Investments" subtitle="Plans customers can put wallet money into, and who holds what">
      {error && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-rose-50 text-rose-700 text-[13px] ring-1 ring-rose-200">{error}</div>
      )}

      <div className="grid sm:grid-cols-3 gap-4 mb-6">
        <StatCard
          title="Invested now"
          value={naira(holdings?.active_amount)}
          icon={<Wallet className="h-5 w-5" />}
          iconBg="bg-[#1b2f6b]/5 text-[#1b2f6b]"
        />
        <StatCard
          title="Paying out in 30 days"
          value={naira(holdings?.due_in_30_days)}
          icon={<CalendarClock className="h-5 w-5" />}
          iconBg="bg-amber-50 text-amber-600"
        />
        <StatCard
          title="Plans on sale"
          value={String(plans.filter((p) => p.is_active).length)}
          icon={<TrendingUp className="h-5 w-5" />}
          iconBg="bg-emerald-50 text-emerald-600"
        />
      </div>

      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[15px] font-semibold text-slate-900">Plans</h2>
        {canManage ? (
          <button
            onClick={() => setEditing('new')}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[#1b2f6b] text-white text-[13px] font-semibold"
          >
            <Plus className="h-4 w-4" /> New plan
          </button>
        ) : null}
      </div>

      {loading ? (
        <div className="dash-card p-16 text-center">
          <div className="inline-block h-9 w-9 rounded-full border-2 border-slate-200 border-t-[#1b2f6b] animate-spin" />
        </div>
      ) : plans.length === 0 ? (
        <div className="dash-card px-6 py-16 text-center">
          <TrendingUp className="h-10 w-10 text-slate-300 mx-auto mb-3" />
          <p className="text-sm font-semibold text-slate-700">No plans yet</p>
          <p className="text-[12px] text-slate-400 mt-1">Create one and customers see it on the Invest tab in the app.</p>
        </div>
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4 mb-8">
          {plans.map((p) => (
            <PlanCard key={p.id} plan={p} canManage={canManage} token={token} onEdit={() => setEditing(p)} onChanged={replace} />
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h2 className="text-[15px] font-semibold text-slate-900">Customer investments</h2>
        <div className="flex gap-2">
          {(
            [
              ['active', 'Active'],
              ['paid_out', 'Paid out'],
              ['', 'All'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={label}
              onClick={() => setHoldingFilter(value)}
              className={clsx(
                'px-3 py-1.5 rounded-full text-[12px] font-semibold ring-1',
                holdingFilter === value ? 'bg-[#1b2f6b] text-white ring-[#1b2f6b]' : 'bg-white text-slate-600 ring-slate-200',
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <HoldingsTable items={holdings?.items ?? []} total={holdings?.total ?? 0} />

      {editing && token ? (
        <PlanDialog
          plan={editing === 'new' ? null : editing}
          token={token}
          onClose={() => setEditing(null)}
          onSaved={(p) => {
            setEditing(null)
            setPlans((cur) => (cur.some((x) => x.id === p.id) ? cur.map((x) => (x.id === p.id ? p : x)) : [...cur, p]))
          }}
        />
      ) : null}
    </AdminLayout>
  )
}

function PlanCard({
  plan,
  canManage,
  token,
  onEdit,
  onChanged,
}: {
  plan: InvestmentPlan
  canManage: boolean
  token: string | null
  onEdit: () => void
  onChanged: (p: InvestmentPlan) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const file = useRef<HTMLInputElement>(null)

  const run = async (fn: () => Promise<InvestmentPlan>) => {
    setBusy(true)
    setError('')
    try {
      onChanged(await fn())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  const pickImage = (f: File | undefined) => {
    if (!f || !token) return
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(f.type)) return setError('Use a JPG, PNG or WebP picture.')
    if (f.size > 2 * 1024 * 1024) return setError('The picture must be under 2 MB.')
    const reader = new FileReader()
    reader.onload = () => run(() => investmentsApi.setImage(token, plan.id, String(reader.result)))
    reader.readAsDataURL(f)
  }

  return (
    <div className={clsx('dash-card overflow-hidden flex flex-col', !plan.is_active && 'opacity-70')}>
      <div className="relative h-36 bg-gradient-to-br from-[#1b2f6b] to-[#2c4a9a]">
        {plan.image_url ? (
          <img src={`${API_BASE}${plan.image_url}`} alt="" className="absolute inset-0 h-full w-full object-cover" />
        ) : (
          <TrendingUp className="absolute right-4 bottom-4 h-12 w-12 text-white/20" />
        )}
        <span className="absolute left-3 top-3 px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-400 text-emerald-950">
          {Number(plan.return_rate)}% a year
        </span>
        {!plan.is_active ? (
          <span className="absolute right-3 top-3 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-white/90 text-slate-600">
            Off sale
          </span>
        ) : null}
      </div>
      <div className="p-5 flex-1 flex flex-col gap-3">
        <div>
          <p className="text-[15px] font-semibold text-slate-900">{plan.name}</p>
          {plan.description ? <p className="text-[12px] text-slate-500 mt-1 line-clamp-2">{plan.description}</p> : null}
        </div>
        <dl className="grid grid-cols-2 gap-y-2 text-[12px]">
          <dt className="text-slate-400">Term</dt>
          <dd className="text-slate-800 font-medium text-right">{plan.tenure_months} months</dd>
          <dt className="text-slate-400">Amount</dt>
          <dd className="text-slate-800 font-medium text-right">
            {naira(plan.min_amount)}
            {plan.max_amount ? ` – ${naira(plan.max_amount)}` : '+'}
          </dd>
          <dt className="text-slate-400">Investors</dt>
          <dd className="text-slate-800 font-medium text-right">
            {plan.active_investors} · {naira(plan.active_amount)}
          </dd>
        </dl>
        <span className={clsx('self-start px-2 py-0.5 rounded-full text-[11px] font-semibold ring-1', RISK[plan.risk]?.className)}>
          {RISK[plan.risk]?.label ?? plan.risk}
        </span>
        {error ? <p className="text-[12px] text-rose-600">{error}</p> : null}
        {canManage && token ? (
          <div className="mt-auto pt-2 flex flex-wrap gap-2">
            <button
              onClick={onEdit}
              disabled={busy}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg ring-1 ring-slate-200 text-[12px] font-semibold text-slate-700"
            >
              <Pencil className="h-3.5 w-3.5" /> Edit
            </button>
            <button
              onClick={() => file.current?.click()}
              disabled={busy}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg ring-1 ring-slate-200 text-[12px] font-semibold text-slate-700"
            >
              <ImagePlus className="h-3.5 w-3.5" /> {plan.image_url ? 'Change picture' : 'Add picture'}
            </button>
            {plan.image_url ? (
              <button
                onClick={() => run(() => investmentsApi.removeImage(token, plan.id))}
                disabled={busy}
                aria-label="Remove picture"
                className="inline-flex items-center px-2 py-1.5 rounded-lg ring-1 ring-slate-200 text-slate-500"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            ) : null}
            <button
              onClick={() => run(() => investmentsApi.update(token, plan.id, { is_active: !plan.is_active }))}
              disabled={busy}
              className={clsx(
                'ml-auto px-3 py-1.5 rounded-lg text-[12px] font-semibold ring-1',
                plan.is_active ? 'ring-slate-200 text-slate-600' : 'ring-emerald-200 bg-emerald-50 text-emerald-700',
              )}
            >
              {plan.is_active ? 'Take off sale' : 'Put on sale'}
            </button>
            <input
              ref={file}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={(e) => {
                pickImage(e.target.files?.[0])
                e.target.value = ''
              }}
            />
          </div>
        ) : null}
      </div>
    </div>
  )
}

function HoldingsTable({ items, total }: { items: Holding[]; total: number }) {
  if (items.length === 0) {
    return (
      <div className="dash-card px-6 py-12 text-center text-[13px] text-slate-400">No customer investments here yet.</div>
    )
  }
  return (
    <div className="dash-card overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-slate-400 border-b border-slate-100">
            <th className="px-5 py-3 font-semibold">Customer</th>
            <th className="px-5 py-3 font-semibold">Plan</th>
            <th className="px-5 py-3 font-semibold text-right">Amount</th>
            <th className="px-5 py-3 font-semibold text-right">Returns</th>
            <th className="px-5 py-3 font-semibold">Matures</th>
            <th className="px-5 py-3 font-semibold">Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((h) => (
            <tr key={h.id} className="border-b border-slate-50 last:border-0">
              <td className="px-5 py-3">
                <Link to={`/customers/${h.customer_id}`} className="font-medium text-slate-900 hover:text-[#1b2f6b]">
                  {h.customer_name}
                </Link>
                <p className="text-[11px] text-slate-400 font-mono">{h.reference}</p>
              </td>
              <td className="px-5 py-3 text-slate-600">
                {h.plan_name} <span className="text-slate-400">· {Number(h.return_rate)}%</span>
              </td>
              <td className="px-5 py-3 text-right tabular-nums">{naira(h.amount)}</td>
              <td className="px-5 py-3 text-right tabular-nums text-emerald-600">+{naira(h.projected_return)}</td>
              <td className="px-5 py-3 text-slate-600">{new Date(h.maturity_date).toLocaleDateString()}</td>
              <td className="px-5 py-3">
                <span
                  className={clsx(
                    'px-2 py-0.5 rounded-full text-[11px] font-semibold ring-1',
                    h.status === 'active'
                      ? 'bg-sky-50 text-sky-700 ring-sky-200'
                      : 'bg-emerald-50 text-emerald-700 ring-emerald-200',
                  )}
                >
                  {h.status === 'active' ? 'Active' : 'Paid out'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {total > items.length ? (
        <p className="px-5 py-3 text-[12px] text-slate-400">Showing the latest {items.length} of {total}.</p>
      ) : null}
    </div>
  )
}

const input =
  'w-full text-[13px] ring-1 ring-slate-200 rounded-lg px-3 py-2.5 bg-white focus:ring-[#1b2f6b]/40 outline-none'

function PlanDialog({
  plan,
  token,
  onClose,
  onSaved,
}: {
  plan: InvestmentPlan | null
  token: string
  onClose: () => void
  onSaved: (p: InvestmentPlan) => void
}) {
  const [form, setForm] = useState<PlanInput>({
    name: plan?.name ?? '',
    description: plan?.description ?? '',
    min_amount: plan ? String(Number(plan.min_amount)) : '',
    max_amount: plan?.max_amount ? String(Number(plan.max_amount)) : '',
    return_rate: plan ? String(Number(plan.return_rate)) : '',
    tenure_months: plan?.tenure_months ?? 12,
    risk: plan?.risk ?? 'low',
    is_active: plan?.is_active ?? true,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = <K extends keyof PlanInput>(k: K, v: PlanInput[K]) => setForm((f) => ({ ...f, [k]: v }))

  const sample = Number(form.min_amount || 0)
  const returns = (sample * Number(form.return_rate || 0) * Number(form.tenure_months || 0)) / 1200

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (form.name.trim().length < 3) return setError('Give the plan a name (3 characters or more).')
    if (!(Number(form.min_amount) > 0)) return setError('Set a minimum amount.')
    if (form.max_amount && Number(form.max_amount) < Number(form.min_amount))
      return setError('The maximum must be at least the minimum.')
    if (!(Number(form.return_rate) > 0 && Number(form.return_rate) <= 100)) return setError('Set a yearly rate between 0 and 100%.')
    if (!(form.tenure_months >= 1 && form.tenure_months <= 60)) return setError('The term must be 1 to 60 months.')
    setBusy(true)
    setError('')
    const body: PlanInput = {
      ...form,
      name: form.name.trim(),
      description: form.description?.trim() || null,
      max_amount: form.max_amount ? form.max_amount : null,
    }
    try {
      onSaved(plan ? await investmentsApi.update(token, plan.id, body) : await investmentsApi.create(token, body))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save the plan')
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button type="button" aria-label="Close" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <form
        onSubmit={submit}
        className="relative w-full max-w-lg max-h-[calc(100vh-2rem)] flex flex-col bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200 overflow-hidden"
        aria-label={plan ? 'Edit plan' : 'New plan'}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">{plan ? 'Edit plan' : 'New investment plan'}</h3>
            <p className="text-[12px] text-slate-400 mt-0.5">
              Changes apply to new investments. Customers who already invested keep their rate.
            </p>
          </div>
          <button type="button" onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:bg-slate-100" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="overflow-y-auto px-6 py-5 space-y-4">
          <Field label="Name">
            <input value={form.name} onChange={(e) => set('name', e.target.value)} maxLength={100} className={input} autoFocus />
          </Field>
          <Field label="Description" hint="Shown to customers on the plan's page.">
            <textarea
              value={form.description ?? ''}
              onChange={(e) => set('description', e.target.value)}
              rows={3}
              maxLength={2000}
              className={input}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Yearly return (%)">
              <input value={form.return_rate} onChange={(e) => set('return_rate', e.target.value)} inputMode="decimal" className={input} />
            </Field>
            <Field label="Term (months)">
              <input
                value={form.tenure_months}
                onChange={(e) => set('tenure_months', Number(e.target.value.replace(/\D/g, '')) || 0)}
                inputMode="numeric"
                className={input}
              />
            </Field>
            <Field label="Minimum (₦)">
              <input value={form.min_amount} onChange={(e) => set('min_amount', e.target.value)} inputMode="decimal" className={input} />
            </Field>
            <Field label="Maximum (₦)" hint="Leave empty for no limit.">
              <input
                value={form.max_amount ?? ''}
                onChange={(e) => set('max_amount', e.target.value)}
                inputMode="decimal"
                className={input}
              />
            </Field>
          </div>
          <Field label="Risk">
            <div className="flex gap-2">
              {(['low', 'medium', 'high'] as Risk[]).map((r) => (
                <button
                  key={r}
                  type="button"
                  aria-pressed={form.risk === r}
                  onClick={() => set('risk', r)}
                  className={clsx(
                    'px-3 py-1.5 rounded-lg text-[12px] font-medium ring-1',
                    form.risk === r ? 'bg-[#1b2f6b] text-white ring-[#1b2f6b]' : 'bg-white text-slate-600 ring-slate-200',
                  )}
                >
                  {RISK[r].label}
                </button>
              ))}
            </div>
          </Field>
          <label className="flex items-center gap-2.5 text-[13px] text-slate-700">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => set('is_active', e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 accent-[#1b2f6b]"
            />
            On sale in the app
          </label>
          {sample > 0 && returns > 0 ? (
            <p className="text-[12px] rounded-lg bg-emerald-50 text-emerald-800 px-3 py-2 ring-1 ring-emerald-100">
              {naira(sample)} for {form.tenure_months} months earns {naira(returns.toFixed(2))}, paid back as{' '}
              {naira((sample + returns).toFixed(2))}.
            </p>
          ) : null}
          {error ? <p className="text-[12px] text-rose-600">{error}</p> : null}
        </div>
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-slate-100">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg ring-1 ring-slate-200 text-[13px] font-semibold text-slate-600">
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="px-4 py-2 rounded-lg bg-[#1b2f6b] text-white text-[13px] font-semibold disabled:opacity-50"
          >
            {busy ? 'Saving…' : plan ? 'Save changes' : 'Create plan'}
          </button>
        </div>
      </form>
    </div>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[12px] font-medium text-slate-700 mb-1.5">{label}</span>
      {children}
      {hint ? <span className="block text-[11px] text-slate-400 mt-1">{hint}</span> : null}
    </label>
  )
}
