# Session timeouts

## Customers (mobile app)

**Profile → Security → Lock app**: Immediately, after 1, 5 (default), 15 or 30 minutes.
There's no "never". The choice is stored on the phone (secure storage) and cleared when the
phone is forgotten (account deleted, "Not you?").

- **Away from the app** for longer than the choice → the app locks and asks for the sign-in
  PIN, or Face ID / fingerprint if switched on. "Immediately" locks on every return.
- **Open but untouched** for the same time (at least 5 minutes, because typing isn't counted
  as a touch) → locks too.
- **The app's own flows don't lock it**: the camera, photo and document pickers, and
  permission prompts pause the lock (`withLockPaused` in `mobile/src/auth/lockPolicy.ts`).
- **App switcher**: while the app isn't in front, a navy cover with the GH Trust mark hides
  the screen (`PrivacyCover`). Reliable on iOS. On Android the system may take its snapshot
  before the cover draws; hiding it fully needs `FLAG_SECURE`, a native change that also
  blocks screenshots (not done).
- Locking keeps the customer signed in; the server session (30 days) is unchanged. Locking
  closes the open screen; loan applications are saved as drafts on the server.

## Staff (admin portals)

**Settings → Security** (super admin): one timeout for everyone, 5 to 60 minutes, default 30.
**Profile** (or Settings → Session timeout in the Next.js portal): each staff member may pick a
shorter one for themselves, never longer.

- Enforced by the server on every staff request and on token refresh
  (`backend/app/modules/admin/security_settings.py`, `SessionService.end_if_idle`). An idle
  session is revoked; the response is `401 SESSION_IDLE_TIMEOUT`.
- Only real activity counts: the portal reports clicks, typing, scrolling and touch to
  `POST /api/v1/admin/auth/activity` (every 30 seconds at most, plus a trailing report).
  Background polling and token refreshes don't restart the clock.
- A minute before the limit: "Still there?" with a countdown and **Stay signed in**. At the
  limit: signed out, and the login page says why. Activity in one tab keeps the others open.
- Changing the timeout records who changed it and when (shown on the card), and logs
  `security_setting_changed` with the old and new value. There's no general staff audit
  table yet; this is the record.
- `STAFF_SESSION_IDLE_MINUTES` (default 30) only applies until a super admin sets a value.

## API

| Method & path | Who | What |
|---|---|---|
| `GET /api/v1/admin/settings/security` | any staff | organisation timeout, my timeout, what applies to me, who last changed it |
| `PUT /api/v1/admin/settings/security` | super admin | `{staff_idle_minutes: 5-60}` |
| `PUT /api/v1/admin/auth/me/session-timeout` | any staff | `{minutes: 5-60 or null}`, not above the organisation's |
| `POST /api/v1/admin/auth/activity` | any staff | records activity; returns the limit and when it runs out |
