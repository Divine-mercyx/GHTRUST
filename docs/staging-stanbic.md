# Staging server for Stanbic testing (UAT)

A separate Railway project that runs the same code as production, with **Stanbic's sandbox as
the payment rail**. Stanbic calls it during UAT; real customers never touch it. Production stays
on Monnify and is not changed.

Why separate: production refuses sandbox settings on purpose (`production_config_errors`), and
staging must never share production's database, Redis or secrets (`docs/go-live.md`, section 1).

## 1. Create the project (Railway dashboard, about 15 minutes)

1. **New Project → Deploy from GitHub repo** → `Divine-mercyx/GHTRUST`, branch `main`. Name the
   project `ghtrust-staging`. Set the service's **Root Directory** to `backend` (it builds
   `backend/Dockerfile`, like production). Rename the service `api`.
2. **+ New → Database → PostgreSQL**, and **+ New → Database → Redis**, in the same project.
3. **api** service settings:
   - Pre-deploy command: `alembic upgrade head && python scripts/seed.py`
   - Healthcheck path: `/api/v1/health/ready`
   - Volume mounted at `/app/uploads`
   - Networking → **Generate Domain**. Note it, e.g. `ghtrust-staging.up.railway.app`.
4. Duplicate **api** twice for the background jobs (same repo, root directory and variables):
   - **worker**, start command `celery -A app.core.celery_app.celery_app worker --loglevel=info`
   - **beat**, start command `celery -A app.core.celery_app.celery_app beat --loglevel=info`
     (exactly one; it runs the 2-minute Stanbic payment check)
   Neither needs a domain, volume or pre-deploy command.

## 2. Variables (Project Settings → Shared Variables, shared with api, worker and beat)

Type the secret values in Railway yourself; never paste them into chat or email.

| Variable | Staging value |
|---|---|
| `APP_ENV` | `staging` |
| `DEBUG` | `false` |
| `SECRET_KEY` | new random value (see below), **not** production's |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | `${{Redis.REDIS_URL}}` |
| `ENABLE_API_DOCS` | `true` (contract at `/docs` for testers) |
| `UPLOAD_DIR` | `/app/uploads` |
| `CORS_ORIGINS` | `http://localhost:5173` (the admin portal run locally against staging), plus any staging portal origin |
| `FEATURE_FLAGS` | `wallet,investments` |
| `SMS_MOCK` / `OTP_TEST_ECHO` | `true` / `true`: no texts, the code is shown in the app. For real texts like the live app: `false` / `false` with `SMS_PROVIDER=dojah`, `DOJAH_APP_ID`, `DOJAH_SECRET_KEY`, `DOJAH_SENDER_ID` |
| `DOJAH_MOCK` | `true`, or `false` with Dojah keys so any customer can sign up with their real BVN (each lookup is charged) |
| `DEMO_BVNS` | optional: made-up 11-digit BVNs testers can sign up with (no Dojah) |
| `DEMO_OTP` | 6 digits, needed with `DEMO_BVNS` |
| `PUSH_MOCK` | `true` |
| `MONNIFY_MOCK` | `true` (card top-ups stay on Monnify; mocked here) |
| `PAYMENT_PROVIDER` | `stanbic` |
| `STANBIC_MOCK` | `false` |
| `STANBIC_PORTAL_SANDBOX` | `true` |
| `STANBIC_CLIENT_ID` / `STANBIC_CLIENT_SECRET` | the "GH Trust Sandbox" app's keys (the **reset** secret) |
| `STANBIC_FVID_PREFIX` | `5960` |
| `STANBIC_SETTLEMENT_ACCOUNT_NUMBER` | `9202314303` |
| `STANBIC_FVID_PROVIDER_ID` / `STANBIC_FVID_PROVIDER_SECRET` | what Stanbic sends when it calls us. Use the same values as your `backend/.env` so the check below can test them; production gets its own later |
| `STANBIC_WEBHOOK_SECRET` | random value (the older generic `/webhooks/stanbic` endpoint) |
| `SEED_SUPER_ADMIN_NAME`, `…_EMAIL`, `…_PHONE` | optional: a staff login for the admin portal on staging |

Leave every `STANBIC_*_BASE_URL` unset: the defaults are Stanbic's sandbox.
Generate secrets with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Deploy api, then worker and beat. `https://<staging domain>/api/v1/health/ready` must return
`{"status":"ready"}`.

## 3. Check it (from your laptop, no money moves)

```bash
cd backend
python scripts/stanbic_check.py --api https://<staging domain>
```

Every line must say PASS: Stanbic
reachable with our keys, prefix 5960 working, and both endpoints answering Stanbic correctly (an
unknown number answers 07, a made-up payment is refused, a call without credentials is refused).
After a tester signs up on staging, add `--account <their 10-digit 5960 number>`: it must
answer 00 with their name.

To try the same thing on your laptop first: `python backend/scripts/dev_server.py --stanbic --port 8001`
(identity checks and SMS mocked, Stanbic real), then `--api http://127.0.0.1:8001`.

## 4. Give Stanbic (through their onboarding form)

- Name Enquiry URL: `https://<staging domain>/api/v1/webhooks/stanbic/virtual-id/name-enquiry`
- Transaction Notification URL: `https://<staging domain>/api/v1/webhooks/stanbic/virtual-id/transaction/notification`
- Credentials: `provider_id` / `provider_secret` (sent as request headers), **privately**, not in
  the shared Slack thread.
- The certificate is Railway's (Let's Encrypt), which their spec's "valid and recognised SSL
  certificate" rule accepts.
- No IP addresses either way: Stanbic doesn't use fixed IPs, so no allow-list and no Railway static IP.
- For the test payment: a 5960 account number from a tester who signed up **on staging**.

## 5. UAT run

1. A tester signs up on staging (app pointed at staging, below): they get a 5960 account number.
2. Stanbic (or a sandbox transfer) pays into it: the notification credits the wallet at once;
   the 2-minute check credits it otherwise. The admin portal shows the payment.
3. Withdraw to the second test account from Stanbic: NPS transfer, then status check.

Only one server should run the payment check for prefix 5960 (staging's beat). The local dev
server doesn't run it, but its numbers overlap staging's (both start at 5960000018), so don't
test payments against a laptop.

**The app against staging.** Release builds point at production. For testers, make a build whose
`EXPO_PUBLIC_API_URL` is the staging domain (an EAS `staging` environment and profile), or use a
development build with that address. Ask before building; it isn't set up yet.
