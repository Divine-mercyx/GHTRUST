import { useEffect, useState } from 'react'
import { Clock, Loader2 } from 'lucide-react'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { securityApi, type SecuritySettings } from '../lib/sessionTimeout'

const CHOICES = [5, 10, 15, 20, 30, 45, 60]

/**
 * `organisation`: the timeout for all staff (a super admin edits it, others see it).
 * `personal`: a shorter timeout for the signed-in staff member only.
 */
export function SessionTimeoutCard({ scope }: { scope: 'organisation' | 'personal' }) {
  const { token } = useAuth()
  const [data, setData] = useState<SecuritySettings | null>(null)
  const [value, setValue] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    if (!token) return
    securityApi
      .get(token)
      .then((s) => {
        setData(s)
        setValue(String(scope === 'organisation' ? s.staff_idle_minutes : (s.my_idle_minutes ?? '')))
      })
      .catch((e) => setNote({ ok: false, text: e instanceof ApiError ? e.message : 'Could not load the timeout' }))
  }, [token, scope])

  if (!data) {
    return (
      <div className="dash-card p-6 flex items-center gap-2 text-[13px] text-slate-500">
        {note ? note.text : <><Loader2 className="h-4 w-4 animate-spin" /> Loading session timeout…</>}
      </div>
    )
  }

  const editable = scope === 'personal' || data.can_edit
  const options = scope === 'organisation' ? CHOICES : CHOICES.filter((m) => m <= data.staff_idle_minutes)
  const current = scope === 'organisation' ? String(data.staff_idle_minutes) : String(data.my_idle_minutes ?? '')

  const save = async () => {
    if (!token) return
    setBusy(true)
    setNote(null)
    try {
      const next =
        scope === 'organisation'
          ? await securityApi.setOrg(token, Number(value))
          : await securityApi.setMine(token, value === '' ? null : Number(value))
      setData(next)
      setNote({
        ok: true,
        text:
          scope === 'organisation'
            ? `Staff are now signed out after ${next.staff_idle_minutes} minutes without activity.`
            : `You'll be signed out after ${next.effective_idle_minutes} minutes without activity.`,
      })
    } catch (e) {
      setNote({ ok: false, text: e instanceof ApiError ? e.message : 'Could not save' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dash-card p-6 space-y-4">
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 shrink-0 rounded-full bg-sky-50 grid place-items-center">
          <Clock className="h-5 w-5 text-sky-700" />
        </div>
        <div>
          <h3 className="text-[14px] font-semibold text-slate-900">
            {scope === 'organisation' ? 'Staff session timeout' : 'My session timeout'}
          </h3>
          <p className="text-[13px] text-slate-500 leading-relaxed">
            {scope === 'organisation'
              ? 'Everyone is signed out after this long without activity, with a minute’s warning. Only clicks, typing and scrolling count, not pages refreshing on their own.'
              : `Sign out sooner than the organisation requires (${data.staff_idle_minutes} minutes). You can't choose longer.`}
          </p>
        </div>
      </div>

      {editable ? (
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="text-[12px] font-semibold text-slate-600">After</span>
            <select
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="mt-1 block rounded-lg ring-1 ring-slate-200 px-3 py-2 text-[13px] bg-white"
            >
              {scope === 'personal' ? (
                <option value="">Same as organisation ({data.staff_idle_minutes} minutes)</option>
              ) : null}
              {options.map((m) => (
                <option key={m} value={m}>
                  {m} minutes
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={save}
            disabled={busy || value === current}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[#1b2f6b] text-white text-[13px] font-semibold disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Save
          </button>
        </div>
      ) : (
        <p className="text-[13px] text-slate-700">
          <strong>{data.staff_idle_minutes} minutes</strong>. Only a super admin can change it.
        </p>
      )}

      {scope === 'organisation' && data.updated_by_name ? (
        <p className="text-[12px] text-slate-400">
          Last changed by {data.updated_by_name}
          {data.updated_at ? ` on ${new Date(data.updated_at).toLocaleString()}` : ''}
        </p>
      ) : null}
      {note ? (
        <p className={note.ok ? 'text-[13px] text-emerald-700' : 'text-[13px] text-rose-700'} role="status">
          {note.text}
        </p>
      ) : null}
    </div>
  )
}
