import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import {
  Bell,
  Building2,
  Clock,
  FileText,
  Package,
  Server,
  Shield,
} from 'lucide-react'
import { AdminLayout } from '../components/AdminLayout'
import { SessionTimeoutCard } from '../components/SessionTimeoutCard'
import { PermissionGate } from '../components/PermissionGate'
import { useAuth } from '../lib/auth'
import { hasPermission } from '../lib/permissions'
import {
  formatDateTime,
  formatEventType,
  settingsApi,
  type AdminSettings,
  type BranchSummary,
  type GlobalAuditLog,
} from '../lib/settingsApi'
import type { LoanProduct } from '../lib/loansApi'
import { ApiError } from '../lib/api'

const tabs = [
  { id: 'system', label: 'System', icon: Server },
  { id: 'security', label: 'Security', icon: Shield },
  { id: 'branches', label: 'Branches', icon: Building2 },
  { id: 'products', label: 'Products', icon: Package },
  { id: 'audit', label: 'Audit log', icon: FileText },
] as const

type TabId = (typeof tabs)[number]['id']

export function SettingsPage() {
  return (
    <PermissionGate permission="loan:read">
      <SettingsPageContent />
    </PermissionGate>
  )
}

function SettingsPageContent() {
  const { token, staff } = useAuth()
  const [activeTab, setActiveTab] = useState<TabId>('system')
  const [settings, setSettings] = useState<AdminSettings | null>(null)
  const [branches, setBranches] = useState<BranchSummary[]>([])
  const [products, setProducts] = useState<LoanProduct[]>([])
  const [auditLogs, setAuditLogs] = useState<GlobalAuditLog[]>([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [togglingCode, setTogglingCode] = useState<string | null>(null)

  const canConfigure = hasPermission(staff, 'loan:configure_workflow')

  const load = useCallback(async () => {
    if (!token) return
    setLoading(true)
    setError('')
    try {
      const [settingsData, branchesData, productsData, auditData] = await Promise.all([
        settingsApi.get(token),
        settingsApi.listBranches(token),
        settingsApi.listProducts(token),
        settingsApi.listAuditLogs(token, { limit: 50 }),
      ])
      setSettings(settingsData)
      setBranches(branchesData)
      setProducts(productsData)
      setAuditLogs(auditData)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load settings')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!message) return
    const t = setTimeout(() => setMessage(''), 4000)
    return () => clearTimeout(t)
  }, [message])

  const toggleProduct = async (product: LoanProduct) => {
    if (!token || !canConfigure) return
    setTogglingCode(product.code)
    setError('')
    try {
      const updated = await settingsApi.toggleProduct(token, product.code, !product.is_active)
      setProducts((prev) => prev.map((p) => (p.code === updated.code ? updated : p)))
      setMessage(`${updated.name} ${updated.is_active ? 'enabled' : 'disabled'}.`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to update product')
    } finally {
      setTogglingCode(null)
    }
  }

  if (loading || !settings) {
    return (
      <AdminLayout title="Settings" subtitle="Operational configuration">
        <div className="flex items-center justify-center py-24">
          <div className="h-10 w-10 rounded-full border-2 border-slate-200 border-t-[#1b2f6b] animate-spin" />
        </div>
      </AdminLayout>
    )
  }

  return (
    <AdminLayout
      title="Settings"
      subtitle="Operational configuration and audit"
      tabs={tabs.map((t) => ({ id: t.id, label: t.label }))}
      activeTab={activeTab}
      onTabChange={(id) => setActiveTab(id as TabId)}
    >
      {(message || error) && (
        <div
          className={clsx(
            'mb-5 px-4 py-3 rounded-xl text-[13px] font-medium',
            error ? 'bg-rose-50 text-rose-700 ring-1 ring-rose-200' : 'bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200',
          )}
        >
          {error || message}
        </div>
      )}

      {activeTab === 'system' && (
        <div className="space-y-5">
          <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">
            <SettingCard
              icon={<Server className="h-5 w-5 text-sky-600" />}
              label="Environment"
              value={settings.app_env}
              detail={settings.app_name}
            />
            <SettingCard
              icon={<Building2 className="h-5 w-5 text-[#1b2f6b]" />}
              label="Default branch"
              value={settings.default_branch}
              detail="New customer onboarding"
            />
            <SettingCard
              icon={<Shield className="h-5 w-5 text-violet-600" />}
              label="Rate limiting"
              value={settings.rate_limits_active ? 'Active' : 'Disabled'}
              detail={settings.app_env === 'development' ? 'Off in development' : 'Production mode'}
            />
            <SettingCard
              icon={<Shield className="h-5 w-5 text-emerald-600" />}
              label="Dojah KYC"
              value={settings.dojah_enabled ? 'Live' : settings.dojah_mock ? 'Mock' : 'Not configured'}
              detail="BVN verification provider"
            />
            <SettingCard
              icon={<Bell className="h-5 w-5 text-amber-600" />}
              label="SMS / OTP"
              value={settings.sms_mock ? 'Console mock' : 'Live provider'}
              detail={`OTP expires in ${Math.round(settings.otp_expire_seconds / 60)} min`}
            />
            <SettingCard
              icon={<FileText className="h-5 w-5 text-slate-600" />}
              label="Upload limit"
              value={`${settings.max_upload_size_mb} MB`}
              detail="Max document size per file"
            />
          </div>

          <div className="dash-card p-6">
            <h3 className="text-[14px] font-semibold text-slate-900 mb-2">Notification preferences</h3>
            <p className="text-[13px] text-slate-500 leading-relaxed">
              Email and SMS alert routing for loan events, disbursements, and staff actions will be configurable here in a future release.
            </p>
            <span className="inline-block mt-3 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded bg-slate-100 text-slate-500">
              Coming soon
            </span>
          </div>
        </div>
      )}

      {activeTab === 'security' && (
        <div className="max-w-2xl space-y-5">
          <SessionTimeoutCard scope="organisation" />
        </div>
      )}

      {activeTab === 'branches' && (
        <div className="dash-card overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
            <h3 className="text-sm font-bold text-slate-900">Branch directory</h3>
            <p className="text-[11px] text-slate-400 mt-0.5">Derived from customer records · default branch from system config</p>
          </div>
          {branches.length === 0 ? (
            <p className="px-6 py-12 text-center text-[13px] text-slate-400">No branches found</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px]">
                <thead>
                  <tr className="text-left text-[10px] font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100">
                    <th className="px-6 py-3.5">Branch</th>
                    <th className="px-6 py-3.5">Customers</th>
                    <th className="px-6 py-3.5">Type</th>
                  </tr>
                </thead>
                <tbody>
                  {branches.map((b) => (
                    <tr key={b.name} className="border-t border-slate-100">
                      <td className="px-6 py-4 text-[13px] font-semibold text-slate-900">{b.name}</td>
                      <td className="px-6 py-4 text-[13px] text-slate-600 tabular-nums">{b.customer_count}</td>
                      <td className="px-6 py-4">
                        {b.name === settings.default_branch ? (
                          <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-[#1b2f6b]/10 text-[#1b2f6b]">Default</span>
                        ) : (
                          <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-slate-100 text-slate-500">Branch</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'products' && (
        <div className="space-y-4">
          {!canConfigure && (
            <div className="px-4 py-3 rounded-xl bg-amber-50 text-amber-800 text-[13px] ring-1 ring-amber-200/80">
              You need <strong>Configure workflows</strong> permission to enable or disable products.
            </div>
          )}
          <div className="grid md:grid-cols-2 gap-4">
            {products.map((product) => (
              <div key={product.code} className="dash-card p-5 flex flex-col">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h4 className="text-[15px] font-bold text-slate-900">{product.name}</h4>
                    <p className="text-[11px] font-mono text-slate-400 mt-0.5">{product.code}</p>
                    {product.description && (
                      <p className="text-[12px] text-slate-500 mt-2 line-clamp-2">{product.description}</p>
                    )}
                  </div>
                  <span
                    className={clsx(
                      'text-[10px] font-bold uppercase px-2 py-1 rounded-full shrink-0',
                      product.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500',
                    )}
                  >
                    {product.is_active ? 'Active' : 'Inactive'}
                  </span>
                </div>
                <div className="flex items-center justify-between mt-5 pt-4 border-t border-slate-100">
                  <Link
                    to="/loan-products"
                    className="text-[12px] font-semibold text-[#1b2f6b] hover:underline"
                  >
                    Edit workflow
                  </Link>
                  <button
                    type="button"
                    disabled={!canConfigure || togglingCode === product.code}
                    onClick={() => toggleProduct(product)}
                    className={clsx(
                      'px-4 py-2 rounded-lg text-[12px] font-semibold transition-colors disabled:opacity-50',
                      product.is_active
                        ? 'text-rose-600 ring-1 ring-rose-200 hover:bg-rose-50'
                        : 'text-white bg-[#1b2f6b] hover:bg-[#141f45]',
                    )}
                  >
                    {togglingCode === product.code ? 'Saving…' : product.is_active ? 'Disable' : 'Enable'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === 'audit' && (
        <div className="dash-card overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
            <h3 className="text-sm font-bold text-slate-900">Staff audit trail</h3>
            <p className="text-[11px] text-slate-400 mt-0.5">Recent staff actions across all loan applications</p>
          </div>
          {auditLogs.length === 0 ? (
            <p className="px-6 py-12 text-center text-[13px] text-slate-400">No staff audit entries yet</p>
          ) : (
            <div className="divide-y divide-slate-100">
              {auditLogs.map((log) => (
                <div key={log.id} className="px-6 py-4 hover:bg-slate-50/60 transition-colors">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-[13px] font-semibold text-slate-900 capitalize">
                        {formatEventType(log.event_type)}
                      </p>
                      <p className="text-[12px] text-slate-500 mt-0.5">
                        {log.actor_label ?? 'Staff'} · {log.message ?? 'No message'}
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-[11px] text-slate-400 flex items-center gap-1 justify-end">
                        <Clock className="h-3 w-3" />
                        {formatDateTime(log.created_at)}
                      </p>
                      <Link
                        to={`/applications/${log.application_id}`}
                        className="text-[11px] font-semibold text-[#1b2f6b] hover:underline mt-1 inline-block"
                      >
                        View application
                      </Link>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </AdminLayout>
  )
}

function SettingCard({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode
  label: string
  value: string
  detail: string
}) {
  return (
    <div className="dash-card p-5">
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 rounded-xl bg-slate-100 flex items-center justify-center shrink-0">{icon}</div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
          <p className="text-[18px] font-bold text-slate-900 mt-0.5">{value}</p>
          <p className="text-[12px] text-slate-500 mt-1">{detail}</p>
        </div>
      </div>
    </div>
  )
}
