import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import { Check, CheckCheck, CheckCircle2, LifeBuoy, Send, Smartphone } from 'lucide-react'
import { AdminLayout } from '../components/AdminLayout'
import { PermissionGate } from '../components/PermissionGate'
import { useAuth } from '../lib/auth'
import { hasPermission } from '../lib/permissions'
import { supportApi, type SupportMessage, type SupportTicket, type TicketStatus } from '../lib/supportApi'
import { supportSocket, useSupportSocket, type SocketState, type SupportEvent } from '../lib/supportSocket'
import { ApiError } from '../lib/api'

const CATEGORY: Record<string, string> = {
  payments: 'Payments',
  loans: 'Loans',
  account: 'Account',
  app: 'App problem',
  data: 'Data request',
  other: 'Other',
}

const STATUS: Record<TicketStatus, { label: string; className: string }> = {
  open: { label: 'New', className: 'bg-sky-50 text-sky-700 ring-sky-200' },
  in_progress: { label: 'In progress', className: 'bg-indigo-50 text-indigo-700 ring-indigo-200' },
  resolved: { label: 'Resolved', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
}

const FILTERS: { value: TicketStatus | ''; label: string }[] = [
  { value: 'open', label: 'New' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'resolved', label: 'Resolved' },
  { value: '', label: 'All' },
]

export function SupportPage() {
  return (
    <PermissionGate permission="support:read">
      <SupportPageContent />
    </PermissionGate>
  )
}

function SupportPageContent() {
  const { token, staff } = useAuth()
  const canRespond = hasPermission(staff, 'support:respond')
  const [filter, setFilter] = useState<TicketStatus | ''>('open')
  const [tickets, setTickets] = useState<SupportTicket[]>([])
  const [openCount, setOpenCount] = useState(0)
  const [selected, setSelected] = useState<SupportTicket | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!token) return
    setLoading(true)
    setError('')
    try {
      const page = await supportApi.list(token, filter || undefined)
      setTickets(page.items)
      setOpenCount(page.open)
      setSelected((cur) => page.items.find((t) => t.id === cur?.id) ?? page.items[0] ?? null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load requests')
    } finally {
      setLoading(false)
    }
  }, [token, filter])

  useEffect(() => {
    load()
  }, [load])

  const onUpdated = (t: SupportTicket) => {
    setSelected(t)
    load()
  }

  // ── Live updates ──────────────────────────────────────────────────────
  const [typing, setTyping] = useState<Record<string, number>>({})
  const reloadSoon = useRef<number | undefined>(undefined)

  const applyEvent = useCallback(
    (e: SupportEvent) => {
      const patch = (t: SupportTicket): SupportTicket => {
        if (t.id !== e.ticket_id) return t
        if (e.type === 'message') {
          if (t.messages.some((m) => m.id === e.message.id)) return t
          return {
            ...t,
            status: e.status,
            messages: [...t.messages, e.message],
            awaiting_reply: e.message.author === 'customer',
            updated_at: e.message.created_at,
          }
        }
        if (e.type === 'read') {
          const mine = e.by === 'customer' ? 'staff' : 'customer'
          return { ...t, messages: t.messages.map((m) => (m.author === mine && !m.read_at ? { ...m, read_at: e.at } : m)) }
        }
        if (e.type === 'ticket') return { ...t, status: e.status }
        return t
      }
      if (e.type === 'typing') {
        if (e.author === 'customer') setTyping((cur) => ({ ...cur, [e.ticket_id]: Date.now() }))
        return
      }
      if (e.type === 'message' && e.message.author === 'customer') {
        setTyping((cur) => ({ ...cur, [e.ticket_id]: 0 }))
      }
      setSelected((cur) => (cur ? patch(cur) : cur))
      setTickets((cur) => {
        if (!cur.some((t) => t.id === e.ticket_id)) {
          // A request not on this list (new, or another filter): refresh the list shortly.
          window.clearTimeout(reloadSoon.current)
          reloadSoon.current = window.setTimeout(load, 400)
          return cur
        }
        const next = cur.map(patch)
        if (e.type !== 'message') return next
        const moved = next.find((t) => t.id === e.ticket_id)!
        return [moved, ...next.filter((t) => t.id !== e.ticket_id)]
      })
    },
    [load],
  )
  const live = useSupportSocket(applyEvent)

  // "Typing…" fades after 5 seconds without another keystroke event.
  const [, tick] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => tick((n) => n + 1), 1000)
    return () => window.clearInterval(id)
  }, [])
  const isTyping = (id: string) => Date.now() - (typing[id] ?? 0) < 5000

  return (
    <AdminLayout title="Support" subtitle={`Requests customers sent from the app · ${openCount} waiting`}>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {FILTERS.map((f) => (
          <button
            key={f.label}
            onClick={() => setFilter(f.value)}
            className={clsx(
              'px-3 py-1.5 rounded-full text-[12px] font-semibold ring-1',
              filter === f.value ? 'bg-[#1b2f6b] text-white ring-[#1b2f6b]' : 'bg-white text-slate-600 ring-slate-200',
            )}
          >
            {f.label}
          </button>
        ))}
        <LiveBadge state={live} />
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-rose-50 text-rose-700 text-[13px] ring-1 ring-rose-200">{error}</div>
      )}

      <div className="grid lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-4">
        <div className="dash-card overflow-hidden">
          {loading ? (
            <div className="p-16 text-center">
              <div className="inline-block h-9 w-9 rounded-full border-2 border-slate-200 border-t-[#1b2f6b] animate-spin" />
            </div>
          ) : tickets.length === 0 ? (
            <div className="px-6 py-16 text-center">
              <LifeBuoy className="h-10 w-10 text-slate-300 mx-auto mb-3" />
              <p className="text-sm font-semibold text-slate-700">Nothing here</p>
              <p className="text-[12px] text-slate-400 mt-1">No requests with this status.</p>
            </div>
          ) : (
            <ul>
              {tickets.map((t) => (
                <li key={t.id}>
                  <button
                    onClick={() => setSelected(t)}
                    className={clsx(
                      'w-full text-left px-5 py-4 border-b border-slate-100 hover:bg-slate-50/70',
                      selected?.id === t.id && 'bg-slate-50',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-[13px] font-semibold text-slate-900 truncate">{t.customer_name}</p>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {t.awaiting_reply && t.status !== 'resolved' ? (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 ring-1 ring-amber-200">
                            Needs reply
                          </span>
                        ) : null}
                        <StatusPill status={t.status} />
                      </div>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      {t.reference} · {CATEGORY[t.category] ?? t.category} · {new Date(t.updated_at ?? t.created_at).toLocaleString()}
                    </p>
                    <p className="text-[12px] text-slate-600 mt-1 line-clamp-2">
                      {isTyping(t.id) ? (
                        <span className="text-emerald-600 font-medium">Typing…</span>
                      ) : (
                        (t.messages?.at(-1)?.body ?? t.message)
                      )}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {selected ? (
          <TicketDetail
            key={selected.id}
            ticket={selected}
            canRespond={canRespond}
            token={token}
            onUpdated={onUpdated}
            onMessage={(m, status) => applyEvent({ type: 'message', ticket_id: selected.id, customer_id: selected.customer_id, status, message: m })}
            customerTyping={isTyping(selected.id)}
            live={live === 'live'}
          />
        ) : null}
      </div>
    </AdminLayout>
  )
}

function TicketDetail({
  ticket,
  canRespond,
  token,
  onUpdated,
  onMessage,
  customerTyping,
  live,
}: {
  ticket: SupportTicket
  canRespond: boolean
  token: string | null
  onUpdated: (t: SupportTicket) => void
  onMessage: (m: SupportMessage, status: TicketStatus) => void
  customerTyping: boolean
  live: boolean
}) {
  const [reply, setReply] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const thread = useRef<HTMLDivElement>(null)
  const lastTyped = useRef(0)

  const count = ticket.messages?.length ?? 0
  const unread = ticket.messages?.some((m) => m.author === 'customer' && !m.read_at)

  // Keep the newest message in view.
  useEffect(() => {
    thread.current?.scrollTo({ top: thread.current.scrollHeight, behavior: 'smooth' })
  }, [count, customerTyping])

  // Opening the request (or a new customer message while it's open) marks it read.
  useEffect(() => {
    if (!unread || !token) return
    if (live) supportSocket.read(ticket.id)
    else supportApi.read(token, ticket.id).catch(() => undefined)
  }, [unread, live, token, ticket.id])

  const onType = (value: string) => {
    setReply(value)
    const now = Date.now()
    if (live && value.trim() && now - lastTyped.current > 2500) {
      lastTyped.current = now
      supportSocket.typing(ticket.id)
    }
  }

  const send = async (body: { reply?: string; status?: TicketStatus }) => {
    if (!token) return
    setBusy(true)
    setError('')
    try {
      // A plain reply goes over the live connection when it's up; HTTP otherwise.
      if (body.reply && !body.status && live) {
        try {
          const ack = await supportSocket.send(ticket.id, body.reply)
          onMessage(ack.message, ack.status)
          setReply('')
          return
        } catch {
          /* fall through to HTTP */
        }
      }
      onUpdated(await supportApi.update(token, ticket.id, body))
      setReply('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update the request')
    } finally {
      setBusy(false)
    }
  }

  const lastStaff = [...(ticket.messages ?? [])].reverse().find((m) => m.author === 'staff')

  return (
    <div className="dash-card p-6 space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {ticket.reference} · {CATEGORY[ticket.category] ?? ticket.category}
          </p>
          <Link to={`/customers/${ticket.customer_id}`} className="text-lg font-bold text-slate-900 hover:text-[#1b2f6b]">
            {ticket.customer_name}
          </Link>
          <p className="text-[12px] text-slate-500">{ticket.customer_phone}</p>
        </div>
        <StatusPill status={ticket.status} />
      </div>

      <div ref={thread} className="space-y-3 max-h-[28rem] overflow-y-auto pr-1">
        {(ticket.messages?.length
          ? ticket.messages
          : [{ id: 'first', author: 'customer' as const, author_name: 'Customer', body: ticket.message, created_at: ticket.created_at }]
        ).map((m) => (
          <div
            key={m.id}
            className={clsx(
              'rounded-xl p-4 ring-1 max-w-[88%]',
              m.author === 'staff' ? 'ml-auto bg-[#1b2f6b]/5 ring-[#1b2f6b]/10' : 'bg-slate-50 ring-slate-100',
            )}
          >
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              {m.author === 'staff' ? m.author_name : ticket.customer_name}
            </p>
            <p className="text-[13px] text-slate-800 whitespace-pre-wrap mt-1">{m.body}</p>
            <p className="text-[11px] text-slate-400 mt-2 flex items-center gap-1">
              {new Date(m.created_at).toLocaleString()}
              {m.author === 'staff' ? (
                m.read_at ? (
                  <span className="inline-flex items-center gap-0.5 text-sky-600" title={`Seen ${new Date(m.read_at).toLocaleString()}`}>
                    <CheckCheck className="h-3.5 w-3.5" />
                    {m.id === lastStaff?.id ? 'Seen' : null}
                  </span>
                ) : (
                  <Check className="h-3.5 w-3.5" aria-label="Sent" />
                )
              ) : null}
            </p>
          </div>
        ))}
        {customerTyping ? (
          <div className="inline-flex items-center gap-1 rounded-xl bg-slate-50 ring-1 ring-slate-100 px-4 py-3" aria-label="Customer is typing">
            <span className="h-1.5 w-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-slate-400 animate-bounce [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-slate-400 animate-bounce" />
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-x-6 gap-y-1 text-[12px] text-slate-500">
        {ticket.related_type ? (
          <span>
            About {ticket.related_type} <span className="font-mono text-slate-700">{ticket.related_id}</span>
          </span>
        ) : null}
        {ticket.device_name || ticket.app_version ? (
          <span className="inline-flex items-center gap-1">
            <Smartphone className="h-3.5 w-3.5" />
            {[ticket.device_name, ticket.platform, ticket.app_version && `app ${ticket.app_version}`].filter(Boolean).join(' · ')}
          </span>
        ) : null}
      </div>

      {error && <div className="px-4 py-3 rounded-xl bg-rose-50 text-rose-700 text-[13px] ring-1 ring-rose-200">{error}</div>}

      {canRespond ? (
        <div className="space-y-3">
          <textarea
            value={reply}
            onChange={(e) => onType(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && reply.trim()) send({ reply: reply.trim() })
            }}
            rows={4}
            placeholder="Write a reply. The customer gets a notification and can reply back in the app."
            className="w-full text-[13px] rounded-xl ring-1 ring-slate-200 p-3 outline-none focus:ring-[#1b2f6b]/30"
          />
          <div className="flex flex-wrap gap-2">
            <button
              disabled={busy || reply.trim().length < 2}
              onClick={() => send({ reply: reply.trim() })}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[#1b2f6b] text-white text-[13px] font-semibold disabled:opacity-50"
            >
              <Send className="h-4 w-4" /> Send reply
            </button>
            {ticket.status !== 'resolved' ? (
              <button
                disabled={busy}
                onClick={() => send({ status: 'resolved', ...(reply.trim().length >= 2 ? { reply: reply.trim() } : {}) })}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg ring-1 ring-emerald-200 bg-emerald-50 text-emerald-700 text-[13px] font-semibold disabled:opacity-50"
              >
                <CheckCircle2 className="h-4 w-4" /> {reply.trim() ? 'Reply and resolve' : 'Mark resolved'}
              </button>
            ) : (
              <button
                disabled={busy}
                onClick={() => send({ status: 'in_progress' })}
                className="px-4 py-2 rounded-lg ring-1 ring-slate-200 bg-white text-slate-600 text-[13px] font-semibold disabled:opacity-50"
              >
                Reopen
              </button>
            )}
          </div>
        </div>
      ) : (
        <p className="text-[12px] text-slate-400">You can read requests but not reply to them.</p>
      )}
    </div>
  )
}

function LiveBadge({ state }: { state: SocketState }) {
  const tone =
    state === 'live'
      ? { dot: 'bg-emerald-500', text: 'Live', cls: 'text-emerald-700 bg-emerald-50 ring-emerald-200' }
      : state === 'connecting'
        ? { dot: 'bg-amber-400 animate-pulse', text: 'Connecting…', cls: 'text-amber-700 bg-amber-50 ring-amber-200' }
        : { dot: 'bg-slate-400', text: 'Offline · refresh for new messages', cls: 'text-slate-500 bg-slate-50 ring-slate-200' }
  return (
    <span className={clsx('ml-auto inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold ring-1', tone.cls)}>
      <span className={clsx('h-1.5 w-1.5 rounded-full', tone.dot)} />
      {tone.text}
    </span>
  )
}

function StatusPill({ status }: { status: TicketStatus }) {
  const s = STATUS[status] ?? STATUS.open
  return (
    <span className={clsx('shrink-0 px-2.5 py-1 rounded-full text-[11px] font-semibold ring-1', s.className)}>{s.label}</span>
  )
}
