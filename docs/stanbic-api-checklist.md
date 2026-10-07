# Stanbic sandbox APIs — GH Trust mapping

All OpenAPI files we have are under `backend/app/integrations/stanbic/specs/`.

## Is **Current Account Opening** the wallet virtual account?

**No.** It is a different product from wallet **collection / dedicated VA** funding.

| Product | What it does | GH Trust use |
|--------|----------------|--------------|
| **Account Opening 2.0** | BVN/NIN onboarding → CIF + account async | Full KYC account creation |
| **Current Account Opening 1.0** | Opens a **current account for an existing `cifID`** (scheme/branch) | Second step after CIF exists — still a **real CASA**, not a per-customer collection VA |
| **Collection / VA** (not in portal yet) | Dedicated account number for **inbound** transfers | What Monnify “reserved account” does today for wallet top-ups |

**Practical path today:** use **Account Opening 2.0 + status** (and optionally **Current Account**) if Stanbic wants every customer on a real Stanbic account. For **wallet top-ups**, keep Monnify/Paystack until Stanbic confirms a **collection / virtual account** API on your plan.

Code:

- Account Opening 2.0 → `account_opening.py`
- Current account → `current_account.py` (OAuth Bearer)
- NPS disbursement / name enquiry → `portal_sandbox.py` + `StanbicClient` when `STANBIC_PORTAL_SANDBOX=true`
- Credit check → `credit_check.py` (opt-in `STANBIC_CREDIT_CHECK_ENABLED`)
- Transaction history → `portal_sandbox.transaction_history()` for settlement reconciliation

## Specs in repo

| File | Product |
|------|---------|
| `account-opening_2.0.0.json` | Account Opening (create) |
| `account-opening-status_1.0.0.json` | Account Opening status |
| `current-account-opening_1.0.0.json` | Current account for existing CIF |
| `name-enquiry_1.0.0.json` | NPS name enquiry |
| `single-transfer_1.0.0.json` | NPS transfer + `/trans-status` |
| `transaction-history-service_1.0.0.json` | Statement / reconciliation |
| `credit-check_2.0.0.json` | Outstanding loan, CBN, private checks |

## Still ask Stanbic for

- **Dedicated collection / virtual account** for wallet funding (inbound NIP to a unique NUBAN per customer)
- **Inbound payment webhooks** for that product (if separate from NPS)
- **NIP bank code list** — portal examples use `999221`-style codes; map from CBN 3-digit codes before live NPS

## Sandbox env (`.env`)

```env
STANBIC_MOCK=false
STANBIC_CLIENT_ID=
STANBIC_CLIENT_SECRET=
STANBIC_SETTLEMENT_ACCOUNT_NUMBER=   # source for NPS single-transfer
STANBIC_PORTAL_SANDBOX=true
STANBIC_ACCOUNT_OPENING_BASE_URL=https://testapi.stanbicibtc.com/test/sandbox/account-opening
STANBIC_NPS_BASE_URL=https://testapi.stanbicibtc.com/test/sandbox/nps
STANBIC_NAME_ENQUIRY_BASE_URL=https://testapi.stanbicibtc.com/test/sandbox/nameenquiry
STANBIC_TRANSACTION_HISTORY_BASE_URL=https://testapi.stanbicibtc.com/test/sandbox/transaction-history-service
STANBIC_CREDIT_CHECK_BASE_URL=https://testapi.stanbicibtc.com/test/sandbox/credit-check-services
STANBIC_OAUTH_TOKEN_URL=https://testapi.stanbicibtc.com/test/sandbox/mynativeoauthprovider/oauth2/token
```

Subscribe each product in the portal (Default plan) with the same sandbox keys.
