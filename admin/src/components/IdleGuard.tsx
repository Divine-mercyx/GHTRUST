import { useCallback, useEffect, useRef, useState } from 'react'
import { Clock } from 'lucide-react'
import { useAuth } from '../lib/auth'
import {
  HEARTBEAT_MS,
  WARNING_SECONDS,
  lastActivity,
  markActivity,
  securityApi,
  setSignOutReason,
} from '../lib/sessionTimeout'

const EVENTS = ['mousedown', 'keydown', 'scroll', 'touchstart', 'wheel'] as const

/**
 * Signs the staff member out after the idle timeout, with a minute's warning. Only real
 * input (clicks, typing, scrolling, touch) counts; data refreshing in the background
 * doesn't. Activity is reported to the server, which enforces the same limit.
 */
export function IdleGuard() {
  const { token, logout } = useAuth()
  const [limitMinutes, setLimitMinutes] = useState<number | null>(null)
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null)
  const lastSent = useRef(0)
  // Activity since the last report: sent as soon as the throttle allows.
  const pending = useRef(false)

  const heartbeat = useCallback(
    (force = false) => {
      if (!token) return
      const now = Date.now()
      if (!force && now - lastSent.current < HEARTBEAT_MS) {
        pending.current = true
        return
      }
      lastSent.current = now
      pending.current = false
      securityApi
        .activity(token)
        .then((r) => {
          markActivity(now) // the server's idle clock restarted at this moment
          setLimitMinutes(r.effective_idle_minutes)
        })
        .catch(() => undefined) // a 401 here signs out through the API client
    },
    [token],
  )

  // Signing in counts as activity; learn the limit that applies to this person.
  useEffect(() => {
    if (!token) return
    markActivity()
    heartbeat(true)
    securityApi
      .get(token)
      .then((s) => setLimitMinutes(s.effective_idle_minutes))
      .catch(() => undefined)
  }, [token, heartbeat])

  useEffect(() => {
    if (!token) return
    const onActivity = () => {
      // While the warning is up, only "Stay signed in" keeps the session.
      if (secondsLeft !== null) return
      heartbeat()
    }
    EVENTS.forEach((e) => window.addEventListener(e, onActivity, { passive: true }))
    return () => EVENTS.forEach((e) => window.removeEventListener(e, onActivity))
  }, [token, heartbeat, secondsLeft])

  useEffect(() => {
    if (!token || !limitMinutes) return
    const tick = () => {
      if (pending.current && Date.now() - lastSent.current >= HEARTBEAT_MS) heartbeat()
      const idleMs = Date.now() - lastActivity()
      const limitMs = limitMinutes * 60_000
      if (idleMs >= limitMs) {
        setSecondsLeft(null)
        setSignOutReason('idle')
        logout()
      } else if (idleMs >= limitMs - WARNING_SECONDS * 1000) {
        setSecondsLeft(Math.ceil((limitMs - idleMs) / 1000))
      } else {
        setSecondsLeft(null)
      }
    }
    tick()
    const id = window.setInterval(tick, 1000)
    return () => window.clearInterval(id)
  }, [token, limitMinutes, logout, heartbeat])

  if (!token || secondsLeft === null) return null

  const stay = () => {
    markActivity() // reset at once; the server confirms a moment later
    heartbeat(true)
    setSecondsLeft(null)
  }

  return (
    <div className="fixed inset-0 z-[100] grid place-items-center bg-slate-900/40 px-4" role="alertdialog" aria-modal="true" aria-labelledby="idle-title">
      <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl space-y-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-full bg-amber-50 grid place-items-center">
            <Clock className="h-5 w-5 text-amber-600" />
          </div>
          <h2 id="idle-title" className="text-[16px] font-bold text-slate-900">
            Still there?
          </h2>
        </div>
        <p className="text-[14px] text-slate-600">
          For security, you'll be signed out in <strong className="tabular-nums">{secondsLeft}s</strong> because you
          haven't been active for {limitMinutes} minutes.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            autoFocus
            onClick={stay}
            className="px-4 py-2 rounded-lg bg-[#1b2f6b] text-white text-[13px] font-semibold"
          >
            Stay signed in
          </button>
          <button
            onClick={() => logout()}
            className="px-4 py-2 rounded-lg ring-1 ring-slate-200 text-slate-600 text-[13px] font-semibold"
          >
            Sign out now
          </button>
        </div>
      </div>
    </div>
  )
}
