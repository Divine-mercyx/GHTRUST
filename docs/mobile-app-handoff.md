# GH Trust mobile app — API & design handoff

For the team building the customer mobile app. The app itself lives in `mobile/`
(Expo, see `mobile/README.md`) and implements everything below for v1. The Next.js
customer screens in `src/` were the original visual reference. All data contracts
come from the live API.

**The API contract is the OpenAPI spec**: `GET {API}/openapi.json` (browse at
`{API}/docs`) on any environment with `ENABLE_API_DOCS=true`. Generate your typed
client from it rather than hand-writing request types.

## Scope

**v1 (launch): loans only.** Register → apply → upload documents → track
application → view loan & schedule → repay. The backend lets loans run without
wallet funding, and `GET /app/config` reports which optional modules are enabled
(`features`), so the app can hide what isn't live.

**v2:** wallet (fund / withdraw), savings, investments, group thrift (Ajo), food
basket. Savings/investments/contributions/food-basket *write* endpoints return
501 until those modules are finished.

## Brand

| Token | Hex | Use |
|---|---|---|
| Navy | `#1B2F6B` | Primary, headers, body text |
| Cyan | `#2FA4D7` | Accents, primary CTAs, progress |
| Mint | `#E9F8F9` | Light backgrounds |
| Surface | `#F4F7FB` | App background |
| Surface (nav) | `#EEF2F9` | Navigation background |
| Success | `#00A86B` | Active / completed / paid |
| Warning | `#E5AF59` | Pending / due soon |
| Error | `#CF2E2E` | Failed / overdue / rejected |
| Gold | `#B58838` | Premium accents |

Typeface **Montserrat** (400–800), Inter as fallback. Cards: soft navy-tinted
shadow (`0 1px 3px rgba(27,47,107,.06), 0 8px 24px rgba(27,47,107,.06)`).

## Screen inventory (from the prototype) → API

| Screen | v | Endpoints |
|---|---|---|
| Bank picker + account-name check | 1 | `GET /banks`, `POST /banks/resolve` |
| Onboarding: BVN entry | 1 | `POST /auth/register/bvn` |
| OTP verify (register / login) | 1 | `POST /auth/register/verify-otp`, `POST /auth/login/request-otp`, `POST /auth/login/verify-otp`, `…/resend-otp` |
| Home / dashboard (active loans, drafts, quick actions) | 1 | `GET /auth/me`, `GET /loans/me/loans`, `GET /loans/me/applications?status=draft` |
| Loan products | 1 | `GET /loans/products` |
| Apply wizard | 1 | see *Apply flow* below |
| Application history & status | 1 | `GET /loans/me/applications`, `GET /loans/me/applications/{id}` |
| Loan detail + repayment schedule | 1 | `GET /loans/me/loans/{id}` |
| Repay | 1 | `POST /loans/me/loans/{id}/repayments` (wallet) |
| Profile & signed-in devices | 1 | `GET /auth/me`, `GET /auth/sessions`, `DELETE /auth/sessions/{id}`, `POST /auth/logout`, `POST /auth/logout-all` |
| Wallet (balance, add money) | 1 (when `features.wallet`) | `GET /wallet`, `POST /wallet/fund` (Zest only, see *Wallet*) |
| Withdraw, payout account | 2 | `GET /wallet`, `POST /wallet/fund`, `POST /wallet/withdraw`, `POST /wallet/payout-account` |
| Savings / Investments / Group thrift | 2 | `/savings/*`, `/investments/*`, `/contributions/*` |
| Notifications, transactions | 2 | not built server-side yet |

## Every request

| Header | When | Why |
|---|---|---|
| `Authorization: Bearer <access_token>` | authenticated calls | |
| `X-App-Platform: ios\|android` + `X-App-Version: 1.2.0` | **always** | Below the minimum → `426 APP_UPDATE_REQUIRED` |
| `Idempotency-Key: <8–64 chars [A-Za-z0-9_-]>` | every POST/PATCH/DELETE you might retry; **required** on `/wallet/withdraw` and `/loans/me/loans/{id}/repayments` | A retry with the same key replays the original response (`Idempotent-Replayed: true`) instead of acting twice. Generate one UUID per user action, reuse it for that action's retries |
| `X-Request-ID` (optional) | any | Echoed back; quote it in bug reports — it's on every server log line |

On launch and on resume call `GET /app/config?platform=android&version=1.2.0`.
If `update_required`, block and link to the store; if `maintenance.enabled`, show
`maintenance.message`. This endpoint is never gated.

## Auth & sessions

Passwordless: BVN + SMS OTP to register, phone + OTP to sign in.

OTP verify returns `access_token` (15 min), `refresh_token` (30 days),
`expires_in`, `refresh_expires_in`, `session_id`, and the customer profile. Send
`device: { device_id, device_name, platform, app_version }` with every OTP verify;
`device_id` should be a stable per-install ID — signing in again on the same
device replaces its previous session.

- Store the refresh token in Keychain (iOS) / Keystore-backed storage (Android).
- On `401` with `code: TOKEN_INVALID`, call `POST /auth/token/refresh` with the
  refresh token, **store the new refresh token** (it rotates every time), retry
  the request once.
- **Refresh single-flight**: at most one refresh in flight; other requests wait
  for it. Presenting an already-used refresh token outside a 30 s grace window is
  treated as theft and signs the device out (`REFRESH_TOKEN_REUSED`).
- `SESSION_REVOKED` / `ACCOUNT_INACTIVE` / `REFRESH_TOKEN_*` → go to sign-in.

## Apply flow

1. `GET /loans/products` → per product: `workflow_steps` (the wizard steps, e.g.
   `product_selection → universal_form → business_details → guarantor_collateral →
   documents → review_submit`), `required_document_types`,
   `repayment_cadence_options`, pricing. Drive the wizard from this; don't hard-code.
2. `POST /loans/me/applications` `{product_code, channel: "mobile"}` → draft, pre-filled from the BVN profile.
3. `PATCH /loans/me/applications/{id}` per step with `universal_form`,
   `product_data`, `guarantors`, `collaterals`. Partial updates merge.
   - **Bank picker must supply `bank_code`** plus `bank_account_number` (10 digits) —
     without it the loan cannot be disbursed. Codes are specific to the active payment
     rail, so take them from `GET /banks` (never hard-code a list). Then call
     `POST /banks/resolve {bank_code, account_number}` and show the returned
     `account_name` for the customer to confirm; store it as `bank_account_name`.
     Resolve is rate-limited per customer (10/min); `422 BANK_ACCOUNT_UNVERIFIED`
     means the details didn't match an account.
   - Send the tenure as `product_data.tenure_months` (integer).
4. `POST /loans/me/applications/{id}/documents/{document_type}` (multipart
   `file`): PDF/JPG/PNG, ≤ 10 MB. Content is checked, not just the extension —
   compress camera photos to JPEG before upload.
5. `POST /loans/me/applications/{id}/submit`. `422 APPLICATION_INCOMPLETE` lists
   what's missing in `errors[]` — map them back to wizard steps.

Statuses you'll see: `draft → submitted → under_review → approved →
ready_to_disburse → disbursed`, or `rejected` (reason in the detail view).

**After submission** a customer can replace only a document staff **rejected**
(`documents[].status == "rejected"`, reason in `rejection_note`), while the application is
`submitted`, `under_review` or `documents_incomplete` — same upload endpoint. Anything
else returns `409 APPLICATION_NOT_EDITABLE`. The replacement goes back to staff review.

## Loans & repayments

`GET /loans/me/loans/{id}` returns the loan with `schedule[]` (per installment:
`due_date`, `amount`, `amount_due`, `status` = `pending|partial|paid|overdue`) and
`repayments[]`. `outstanding` is what the customer still owes (principal +
interest); `monthly_payment` is the regular installment for the loan's cadence.

Repay: `POST /loans/me/loans/{id}/repayments` `{amount}` with an
`Idempotency-Key`. Paid from the wallet; `409 INSUFFICIENT_FUNDS` if the balance
is short. Payments go to the oldest installment first, interest before principal.
When `features.wallet` is off, don't offer in-app repayment: show the amount due
and how to pay at the branch (staff record those repayments).

## Wallet

`GET /wallet` → `funding_mode` says how money gets in:

- `permanent_dva` (Monnify, Stanbic, Paystack): the customer's own account
  `dva_account_number` / `dva_bank_name`. Any transfer to it credits the wallet. Show it
  with copy buttons; there is nothing to call.
- `on_demand_dynamic` (Zest): `POST /wallet/fund {amount}` with an `Idempotency-Key`
  returns a one-off account valid for `expires_in_minutes`.

## Errors

Every error has the same shape:

```json
{ "detail": "Human-readable message", "code": "OTP_INVALID", "errors": [], "request_id": "…" }
```

Branch on `code`, show `detail`. Codes you should handle explicitly:

| Code | Meaning / action |
|---|---|
| `OTP_INVALID`, `OTP_EXPIRED`, `OTP_ATTEMPTS_EXCEEDED` | OTP screen states |
| `RATE_LIMITED` (429) | back off using `Retry-After` |
| `BVN_NOT_FOUND`, `KYC_UNAVAILABLE`, `ACCOUNT_EXISTS`, `ACCOUNT_RESTRICTED` | onboarding |
| `SMS_UNAVAILABLE` (503) | "couldn't send code, try again" |
| `TOKEN_INVALID` | refresh and retry |
| `SESSION_REVOKED`, `ACCOUNT_INACTIVE`, `REFRESH_TOKEN_INVALID`, `REFRESH_TOKEN_REUSED` | sign in again |
| `APP_UPDATE_REQUIRED` (426), `MAINTENANCE_MODE` (503) | blocking screens |
| `IDEMPOTENCY_IN_PROGRESS` (409) | retry after `Retry-After` with the same key |
| `IDEMPOTENCY_KEY_REUSED` (422) | bug: new action needs a new key |
| `APPLICATION_INCOMPLETE`, `APPLICATION_NOT_EDITABLE`, `DOCUMENT_INVALID`, `DOCUMENT_TYPE_NOT_ALLOWED` | apply flow |
| `INSUFFICIENT_FUNDS`, `LOAN_NOT_REPAYABLE` | repayment |
| `VALIDATION_ERROR` (422) | `detail` is a list of `{loc, msg}` |

## Lists

Customer list endpoints return `{items, total, limit, offset}`; page with
`?limit=&offset=`.
