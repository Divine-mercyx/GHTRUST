# GH Trust customer app

Expo (SDK 57) / React Native / TypeScript. Expo Router, TanStack Query, generated API types.

**v1 scope — loans:** BVN sign-up, phone + OTP sign-in, app lock (Face ID / fingerprint /
passcode), loan products, the application wizard (driven by each product's
`workflow_steps`), document upload, application tracking with re-upload of rejected
documents, loan detail + schedule, and — when the server enables the wallet — adding
money and repaying in-app. The API contract is in `docs/mobile-app-handoff.md`.

## Run it

You need Node 20+ and, for a phone, the **Expo Go** app.

**1. Start an API.** Either the real backend (`backend/`, port 8000, needs Postgres + Redis),
or the self-contained dev API — no Docker, every provider mocked, OTP always `123456`:

```bash
python backend/scripts/dev_server.py --wallet
```

Both use port 8000 and listen on `0.0.0.0`, so a phone on the same network (or on this
computer's hotspot) can reach them. Run only one at a time. For the real backend:

```bash
cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Without `--host 0.0.0.0` the backend only accepts connections from this computer and the
phone shows "We couldn't connect to GH Trust".

**2. Start the app:**

```bash
npm --prefix mobile install
```

```bash
npm --prefix mobile start
```

Scan the QR code with Expo Go (same Wi-Fi as this computer), or press `w` for a browser
preview. The app finds the API on the machine running Metro automatically.

Dev helpers (against `dev_server.py`):

- staff login for approving applications in the admin portal: phone `08000000001`, OTP `123456`
- credit a customer's wallet as if they'd made a bank transfer:
  `python backend/scripts/dev_credit_wallet.py <wallet account number> <amount>`

## Scripts

| | |
|---|---|
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint (Expo config) |
| `npm run gen:api` | regenerate `src/api/schema.d.ts` from the backend's OpenAPI spec — run after any API change |

## Layout

```
src/
  app/            routes (Expo Router): (auth) sign-up/in, unlock, (app) tabs + screens
  api/            HTTP client (refresh, idempotency, errors), endpoints, generated types
  auth/           session lifecycle, secure storage, app lock, device info
  features/apply/ the application wizard: page config, draft/validation, pages
  components/     design-system primitives (Button, Field, Card, Screen, …)
  lib/            formatting, status copy, queries
  theme/          tokens — every colour, size and font comes from here
```

## Security notes

- The refresh token lives in the Keychain / Keystore (`expo-secure-store`,
  this-device-only); the access token only in memory. Web previews keep both in memory.
- A saved session opens behind the device's biometrics/passcode and re-locks after
  5 minutes in the background.
- Money-moving calls carry an `Idempotency-Key` that is reused for retries of the same
  action, so a flaky network can never pay twice.
- BVNs and phone numbers are never put in routes or URLs.
- Android backups are disabled (`allowBackup: false`).

## Before the first store release

- Replace the placeholder app icon and splash image in `assets/images/` with the brand logo.
- Confirm the bundle/package ID in `app.json` (`ng.ghtrust.app`) — it can't change after publishing.
- Set `EXPO_PUBLIC_API_URL` for staging/production builds, and the store URLs
  (`EXPO_PUBLIC_IOS_STORE_URL`, `EXPO_PUBLIC_ANDROID_STORE_URL`) for the forced-update screen.
- Build with EAS: `npx eas-cli@latest build` (no Mac needed for iOS).
