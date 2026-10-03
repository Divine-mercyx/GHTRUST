import { apiFetch } from './api'

/**
 * Staff idle timeout. The server sets and enforces it (a super admin chooses 5-60
 * minutes; staff may pick shorter for themselves). The portal reports real activity
 * so the server's clock restarts, warns a minute before, and signs out at the limit.
 */

export interface SecuritySettings {
  staff_idle_minutes: number
  min_minutes: number
  max_minutes: number
  updated_at: string | null
  updated_by_name: string | null
  my_idle_minutes: number | null
  effective_idle_minutes: number
  can_edit: boolean
}

export interface ActivityResult {
  effective_idle_minutes: number
  last_activity_at: string
  idle_expires_at: string
}

export const securityApi = {
  get: (token: string) => apiFetch<SecuritySettings>('/api/v1/admin/settings/security', {}, token),
  setOrg: (token: string, minutes: number) =>
    apiFetch<SecuritySettings>(
      '/api/v1/admin/settings/security',
      { method: 'PUT', body: JSON.stringify({ staff_idle_minutes: minutes }) },
      token,
    ),
  setMine: (token: string, minutes: number | null) =>
    apiFetch<SecuritySettings>(
      '/api/v1/admin/auth/me/session-timeout',
      { method: 'PUT', body: JSON.stringify({ minutes }) },
      token,
    ),
  activity: (token: string) => apiFetch<ActivityResult>('/api/v1/admin/auth/activity', { method: 'POST' }, token),
}

/** Seconds of warning before an idle sign-out. */
export const WARNING_SECONDS = 60
/** Report activity to the server at most this often (a trailing report always follows). */
export const HEARTBEAT_MS = 30_000

// When activity was last reported to the server. The idle countdown runs from this, so the
// warning matches the server's clock. Shared by every open tab, so activity in one keeps
// the others signed in too.
const ACTIVITY_KEY = 'ghtrust_admin_last_activity'

export function lastActivity(): number {
  try {
    return Number(localStorage.getItem(ACTIVITY_KEY)) || Date.now()
  } catch {
    return Date.now()
  }
}

export function markActivity(at = Date.now()): void {
  try {
    localStorage.setItem(ACTIVITY_KEY, String(at))
  } catch {
    /* private mode: this tab only */
  }
}

export { setSignOutReason, takeSignOutReason, type SignOutReason } from './signOutReason'
