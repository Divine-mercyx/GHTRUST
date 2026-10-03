// Why the staff member was signed out, shown once on the login page.
const REASON_KEY = 'ghtrust_admin_signout_reason'

export type SignOutReason = 'idle'

export function setSignOutReason(reason: SignOutReason): void {
  try {
    sessionStorage.setItem(REASON_KEY, reason)
  } catch {
    /* ignore */
  }
}

export function takeSignOutReason(): SignOutReason | null {
  try {
    const reason = sessionStorage.getItem(REASON_KEY)
    sessionStorage.removeItem(REASON_KEY)
    return reason === 'idle' ? reason : null
  } catch {
    return null
  }
}
