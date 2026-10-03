# Go-live runbook

How to take GH Trust from the test setup to live customers. Everything here is checked
against what the code enforces: the API **refuses to start in production** if any required
setting below is missing or unsafe (`production_config_errors` in
`backend/app/core/config.py`), and release app builds fail without a real API address
(`mobile/app.config.js`).

## What's ready and what's blocking

**Ready (verified before this runbook was written):** backend lint and all tests, migrations up to
`022` apply, match the models and roll back cleanly; the Docker image builds and refuses an
insecure production config; the admin portal (Next.js) and the legacy Vite admin build;
the mobile app typechecks, lints, passes its tests, and its API types match the backend.

**Blocking go-live (needs you):**

| # | Item | Why it blocks |
|---|---|---|
| 1 | Termii API key + approved sender ID | No SMS codes = nobody can sign up or sign in |
| 2 | Dojah App ID + secret key, funded wallet | BVN lookup and face check |
| 3 | Live payment provider keys + webhook secret (Monnify, Paystack, Stanbic or Zest) | Wallet funding, payouts, disbursement |
| 4 | A domain (e.g. `ghtrust.ng`) for the API and the admin portal | Staff sign-in cookie needs both on the same domain (below) |
| 5 | Brand icon and splash image | Store listings |
| 6 | Google Play Console and Apple Developer accounts | Publishing the app |

## 1. Services to run

Match `backend/docker-compose.prod.yml`. On Railway, that's five services in one project, one
project per environment (staging and production, never shared):

| Service | Source | Start command | Notes |
|---|---|---|---|
| Postgres | Railway Postgres | – | Turn on **daily backups** |
| Redis | Railway Redis | – | Sessions, OTPs, rate limits, task queue |
| **api** | `backend/Dockerfile` | the image's default | Healthcheck path `/api/v1/health/ready`. **Pre-deploy command: `alembic upgrade head && python scripts/seed.py`.** **Attach a volume at `/app/uploads`** |
| **worker** | same image | `celery -A app.core.celery_app.celery_app worker --loglevel=info` | Processes withdrawals, reconciliation, notifications |
| **beat** | same image | `celery -A app.core.celery_app.celery_app beat --loglevel=info` | Schedules the periodic jobs. Run **exactly one** |

Two things that fail silently if skipped:

- **The uploads volume.** Loan documents are written to disk in the api container. Without a
  volume at `/app/uploads`, **every redeploy deletes every uploaded document**. A volume
  also means the api runs as a single replica; before scaling out, move documents to object
  storage (S3 or Cloudflare R2).
- **worker and beat.** Without them the API looks healthy, but withdrawals are never paid
  out, payments aren't reconciled, and loan statuses (overdue) don't update.

## 2. Backend settings (api, worker and beat all need them)

Put them in a Railway **shared variable** group so all three services get the same values.
Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

| Setting | Production value |
|---|---|
| `APP_ENV` | `production` |
| `DEBUG` | `false` |
| `SECRET_KEY` | random, 32+ characters, **different from staging** |
| `DATABASE_URL` | the Railway Postgres URL as given (`postgresql://…` is converted for the async driver automatically; not localhost) |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Railway Redis URL (not localhost) |
| `CORS_ORIGINS` | the admin portal origin, `https://` only, e.g. `https://admin.ghtrust.ng` |
| `ENABLE_API_DOCS` | `false` |
| `UPLOAD_DIR` | `/app/uploads` (the volume) |
| `SMS_MOCK` / `SMS_PROVIDER` | `false` / `termii` |
| `TERMII_API_KEY`, `TERMII_SENDER_ID`, `TERMII_BASE_URL` | from the Termii dashboard; `TERMII_CHANNEL=dnd` |
| `DOJAH_MOCK` / `DOJAH_APP_ID` / `DOJAH_SECRET_KEY` | `false` / from Dojah |
| `DOJAH_MOCK_PHONE` | **empty** |
| `OTP_TEST_ECHO` | `false` (codes are never echoed in production anyway, but keep it off) |
| `PAYMENT_PROVIDER` | `monnify`, `paystack`, `stanbic` or `zest` |
| provider keys | e.g. Monnify: `MONNIFY_API_KEY`, `MONNIFY_SECRET_KEY`, `MONNIFY_CONTRACT_CODE`, `MONNIFY_MOCK=false`. The webhook secret is the provider's secret key, except Stanbic (`STANBIC_WEBHOOK_SECRET`) |
| `FEATURE_FLAGS` | `wallet` to launch with the wallet: loans are then **paid into the wallet** and customers withdraw to any bank. Empty for loans only (paid straight to the bank account in the application). Savings, investments, contributions and food basket are refused until they are built |
| `PUSH_MOCK` / `EXPO_PUSH_ACCESS_TOKEN` | `false` to send push notifications (worker + beat must run; the job sends every minute). The token is optional (Expo push security). Android also needs Firebase credentials in EAS, see section 6 |
| `SEED_SUPER_ADMIN_NAME`, `…_EMAIL`, `…_PHONE` | the first staff admin (see step 4) |
| `DEMO_PHONES`, `DEMO_OTP`, `DEMO_LOGIN_PIN`, `DEMO_TRANSACTION_PIN` | optional: the app-review account (below) |
| `SUPPORT_PHONE`, `SUPPORT_EMAIL`, `SUPPORT_WHATSAPP`, `SUPPORT_HOURS` | shown in the app's Help screen |
| `APP_MIN_VERSION_ANDROID` / `_IOS` | `1.0.0` at launch; raise to force an update |
| `SENTRY_DSN` | optional, recommended |
| `STAFF_SESSION_IDLE_MINUTES` | optional, default 30. After launch a super admin sets it in the portal (Settings → Security); see `docs/session-timeouts.md` |

If anything required is missing, the api logs the exact list and **does not start**. That's
deliberate; read the deploy log, fix the variables, redeploy.

**Demo account for app review.** Apple and Google need a login that works without a real
phone. Set `DEMO_PHONES` to a number you control (not a staff number), `DEMO_OTP` to a
6-digit code that isn't a pattern (not `000000` or `123456`), and optionally
`DEMO_LOGIN_PIN` / `DEMO_TRANSACTION_PIN`; then run `python scripts/seed.py`. That number
signs in with the fixed code (no SMS) as "Demo Customer", on any number of phones at
once. On the live system money can't leave a demo account and staff sign-in never
accepts the demo code. Give the number, code and PINs to the stores in the review notes.
Re-running the seed resets the PINs if a reviewer changed them.

Optional pilot tuning (defaults shown): `DOJAH_SELFIE_THRESHOLD=90`,
`DOJAH_LIVENESS_MIN_PROBABILITY=0.5`, `DOJAH_SELFIE_MAX_ATTEMPTS=3`. Adjust only with the
evidence on the admin **Onboarding** page.

## 3. Payment webhooks

In the provider's dashboard, set the webhook URL to the live API:

| Provider | Webhook URL |
|---|---|
| Monnify | `https://<api domain>/api/v1/webhooks/monnify` |
| Paystack | `https://<api domain>/api/v1/webhooks/paystack` |
| Stanbic | `https://<api domain>/api/v1/webhooks/stanbic` |
| Zest | `https://<api domain>/api/v1/webhooks/zest` |

Webhooks are signature-checked; a wrong secret means money arrives at the provider but the
wallet is never credited.

## 4. First deploy

1. Deploy **api**. The pre-deploy command migrates the database and seeds products and
   loan workflows (the seed never duplicates, so it's safe on every deploy).
2. The first staff admin (`SEED_SUPER_ADMIN_*`) and demo customers (`DEMO_PHONES`) are
   created by the API itself on every start, so they exist even without the seed. Change
   `SEED_SUPER_ADMIN_PHONE` and the next start moves that admin (matched by email) to the
   new number. If sign-in says "Staff account not found", look for
   `configured_accounts_failed` in the api log.
3. Deploy **worker** and **beat**.
4. Check `https://<api domain>/api/v1/health/ready` returns `{"status":"ready"}`.

## 5. Admin portal (Next.js, repo root)

- Set `NEXT_PUBLIC_API_URL=https://<api domain>` (`.env.production` defaults to the Railway API), build with `npm run build`, serve with `npm run start`.
- **Host it on the same domain as the API**, e.g. `admin.ghtrust.ng` and `api.ghtrust.ng`.
  The staff session cookie is `Secure` and `SameSite=Strict`, so browsers only send it
  between sites on the same registrable domain. With `*.vercel.app` and `*.up.railway.app`
  staff would be signed out on every refresh.
- Add the portal's origin to `CORS_ORIGINS` on the API.

## 6. Mobile app

Builds and updates already point at `https://ghtrust-production.up.railway.app`
(`mobile/eas.json`, `mobile/.env.production`). Once the API moves to its own domain, set it
with the first command below, which overrides both.

```bash
cd mobile
npx eas-cli@latest env:create --environment production --name EXPO_PUBLIC_API_URL --value https://<api domain> --visibility plaintext
npx eas-cli@latest env:create --environment production --name EXPO_PUBLIC_SENTRY_DSN --value <dsn> --visibility plaintext   # optional
npx eas-cli@latest build --profile production --platform all
npx eas-cli@latest submit --profile production --platform all
```

Launch through the stores' test tracks first: Play **internal testing → closed testing →
production**; iOS **TestFlight → review**. JavaScript-only fixes after that ship with
`npm run update:production` (see `mobile/README.md`).

### Push notifications on Android

Expo sends Android pushes through Firebase Cloud Messaging, so EAS needs your Firebase
project's credentials once:

1. Firebase console → create a project → add an Android app with package `ng.ghtrust.app`
   → download `google-services.json`.
2. Firebase → Project settings → Service accounts → generate a private key (JSON).
3. `npx eas-cli@latest credentials` → Android → production → Google Service Account → FCM V1
   → upload that key.
4. Put `google-services.json` in `mobile/` and set `"googleServicesFile": "./google-services.json"`
   under `android` in `app.json`, then build again.

In-app notifications work without any of this; push needs it.

### Account deletion URL (Google Play)

Play Console → App content → Data safety → account deletion: enter
`https://<admin site>/delete-account`. See `docs/account-deletion.md`.

## 7. Smoke test (staging first, then production)

On a real phone with the production build:

1. Sign up with a real BVN: SMS code arrives, face check passes, account opens, PINs set.
2. Admin portal: staff sign-in works and survives a page refresh (proves the cookie setup).
3. Apply for a small loan, upload documents; approve and disburse from the portal.
4. Fund the wallet with ₦100 by bank transfer: balance updates within minutes (proves webhooks).
5. Repay part of the loan; withdraw ₦100 to a bank account: it arrives (proves the worker).
6. Admin **Onboarding** page shows the sign-up and face check.

## 8. Rollback

| What broke | Do this |
|---|---|
| API deploy | Railway → the service → redeploy the previous deployment. Check the release's migrations first: additive ones (new tables, columns, indexes) leave the previous code working; anything that alters or drops needs the backup restore below |
| A bad migration | Restore the pre-deploy Postgres backup; don't run `alembic downgrade` on live data |
| App JavaScript | `npx eas-cli@latest update:republish` the previous update to the `production` channel |
| App native crash | Ship a fixed build; meanwhile raise `APP_MIN_VERSION_*` only once the fix is in the store |
| Emergency stop | `MAINTENANCE_MODE=true` on the API shows the maintenance screen in the app |

## 9. After launch

- Watch Sentry (crash-free sessions), the Onboarding page (drop-off, face-check pass rate)
  and Railway metrics for the first two weeks of the pilot.
- Verify a Postgres backup restores, once, on staging.
- Before scaling the api past one replica: move documents to object storage.
- An independent penetration test is recommended before the public launch
  (`docs/mobile-security-review.md`).
