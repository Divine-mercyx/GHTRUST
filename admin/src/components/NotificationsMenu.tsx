import clsx from 'clsx'
import { Bell, CheckCircle2, ChevronRight, FileClock, Wallet } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { formatNaira, loansApi, type ApplicationSummary } from '../lib/loansApi'
import { hasPermission } from '../lib/permissions'

/**
 * Header bell. There is no notification service on the server, so this is built from
 * the application queue: what is waiting on staff right now. The dot marks items that
 * arrived since the panel was last opened on this browser.
 */

const REVIEW_STATUSES = new Set(['submitted', 'under_review', 'documents_incomplete'])
const DISBURSE_STATUSES = new Set(['approved', 'ready_to_disburse'])
const REFRESH_MS = 60_000
const SEEN_KEY = 'ghtrust.notifications.seenAt'
const MAX_PER_GROUP = 5

function readSeenAt(): number {
  try {
    return Number(localStorage.getItem(SEEN_KEY)) || 0
  } catch {
    return 0
  }
}

function writeSeenAt(value: number) {
  try {
    localStorage.setItem(SEEN_KEY, String(value))
  } catch {
    // Storage unavailable (private mode): the dot just won't remember.
  }
}

function activityTime(app: ApplicationSummary): number {
  return new Date(app.submitted_at ?? app.created_at).getTime()
}

function timeAgo(ms: number): string {
  const minutes = Math.round((Date.now() - ms) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return days === 1 ? 'yesterday' : `${days}d ago`
}

const STATUS_LABEL: Record<string, string> = {
  submitted: 'New application',
  under_review: 'In review',
  documents_incomplete: 'Waiting on documents',
  offer_sent: 'Offer with customer',
  approved: 'Approved',
  ready_to_disburse: 'Ready to disburse',
}

export function NotificationsMenu() {
  const { token, staff } = useAuth()
  const navigate = useNavigate()
  const canRead = hasPermission(staff, 'loan:read')
  const [open, setOpen] = useState(false)
  const [apps, setApps] = useState<ApplicationSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [seenAt, setSeenAt] = useState(readSeenAt)
  const rootRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    if (!token || !canRead) return
    setLoading(true)
    try {
      setApps(await loansApi.listApplications(token))
      setError(false)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [token, canRead])

  useEffect(() => {
    load()
    const timer = window.setInterval(load, REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [load])

  // Close on outside click or Escape.
  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const byNewest = (a: ApplicationSummary, b: ApplicationSummary) => activityTime(b) - activityTime(a)
  const review = apps.filter((a) => REVIEW_STATUSES.has(a.status)).sort(byNewest)
  const disburse = apps.filter((a) => DISBURSE_STATUSES.has(a.status)).sort(byNewest)
  const total = review.length + disburse.length
  const unseen = [...review, ...disburse].filter((a) => activityTime(a) > seenAt).length

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (next) {
      load()
      const now = Date.now()
      writeSeenAt(now)
      setSeenAt(now)
    }
  }

  const go = (path: string) => {
    setOpen(false)
    navigate(path)
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={toggle}
        aria-label={unseen ? `Notifications, ${unseen} new` : 'Notifications'}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={clsx(
          'relative h-9 w-9 rounded-lg ring-1 flex items-center justify-center transition-colors cursor-pointer',
          open ? 'bg-white ring-slate-300' : 'bg-slate-100 ring-slate-200/80 hover:bg-white',
        )}
      >
        <Bell className="h-[15px] w-[15px] text-slate-500" />
        {unseen > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-[#1b2f6b] text-white text-[9px] font-bold leading-4 text-center ring-2 ring-white">
            {unseen > 9 ? '9+' : unseen}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          className="absolute right-0 top-11 z-50 w-[min(380px,calc(100vw-2rem))] rounded-xl bg-white shadow-xl ring-1 ring-slate-200 overflow-hidden"
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
            <div>
              <p className="text-[13px] font-semibold text-slate-900">Notifications</p>
              <p className="text-[11px] text-slate-400">
                {total ? `${total} item${total === 1 ? '' : 's'} waiting on staff` : 'Nothing waiting on staff'}
              </p>
            </div>
            {loading && <span className="text-[11px] text-slate-400">Updating…</span>}
          </div>

          <div className="max-h-[420px] overflow-y-auto">
            {!canRead ? (
              <Empty text="You don't have access to loan applications." />
            ) : error && !apps.length ? (
              <Empty text="Couldn't load notifications. Check your connection." />
            ) : !total ? (
              <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
                <CheckCircle2 className="h-6 w-6 text-emerald-500" />
                <p className="text-[13px] font-medium text-slate-700">You're all caught up</p>
                <p className="text-[11px] text-slate-400">New applications and approved loans will show here.</p>
              </div>
            ) : (
              <>
                <Group
                  title="Needs review"
                  icon={<FileClock className="h-3.5 w-3.5" />}
                  items={review}
                  seenAt={seenAt}
                  onOpen={(id) => go(`/applications/${id}`)}
                  onViewAll={() => go('/applications')}
                />
                <Group
                  title="Ready to disburse"
                  icon={<Wallet className="h-3.5 w-3.5" />}
                  items={disburse}
                  seenAt={seenAt}
                  onOpen={(id) => go(`/applications/${id}`)}
                  onViewAll={() => go('/applications?status=approved')}
                />
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <p className="px-4 py-8 text-center text-[12px] text-slate-400">{text}</p>
}

function Group({
  title,
  icon,
  items,
  seenAt,
  onOpen,
  onViewAll,
}: {
  title: string
  icon: React.ReactNode
  items: ApplicationSummary[]
  seenAt: number
  onOpen: (id: string) => void
  onViewAll: () => void
}) {
  if (!items.length) return null
  return (
    <section className="py-2">
      <p className="flex items-center gap-1.5 px-4 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-400">
        {icon}
        {title} · {items.length}
      </p>
      <ul>
        {items.slice(0, MAX_PER_GROUP).map((app) => {
          const when = activityTime(app)
          const isNew = when > seenAt
          return (
            <li key={app.id}>
              <button
                type="button"
                onClick={() => onOpen(app.id)}
                className="w-full flex items-start gap-3 px-4 py-2.5 text-left hover:bg-slate-50 transition-colors"
              >
                <span
                  className={clsx('mt-1.5 h-1.5 w-1.5 rounded-full shrink-0', isNew ? 'bg-[#2fa4d7]' : 'bg-transparent')}
                  aria-hidden
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-medium text-slate-800 truncate">
                    {app.applicant_name ?? 'Unknown applicant'}
                  </span>
                  <span className="block text-[11px] text-slate-500 truncate">
                    {[STATUS_LABEL[app.status] ?? app.status, app.product_name, app.current_stage_name]
                      .filter((part, i, all) => part && all.indexOf(part) === i)
                      .join(' · ')}
                  </span>
                </span>
                <span className="text-right shrink-0">
                  <span className="block text-[12px] font-semibold text-slate-800">
                    {formatNaira(app.approved_amount ?? app.requested_amount)}
                  </span>
                  <span className="block text-[10px] text-slate-400">{timeAgo(when)}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      {items.length > MAX_PER_GROUP && (
        <button
          type="button"
          onClick={onViewAll}
          className="w-full flex items-center justify-center gap-1 px-4 py-2 text-[11px] font-medium text-[#1b2f6b] hover:bg-slate-50"
        >
          View all {items.length}
          <ChevronRight className="h-3 w-3" />
        </button>
      )}
    </section>
  )
}
