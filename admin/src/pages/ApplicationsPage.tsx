import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  CheckCircle2,
  FileText,
  Search,
  Shield,
} from 'lucide-react'
import clsx from 'clsx'
import { AdminLayout } from '../components/AdminLayout'
import { LoanQueueCharts } from '../components/LoanQueueCharts'
import { WorkflowPipeline } from '../components/WorkflowPipeline'
import { PermissionGate } from '../components/PermissionGate'
import { initials } from '../lib/productMeta'
import { formatNaira, loansApi, type ApplicationSummary } from '../lib/loansApi'
import { useAuth } from '../lib/auth'

const STATUS_FILTERS = [
  { value: '', label: 'All' },
  { value: 'under_review', label: 'Under review' },
  { value: 'submitted', label: 'Submitted' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'disbursed', label: 'Disbursed' },
] as const

function channelLabel(channel: string | null | undefined): string {
  if (!channel) return 'VIA WEB'
  return `VIA ${channel.replace(/_/g, ' ').toUpperCase()}`
}

function formatLoanRef(id: string): string {
  const num = id.replace(/\D/g, '').slice(-4) || id.slice(0, 4)
  return `#LOAN-${num.padStart(4, '0')}`
}

function isNewApp(app: ApplicationSummary): boolean {
  const ts = app.submitted_at ?? app.created_at
  if (!ts) return false
  return Date.now() - new Date(ts).getTime() < 7 * 24 * 60 * 60 * 1000
}

function QueueStatusPill({ status }: { status: string }) {
  const config: Record<string, { label: string; bg: string; text: string; dot: string }> = {
    under_review: { label: 'Pending', bg: 'bg-orange-50', text: 'text-orange-700', dot: 'bg-orange-500' },
    submitted: { label: 'Submitted', bg: 'bg-sky-50', text: 'text-sky-700', dot: 'bg-sky-500' },
    offer_sent: { label: 'Offer with customer', bg: 'bg-amber-50', text: 'text-amber-700', dot: 'bg-amber-500' },
    approved: { label: 'Approved', bg: 'bg-blue-50', text: 'text-blue-700', dot: 'bg-blue-500' },
    disbursed: { label: 'Disbursed', bg: 'bg-emerald-50', text: 'text-emerald-700', dot: 'bg-emerald-500' },
    rejected: { label: 'Rejected', bg: 'bg-rose-50', text: 'text-rose-700', dot: 'bg-rose-500' },
    draft: { label: 'Draft', bg: 'bg-slate-100', text: 'text-slate-600', dot: 'bg-slate-400' },
  }
  const c = config[status] ?? {
    label: status.replace(/_/g, ' '),
    bg: 'bg-slate-100',
    text: 'text-slate-600',
    dot: 'bg-slate-400',
  }
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-[11px] font-bold uppercase tracking-wide',
        c.bg,
        c.text,
      )}
    >
      <span className={clsx('h-2 w-2 rounded-full', c.dot)} />
      {c.label}
    </span>
  )
}

function AvatarStack({ apps }: { apps: ApplicationSummary[] }) {
  const sample = apps.slice(0, 4)
  const extra = apps.length - sample.length
  return (
    <div className="flex items-center -space-x-2">
      {sample.map((app) => (
        <div
          key={app.id}
          className="h-8 w-8 rounded-full bg-slate-200 ring-2 ring-white flex items-center justify-center text-[10px] font-bold text-slate-600"
          title={app.applicant_name ?? undefined}
        >
          {initials(app.applicant_name)}
        </div>
      ))}
      {extra > 0 && (
        <div className="h-8 w-8 rounded-full bg-[#1b2f6b] ring-2 ring-white flex items-center justify-center text-[10px] font-bold text-white">
          +{extra}
        </div>
      )}
    </div>
  )
}

export function ApplicationsPage() {
  return (
    <PermissionGate permission="loan:read">
      <ApplicationsPageContent />
    </PermissionGate>
  )
}

function ApplicationsPageContent() {
  const { token } = useAuth()
  const [searchParams] = useSearchParams()
  const [apps, setApps] = useState<ApplicationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState(() => searchParams.get('status') ?? '')
  const [search, setSearch] = useState('')

  useEffect(() => {
    const status = searchParams.get('status') ?? ''
    setFilter(status)
  }, [searchParams])

  // Load the queue once (newest 500, the API's maximum); tabs filter it here, so switching
  // is instant and the charts always have every status to draw.
  useEffect(() => {
    if (!token) return
    setLoading(true)
    loansApi
      .listApplications(token, { limit: 500 })
      .then(setApps)
      .finally(() => setLoading(false))
  }, [token])

  const filtered = useMemo(() => {
    const inTab = filter ? apps.filter((app) => app.status === filter) : apps
    const q = search.trim().toLowerCase()
    if (!q) return inTab
    return inTab.filter((app) => {
      const name = (app.applicant_name ?? '').toLowerCase()
      const product = app.product_name.toLowerCase()
      const id = app.id.toLowerCase()
      const acct = (app.account_number ?? '').toLowerCase()
      return name.includes(q) || product.includes(q) || id.includes(q) || acct.includes(q)
    })
  }, [apps, filter, search])

  return (
    <AdminLayout title="Loan queue" subtitle="Active pipeline — review and action applications">
      <LoanQueueCharts applications={apps} status={filter} />

      {/* Toolbar */}
      <div className="flex flex-col lg:flex-row lg:items-center gap-4 mb-5">
        <div className="flex flex-wrap gap-2 flex-1">
          {STATUS_FILTERS.map((chip) => (
            <button
              key={chip.value}
              type="button"
              onClick={() => setFilter(chip.value)}
              className={clsx(
                'px-3.5 py-1.5 rounded-lg text-[12px] font-semibold transition-all',
                filter === chip.value
                  ? 'bg-[#1b2f6b] text-white shadow-sm'
                  : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:ring-slate-300',
              )}
            >
              {chip.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2.5 h-10 px-3.5 rounded-lg bg-white ring-1 ring-slate-200/90 min-w-[220px] lg:max-w-xs focus-within:ring-[#0B84CE]/40 transition-all">
          <Search className="h-4 w-4 text-slate-400 shrink-0" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search applicant, product…"
            className="bg-transparent border-none outline-none text-[13px] text-slate-700 placeholder:text-slate-400 w-full"
          />
        </label>
      </div>

      {/* Active pipeline table */}
      <div className="dash-card overflow-hidden border-slate-200/90">
        <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-5 border-b border-slate-100">
          <div>
            <h3 className="text-lg font-bold text-slate-900 tracking-tight">Active Pipeline</h3>
            <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mt-1">
              Found {filtered.length} total record{filtered.length === 1 ? '' : 's'}
            </p>
          </div>
          <AvatarStack apps={filtered} />
        </div>

        {loading ? (
          <div className="p-16 text-center">
            <div className="inline-block h-9 w-9 rounded-full border-2 border-slate-200 border-t-[#0B84CE] animate-spin" />
            <p className="text-slate-400 text-sm mt-4">Loading pipeline…</p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-16 text-center">
            <FileText className="h-10 w-10 text-slate-300 mx-auto" />
            <p className="text-slate-600 font-medium mt-4">No applications in this view</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead>
                <tr className="text-left text-[10px] font-bold text-slate-400 uppercase tracking-widest border-b border-slate-100 bg-slate-50/80">
                  <th className="px-4 py-3 min-w-[220px]">Applicant</th>
                  <th className="px-4 py-3 min-w-[160px]">Loan detail</th>
                  <th className="px-4 py-3 min-w-[180px]">Stage & progress</th>
                  <th className="px-4 py-3 min-w-[120px]">Financials</th>
                  <th className="px-4 py-3 w-16 text-center">Indemnity</th>
                  <th className="px-4 py-3 min-w-[120px]">Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((app) => {
                  const name = app.applicant_name ?? 'Unknown applicant'
                  const progress = app.stage_progress_pct ?? 0
                  const submitted = app.submitted_at ?? app.created_at
                  const dateStr = submitted
                    ? new Date(submitted).toLocaleDateString('en-GB', {
                        day: '2-digit',
                        month: '2-digit',
                        year: 'numeric',
                      })
                    : '—'
                  const indemnityOk = app.status === 'approved' || app.status === 'disbursed'

                  return (
                    <tr
                      key={app.id}
                      className="border-t border-slate-100 hover:bg-sky-50/30 transition-colors group"
                    >
                      <td className="px-4 py-5 align-top">
                        <Link to={`/applications/${app.id}`} className="flex gap-3 min-w-0">
                          <div className="h-10 w-10 rounded-full bg-slate-200 flex items-center justify-center text-[11px] font-bold text-slate-600 shrink-0 group-hover:ring-2 group-hover:ring-[#0B84CE]/30 transition-all">
                            {initials(name)}
                          </div>
                          <div className="min-w-0">
                            <p className="text-[13px] font-bold text-slate-900 uppercase leading-snug group-hover:text-[#0B84CE] transition-colors">
                              {name}
                            </p>
                            <p className="text-[11px] text-slate-400 mt-1 font-medium">
                              {formatLoanRef(app.id)} · {dateStr}
                            </p>
                            {app.account_number && (
                              <p className="text-[11px] font-semibold text-[#0B84CE] mt-1">
                                CASA: {app.account_number}
                              </p>
                            )}
                            <span className="inline-block mt-2 text-[9px] font-bold uppercase tracking-wide px-2 py-0.5 rounded bg-orange-50 text-orange-700 border border-orange-200/80">
                              {channelLabel(app.channel)}
                            </span>
                          </div>
                        </Link>
                      </td>
                      <td className="px-4 py-5 align-top">
                        <span className="inline-block text-[10px] font-bold uppercase tracking-wide px-2.5 py-1.5 rounded-md bg-sky-100 text-sky-800 border border-sky-200/80 leading-tight max-w-[140px]">
                          {app.product_name}
                        </span>
                        {isNewApp(app) && (
                          <p className="text-[10px] font-bold text-slate-400 uppercase mt-2 tracking-wide">New</p>
                        )}
                      </td>
                      <td className="px-4 py-5 align-top">
                        <p className="text-[11px] font-bold text-slate-800 uppercase tracking-wide">
                          {app.current_stage_name ?? '—'}
                        </p>
                        {app.pipeline_stages && app.pipeline_stages.length > 0 ? (
                          <div className="mt-2">
                            <WorkflowPipeline
                              stages={app.pipeline_stages.map((s) => ({
                                name: s.name,
                                status: s.status as 'completed' | 'current' | 'upcoming' | 'rejected',
                              }))}
                              compact
                            />
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 mt-2 max-w-[160px]">
                            <div className="flex-1 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                              <div
                                className="h-full rounded-full bg-[#0B84CE] transition-all duration-500"
                                style={{ width: `${progress}%` }}
                              />
                            </div>
                            <span className="text-[11px] font-bold text-slate-500 tabular-nums w-8">
                              {progress}%
                            </span>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-5 align-top">
                        <p className="text-[15px] font-bold text-slate-900 tabular-nums">
                          {formatNaira(app.requested_amount)}
                        </p>
                        {app.approved_amount && app.status === 'disbursed' && (
                          <p className="text-[11px] font-semibold text-emerald-600 mt-1">
                            Disbursed: {formatNaira(app.approved_amount)}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-5 align-top text-center">
                        {indemnityOk ? (
                          <CheckCircle2 className="h-5 w-5 text-emerald-500 mx-auto" />
                        ) : (
                          <Shield className="h-5 w-5 text-slate-300 mx-auto" />
                        )}
                      </td>
                      <td className="px-4 py-5 align-top">
                        <QueueStatusPill status={app.status} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AdminLayout>
  )
}
