# Stanbic APIs: GH Trust mapping and status

All OpenAPI files are in `backend/app/integrations/stanbic/specs/`. Everything Stanbic-specific
switches on only with `PAYMENT_PROVIDER=stanbic`; Monnify stays the default until then.

## Wallet top-ups: Fundable Virtual ID

**This is Stanbic's virtual account product** (files `fvid-*.json`, `nuban-generator_3.0.0.json`).
It works differently from Monnify: there is **no "create account" call**.

1. Stanbic gives GH Trust a **4-digit prefix** (`STANBIC_FVID_PREFIX`). Ours is **5960**
   (sandbox; confirm the live one). The generator gives e.g. 596000001 -> **5960000018**.
2. Each customer's account number = prefix + a 5-digit serial we allocate + the check digit from
   Stanbic's **Nuban Generator** (bank code 221). One prefix = 99,999 customers.
3. A transfer to that number from any bank lands in GH Trust's pooled wallet account at Stanbic.
4. **Transaction history by prefix** lists every payment (other banks and Stanbic-to-Stanbic are
   separate lists). Each record has a `checksum` and `sessionId`.
5. The **Checksum Validator** confirms a record is genuine (`isValid`, amount, account) before
   we credit anything.

We use **Fundable Virtual ID 3.0.0** (files `fvid3-*.json`). Verified against the sandbox (Oct 2026):

- Addresses are short paths on `STANBIC_FVID_BASE_URL`: `POST /validator`, `GET /history`
  (other banks), `GET /stanbic-to-stanbic`, `POST /generate` (Nuban Generator). The 2.1.x paths
  (`/checksum-validator/validator`, `/history/prefix-id/...`) answer "no valid subscription".
- Every call needs **both** the OAuth token (`mynativeoauthprovider/oauth2/token`, scope `access`)
  **and** the `Client-Id` / `Client-Secret` headers.
- A made-up payment is refused by the validator: code 99, "Session ID Does not Exist".
- **Stanbic's `GET /va-transaction-history/` ignored `prefixId`** and returned other clients'
  payments. Stanbic fixed the filter (Oct 20: our prefix returns only ours), **but any prefix can
  still be requested** with our keys (5700 returned another client's payment), so the prefix isn't
  tied to the client. Reported again. We filter every record to our prefix in our code.

Code: `backend/app/modules/payments/stanbic_fvid.py`.

- Account numbers are allocated at sign-up (`WalletService.provision_payment_rail`), stored in
  `stanbic_virtual_accounts` (migration `027`). A failure leaves the customer signed in, and the
  `retry_wallet_accounts` job finishes it.
- Wallets are credited by polling: the `credit_stanbic_payments` job runs every 2 minutes, reads
  today's and yesterday's history, validates each checksum, and credits once per `sessionId`. A
  forged or mismatched record is rejected; one Stanbic can't confirm right now is retried next run;
  a payment to an unknown number is logged (`stanbic_fvid_unknown_account`) and not credited.
- **Endpoints Stanbic calls** (format: Stanbic's "Fundable Wallet API Specification" v1.0.4 PDF):
  - Name Enquiry: `POST /api/v1/webhooks/stanbic/virtual-id/name-enquiry`
    `{requestId, accountNumber}` -> `{accountNumber, accountName, bvn, responseCode "00"|"07"}`.
    Deleted or inactive customers answer 07 "Invalid Account".
  - Transaction Notification: `POST /api/v1/webhooks/stanbic/virtual-id/transaction/notification`,
    a list of payments; each answered `Successful`, `Duplicate Transaction`, `Invalid Checksum`,
    `Invalid Amount`, `Invalid Account Number`, `Invalid Request` or `System malfunction` (Stanbic
    couldn't confirm it right now); overall 00 all, 02 some, 99 none. Each is confirmed with the
    checksum validator (same account and amount) before crediting; sessionId is the duplicate key.
  - Both require headers `provider_id` / `provider_secret` (`STANBIC_FVID_PROVIDER_ID` /
    `STANBIC_FVID_PROVIDER_SECRET`, chosen by us, given to Stanbic privately). Without them: 503.
  - The wallet is credited the notified `amount`. Stanbic's charges (`bankCharge`, `adminFee`, VAT,
    `amountNetChargesAndVat`) are stored on the payment for reconciliation. **Stanbic confirmed
    (Oct 30): GH Trust bears the charges**, and the net amount (`amountNetChargesAndVat`) settles
    into our pooled account at **end of day**, not per payment. So customers are credited the gross
    amount at once, the daily settlement is lower by GH Trust's charges, and same-day withdrawals
    are paid before that day's settlement arrives: the business needs float in the account.
  - Stanbic retries an unsuccessful notification **4 times** (interval not given). Safe: each
    payment is credited once per `sessionId`.
  - Stanbic calls from **no fixed IP addresses**, so there's no IP allow-list; the
    `provider_id` / `provider_secret` headers are the check.
  - The callback URLs and credentials are registered through Stanbic's **onboarding form** (link
    in the Slack thread), not by chat.
- Polling stays as the safety net for a missed notification.

## Transfers out (withdrawals and loan payouts)

- Single transfer ("NPS" in the portal docs; Stanbic's team calls it NIP, same API), transfer
  status and name enquiry: `portal_sandbox.py`, `StanbicClient`.
- **Bank codes:** Stanbic routes on 6-digit institution codes; the app and older saved accounts
  use 3-digit CBN codes. `bank_codes.py` converts using Stanbic's **Bank List**, which gives both
  codes per bank. Unknown codes are refused, never guessed. With Stanbic as the rail, the app's
  bank picker shows Stanbic's list.
- **Narration:** a withdrawal's optional customer note (30 characters: letters, digits, spaces
  and `. , ' & ( ) / -`) is sent as `destAcctNarration`; `srcAcctNarration` stays "GH Trust wallet
  withdrawal". 30 is our limit until Stanbic confirms theirs.

## Other products

| Product | File | Use |
|---|---|---|
| Account Opening 2.0 + status | `account-opening_2.0.0.json`, `account-opening-status_1.0.0.json` | Full bank accounts (CASA). **Not** for the wallet |
| Current Account Opening | `current-account-opening_1.0.0.json` | Current account for an existing CIF. **Not** for the wallet |
| Transaction History | `transaction-history-service_1.0.0.json` | Settlement account statement |
| Credit Check | `credit-check_2.0.0.json` | Optional (`STANBIC_CREDIT_CHECK_ENABLED`) |
| Nuban Generator (Bank-Test) | `nuban-generator_3.0.0.json` | Check digit for our virtual account numbers |

## Response codes (confirmed by Stanbic)

00 successful, 99 failed, 55 and 56 pending. A repeated `clientRefId` is not reprocessed. Our code:
pending and "duplicate" replies are never treated as failures (no refund), transfers are never
auto-retried, and unknown codes wait for the status check.

## Status of our sandbox access (Oct 20, 2026)

- Client ID profiled. Bank List, Name Enquiry, Nuban Generator (prefix 5960), Fundable Virtual ID 3.0
  history and checksum validator all work.
- Test account (UAT): **9202314303** (APIC TEST DUMMY ACCOUNT). Accepted as the NPS transfer source.
- VA transaction history: subscribe to **Transaction History (VA) 3.0.0** (product 14378) on the portal.

## Answered by Stanbic (Oct 30, 2026)

- **Callback URLs:** register them on Stanbic's onboarding form.
- **Test payment into a 5960 account:** we share a virtual account number and Stanbic credits it.
  Use a number from the **staging** server (a tester signs up there), never a laptop's.
- **IPs:** Stanbic uses no fixed IPs either way, so there's nothing to allow-list on our side and no
  fixed outbound IP needed on Railway.
- **Retries:** 4 for an unsuccessful notification.
- **Charges:** borne by GH Trust; the net amount settles into our pool at end of day.

## Still needed from Stanbic

1. A second test account (with bank code) to complete a successful transfer, and whether
   9202314303 holds test funds (asked twice).
2. Who receives the `provider_id` / `provider_secret`, privately.
3. Is the end-of-day settlement one lump sum, and is there a report or statement to reconcile it against?
4. Fix: VA history must only return the calling client's prefix.
5. Live prefix, live URLs and live keys (into Railway, never by email or chat).
6. Maximum length and allowed characters for `srcAcctNarration` / `destAcctNarration` on
   transfers (we allow 30).

## Our next steps

1. Get the staging server live (Railway billing, then `docs/staging-stanbic.md`).
2. Fill Stanbic's onboarding form with the staging callback URLs.
3. Sign up a tester on staging and send Stanbic the 5960 number to credit.
4. Agree float for same-day withdrawals with the business.

## Staging server for UAT

Set-up, variables and the end-to-end check (`scripts/stanbic_check.py`): `docs/staging-stanbic.md`.

## Sandbox env (`backend/.env`, not Railway)

```env
STANBIC_MOCK=false
STANBIC_PORTAL_SANDBOX=true
STANBIC_CLIENT_ID=
STANBIC_CLIENT_SECRET=
STANBIC_FVID_PREFIX=5960             # from Stanbic (sandbox)
STANBIC_FVID_PROVIDER_ID=            # ours: what Stanbic sends to call us
STANBIC_FVID_PROVIDER_SECRET=        # ours: 32+ random characters, shared privately
STANBIC_SETTLEMENT_ACCOUNT_NUMBER=   # from Stanbic: source for NPS transfers
# PAYMENT_PROVIDER=stanbic           # only when testing the Stanbic rail locally
```

Subscribe each product in the portal (Default Plan) with the same app ("GH Trust Sandbox").
