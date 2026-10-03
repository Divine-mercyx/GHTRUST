# Account deletion

Customers delete their own account, in the app or on the web. Nobody has to contact
support, and staff can't do it for them. Code: `backend/app/modules/auth/account_deletion.py`
(what happens) and `account_router.py` (the endpoints).

## Where customers find it

| Where | How |
|---|---|
| App | **Profile → Account → Delete account** (`mobile/src/app/(app)/delete-account.tsx`) |
| Web | **`https://<admin site>/delete-account`**, e.g. `https://ghtrust.vercel.app/delete-account` (`admin/src/pages/DeleteAccountPage.tsx`). Public page; give this URL to Google Play (Data safety → account deletion URL) |

The app flow: what will be deleted and kept, plus anything stopping it → **Continue** →
sign-in PIN + type `DELETE` → "Delete your account?" → done → signed out, the app forgets
the phone and returns to the welcome screen.

The web flow: phone number → SMS code → code + sign-in PIN + type `DELETE` → browser
confirm → done.

## API

| Method & path | Auth | What |
|---|---|---|
| `GET /api/v1/auth/me/account-deletion` | customer | `can_delete`, `blockers[]`, `will_delete[]`, `will_keep[]` |
| `DELETE /api/v1/auth/me` | customer | body `{pin, confirmation: "DELETE"}` → `{status: "deleted", deleted_at}` |
| `POST /api/v1/auth/account-deletion/request-otp` | none | body `{phone}`; same answer whether or not an account exists |
| `POST /api/v1/auth/account-deletion/confirm` | none | body `{phone, otp, pin, confirmation: "DELETE"}` |

Responses:

| Status | Code | When |
|---|---|---|
| 409 | `LOAN_OUTSTANDING` | active, overdue or written-off loan. Message: "Account deletion cannot be processed while you have an active loan or outstanding repayment balance. Please settle all pending dues before requesting deletion." |
| 409 | `APPLICATION_IN_PROGRESS` | an application between submitted and paid out |
| 409 | `WALLET_NOT_EMPTY` | wallet available or locked balance above zero |
| 409 | `WITHDRAWAL_PENDING` | a withdrawal still pending or processing |
| 409 | `OTHER_PRODUCTS` | any savings, investment, contribution or food-basket record (no customer flows yet) |
| 409 | `ACCOUNT_DELETION_BLOCKED` | more than one of the above; each listed in `errors` |
| 422 | `DELETE_CONFIRMATION_REQUIRED` | `confirmation` isn't `DELETE` |
| 400/401 | PIN codes | wrong PIN (5 wrong ends the session, as everywhere) |
| 400 | `OTP_INVALID` / `OTP_EXPIRED` | web: wrong or old code |
| 401 | `SESSION_REVOKED` / `ACCOUNT_INACTIVE` | already deleted (e.g. a retry after a timeout) |
| 429 | `RATE_LIMITED` | 10 deletion attempts an hour per customer; web uses the sign-in limits |

## Security

- The account is the signed-in one (app) or the one the phone number and its code belong
  to (web). No customer or account id is ever read from the request.
- Re-authentication: the sign-in PIN in both flows, plus an SMS code on the web. PIN attempt
  limits apply.
- Sessions: every session is revoked. Each request checks its session, so existing
  access tokens stop working at once; refresh tokens are refused; push tokens are cleared;
  trusted phones are forgotten, so PIN sign-in can't come back.
- CSRF: not applicable. The endpoints authenticate with a bearer token or the code + PIN in
  the body, never a cookie.
- Logs name only the customer id (`account_deleted`, `kept_identity`), never personal data.
- Idempotent: the work is one database transaction, after a row lock and a re-check. A
  retry after a timeout is refused by authentication, and the app treats that as "deleted".

## What happens to the data

The customer row is **kept** with status `deleted` and `deleted_at`, because loans, the
ledger and payments reference it. Personal data in it is scrubbed.

**Deleted**

| Data | Where |
|---|---|
| Sessions revoked, push tokens cleared | `auth_sessions` |
| Trusted phones, sign-in approvals | `customer_devices`, `device_approvals` |
| Face-check scores | `selfie_attempts` |
| Notifications | `notifications` |
| Unfinished applications (drafts) and their guarantors, collateral, documents and files | `loan_applications` (status draft), `application_*`, `uploads/loan_applications/<id>` |
| Legacy drafts | `loan_drafts` |
| Profile photo, BVN photo, PINs, email, address, state/LGA, other phone, gender, BVN enrolment details, payout account, transfer recipient | columns on `customers` |
| Phone number | replaced with `deleted-<random>`, so the number can be used again |
| Support message text | `support_messages.body`, `support_tickets.message/reply/device_name` → "[Removed …]" |

**Kept**

| Data | Why |
|---|---|
| Loans, schedules, repayments | Financial records. The Privacy Policy says financial records are kept for at least 5 years after the relationship ends |
| Wallet (empty), ledger journals and entries, payment transactions, withdrawals, disbursements | Same |
| Submitted, approved, rejected or withdrawn applications: the form (employment, income, next of kin), guarantors and collateral, documents, workflow decisions and audit trail | Credit decisions and the evidence behind them. Guarantor and next-of-kin details are other people's data held for the same loan record |
| Raw payment-provider payloads (`payment_transactions.raw_payload`, webhook records) | They can contain the payer's name and account number; part of the financial record |
| Legal acceptances, loan offers and signed agreements | Proof of consent to the terms that govern the kept records |
| Support ticket reference, category, status and dates | Complaint handling statistics; the text is removed |
| Revoked session rows (device name, IP, times) | Security and fraud investigation |
| On the customer row: BVN, first and last name, date of birth, account number, branch, dedicated account number | Only when financial records above exist, so they still identify a person for the retention period. With no loan, application or payment ever, these are scrubbed too (BVN replaced with `X` + 10 random digits) |

A BVN kept this way can't open a new account (`409 ACCOUNT_CLOSED`); the customer has to
contact the bank. A BVN that was scrubbed can sign up again as a new customer.

## Third parties

| Service | What it holds | What happens |
|---|---|---|
| Payment provider (Monnify / Stanbic) | Reserved (dedicated) account for wallet funding | **Automated**: deactivated after the deletion (`deactivate_reserved_account`). Failures are logged (`account_deletion_reserved_account_failed`) and don't undo the deletion. **Check the Monnify call on the sandbox before relying on it.** |
| Paystack / Zest | Paystack dedicated account; Zest uses short-lived accounts | **Manual**: `account_deletion_reserved_account_manual` is logged; operations deactivate it in the provider's dashboard |
| Dojah | BVN lookups and face checks already made | **Not automated**: no deletion API. Dojah keeps its records under its own legal duties |
| Termii | SMS delivery logs | **Not automated**: no deletion API |
| Expo push | Delivery receipts only | Tokens are deleted on our side; nothing to delete there |
| Sentry (if enabled) | Error reports may include a customer id | Not deleted; set data scrubbing and retention in Sentry |
| Credit bureaus | Reported loans | Not deleted: reporting is a legal duty for the retention period |

## Operations

- Inbound transfers to a deleted customer's dedicated account (before the provider
  deactivates it) still credit their wallet record. Refund them manually.
- No purge job yet: records kept for retention aren't removed automatically after
  5 years. Add one once compliance confirms the periods.
- The admin portal shows deleted customers with status `deleted` and the scrubbed name.

## Known limitations and items for compliance review

- **Retention periods**: the 5-year figure comes from the Privacy Policy (marked DRAFT). Have
  the compliance officer confirm it, and whether rejected applications, complaint records
  and session IPs need the same period.
- **Legal text**: the Privacy Policy and Terms (`backend/app/modules/legal/documents.py`)
  now describe deletion; they are still DRAFT and need legal sign-off. Their version moved
  to 2026-10-02, so customers accept them again on next open.
- **Store review**: the in-app and web flows meet Apple's and Google's requirements
  (self-service, in-app, a web URL, no need to contact support). They aren't verified until
  the stores review the app. Google Play also needs the URL entered in the Data safety form.
