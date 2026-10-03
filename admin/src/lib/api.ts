import { setSignOutReason } from './signOutReason'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

export { API_BASE }

export class ApiError extends Error {
  status: number
  code?: string
  detail?: unknown

  constructor(message: string, status: number, code?: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

// ── Token store ───────────────────────────────────────────────────────────
// Access tokens live 30 minutes; the refresh token (12h) renews them. Every
// authenticated call reads the freshest access token from here, so a refresh
// done by one request is picked up by all others.

const ACCESS_KEY = 'ghtrust_admin_token'
const REFRESH_KEY = 'ghtrust_admin_refresh'
type Listener = (access: string | null) => void
const listeners = new Set<Listener>()

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    /* storage unavailable (private mode): tokens stay in memory only */
  }
}

let memoryAccess = read(ACCESS_KEY)
let memoryRefresh = read(REFRESH_KEY)

export const tokenStore = {
  get access() {
    return memoryAccess
  },
  get refresh() {
    return memoryRefresh
  },
  set(access: string, refresh: string | null) {
    memoryAccess = access
    memoryRefresh = refresh
    write(ACCESS_KEY, access)
    write(REFRESH_KEY, refresh)
    listeners.forEach((l) => l(access))
  },
  clear() {
    memoryAccess = null
    memoryRefresh = null
    write(ACCESS_KEY, null)
    write(REFRESH_KEY, null)
    listeners.forEach((l) => l(null))
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  },
}

interface ParsedError {
  message: string
  code?: string
  detail?: unknown
}

async function parseError(res: Response): Promise<ParsedError> {
  try {
    const data = await res.json()
    const code = typeof data.code === 'string' ? data.code : undefined
    if (typeof data.detail === 'string') return { message: data.detail, code, detail: data }
    if (Array.isArray(data.detail)) {
      return {
        message: data.detail.map((d: { msg?: string }) => d.msg).join(', '),
        code,
        detail: data,
      }
    }
    return { message: JSON.stringify(data.detail ?? data), code, detail: data }
  } catch {
    return { message: res.statusText }
  }
}

// Single-flight: concurrent 401s share one refresh (the server rotates the
// refresh token, so two parallel refreshes would invalidate each other).
let refreshInFlight: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = tokenStore.refresh
  if (!refreshToken) return false
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/admin/auth/token/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
        if (!res.ok) {
          const err = await parseError(res)
          if (err.code === 'SESSION_IDLE_TIMEOUT') setSignOutReason('idle')
          return false
        }
        const data = (await res.json()) as { access_token: string; refresh_token: string }
        tokenStore.set(data.access_token, data.refresh_token)
        return true
      } catch {
        return false
      } finally {
        refreshInFlight = null
      }
    })()
  }
  return refreshInFlight
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
  retried = false,
): Promise<T> {
  const headers = new Headers(options.headers)
  if (!headers.has('Content-Type') && options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  // Callers pass the token they rendered with; prefer a newer refreshed one.
  const bearer = token ? (tokenStore.access ?? token) : null
  if (bearer) headers.set('Authorization', `Bearer ${bearer}`)

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const err = await parseError(res)
    if (res.status === 401 && bearer) {
      if (err.code === 'TOKEN_INVALID' && !retried && (await refreshAccessToken())) {
        return apiFetch<T>(path, options, tokenStore.access, true)
      }
      // Revoked session, deactivated account, idle too long, or refresh failed: sign out.
      if (err.code === 'SESSION_IDLE_TIMEOUT') setSignOutReason('idle')
      tokenStore.clear()
    }
    throw new ApiError(err.message, res.status, err.code, err.detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export interface OtpSentResponse {
  message: string
  phone_masked: string
  expires_in: number
  purpose: string
}

export interface StaffProfile {
  id: string
  full_name: string
  email: string
  phone: string
  status: string
  is_super_admin: boolean
  permissions: string[]
  job_title?: string | null
  avatar_color?: string | null
  role: {
    id: string
    name: string
    description?: string | null
    permissions?: string[]
    is_system?: boolean
  } | null
}

export interface StaffAuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  refresh_expires_in: number
  session_id: string
  staff: StaffProfile
}

export interface StaffProfileUpdate {
  full_name?: string
  job_title?: string
  avatar_color?: string
}

export const adminAuthApi = {
  updateMe: (token: string, changes: StaffProfileUpdate) =>
    apiFetch<StaffProfile>('/api/v1/admin/auth/me', { method: 'PATCH', body: JSON.stringify(changes) }, token),

  requestOtp: (phone: string) =>
    apiFetch<OtpSentResponse>('/api/v1/admin/auth/login/request-otp', {
      method: 'POST',
      body: JSON.stringify({ phone }),
    }),

  verifyOtp: (phone: string, otp: string) =>
    apiFetch<StaffAuthResponse>('/api/v1/admin/auth/login/verify-otp', {
      method: 'POST',
      body: JSON.stringify({ phone, otp }),
    }),

  resendOtp: (phone: string) =>
    apiFetch<OtpSentResponse>('/api/v1/admin/auth/login/resend-otp', {
      method: 'POST',
      body: JSON.stringify({ phone }),
    }),

  me: (token: string) =>
    apiFetch<StaffProfile>('/api/v1/admin/auth/me', {}, token),

  logout: (token: string) =>
    apiFetch<void>('/api/v1/admin/auth/logout', { method: 'POST' }, token),
}
