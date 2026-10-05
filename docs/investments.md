# Investments and card top-ups

## What customers get

- An **Invest** tab in the app: the plans on sale (picture, yearly rate, term, minimum, risk), their own investments
  with progress to maturity, and the total invested with expected returns.
- A plan screen with a live calculation. They invest wallet money with their transaction PIN. If the wallet is
  short, the button becomes "Add ₦X to your wallet" and opens Add money with the shortfall filled in.
- **Add money** has two tabs: Bank transfer (as before) and **Debit card**.

## Rules

These are defaults until GH Trust's product rules say otherwise:

- Returns are simple interest at the plan's yearly rate: `amount × rate × months / 12`, rounded to kobo. The rate
  is fixed when the customer invests; staff changing a plan only affects new investments.
- The money is locked until maturity. There is no early withdrawal.
- At maturity the amount plus returns goes into the wallet, with a notification. This is done by the hourly Celery
  beat task `pay-out-investments` (05 past each hour). It is idempotent, so running it twice pays once.
- A customer with an active investment can't delete their account (`INVESTMENT_ACTIVE`).

Ledger: investing debits `customer_wallet` and credits `investment_principal`. The payout debits
`investment_principal` (the amount) and `investment_return_expense` (the returns), and credits the wallet.

## Staff (admin portal → Investments)

Permissions: `investment:read` to view, `investment:manage` to create, edit, switch on/off and set pictures.
Super admins have both. Pictures are JPG, PNG or WebP, up to 2 MB.

The page shows the amount invested now, what pays out in the next 30 days, and every customer investment.

Three **sample plans** (14%/12 months, 18%/18 months, 24%/24 months) are created on start-up **only while there
are no plans at all**. Edit them, or take them off sale, before launch: their rates are placeholders, not offers.

## Card top-ups

1. `POST /api/v1/wallet/fund/card {amount}` (₦100 to ₦1,000,000) records a pending payment
   (reference `GHT-CARD-…`) and returns Monnify's `checkout_url`.
2. The app opens it in an in-app browser. When the customer finishes, Monnify sends them to
   `/api/v1/wallet/fund/card/return`, which hands them back to the app (`ghtrust://fund`).
3. The wallet is credited by whichever comes first: Monnify's `SUCCESSFUL_TRANSACTION` webhook (matched on
   `paymentReference`), or `GET /api/v1/wallet/fund/card/{reference}`, which asks Monnify. The app polls it.
   Both credit through the same ledger idempotency key, so a payment is credited once.

Card top-ups need `PAYMENT_PROVIDER=monnify`. With Monnify in mock mode (never allowed in production) a top-up
is credited at once, so demo servers can test the whole flow.

## Switching it on

Railway: `FEATURE_FLAGS=wallet,investments`. Without `investments` the tab still shows the plans, but investing
is refused (`FEATURE_DISABLED`) and the app says "Investing opens soon". The Celery worker **and** beat must run,
or nothing matures.

Monnify dashboard: the webhook URL must be `https://<api>/api/v1/webhooks/monnify` (the same one used for
transfers), and card payments must be enabled on the contract.
