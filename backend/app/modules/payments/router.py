from typing import Literal

import re

from fastapi import APIRouter, Header, Query, Request, status
from fastapi.responses import HTMLResponse

from app.core.deps import CurrentCustomer, DbSession
from app.core.errors import AppError
from app.modules.auth.security_service import SecurityService
from app.modules.payments.ledger_service import LedgerError, raise_ledger_http
from app.modules.payments.card_funding import CardFundingService
from app.modules.payments.schemas import (
    CardFundRequest,
    CardFundResponse,
    PayoutAccountSavedResponse,
    UpdatePayoutAccountRequest,
    WalletFundRequest,
    WalletFundSessionResponse,
    WalletSummaryResponse,
    WalletTransactionPage,
    WalletTransactionResponse,
    WithdrawalResponse,
    WithdrawRequest,
)
from app.modules.payments.transactions import MAX_PAGE, InvalidCursor, WalletTransactionService
from app.modules.payments.wallet_service import WalletService, mask_account_number, payout_account_summary

router = APIRouter(prefix="/wallet", tags=["Wallet"])


@router.get("", response_model=WalletSummaryResponse)
async def get_wallet(customer: CurrentCustomer, db: DbSession) -> WalletSummaryResponse:
    summary = await WalletService(db).get_wallet_summary(customer)
    return WalletSummaryResponse(**summary)


@router.post("/fund", response_model=WalletFundSessionResponse)
async def create_wallet_funding_session(
    payload: WalletFundRequest,
    customer: CurrentCustomer,
    db: DbSession,
) -> WalletFundSessionResponse:
    """Zest: generate a temporary virtual account for bank transfer (expires ~5 minutes)."""
    session = await WalletService(db).create_funding_session(customer, payload.amount)
    return WalletFundSessionResponse(**session)


def _card_return_url(request: Request) -> str:
    url = str(request.url_for("card_funding_return"))
    host = request.url.hostname or ""
    if url.startswith("http://") and host not in {"localhost", "127.0.0.1", "testserver"} and not host.startswith("192.168."):
        url = "https://" + url[len("http://"):]  # behind the host's TLS proxy
    return url


@router.post("/fund/card", response_model=CardFundResponse, status_code=status.HTTP_201_CREATED)
async def start_card_funding(
    payload: CardFundRequest, request: Request, customer: CurrentCustomer, db: DbSession
) -> CardFundResponse:
    """
    Top up the wallet with a debit card. Open `checkout_url` in a browser; when the customer
    finishes, the page goes to `return_url`. Then poll GET /wallet/fund/card/{reference}.
    """
    return_url = _card_return_url(request)
    started = await CardFundingService(db).start(customer, payload.amount, return_url)
    return CardFundResponse(**started, return_url=return_url)


@router.get("/fund/card/return", name="card_funding_return", include_in_schema=False)
async def card_funding_return(paymentReference: str = "") -> HTMLResponse:  # noqa: N803 (Monnify's name)
    """Where Monnify's checkout lands. Hands the customer back to the app."""
    ref = re.sub(r"[^A-Za-z0-9_-]", "", paymentReference)[:64]
    app_link = f"ghtrust://fund?reference={ref}"
    return HTMLResponse(
        "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>GH Trust</title><body style='font-family:sans-serif;text-align:center;padding:48px 24px'>"
        "<h2>Payment received</h2><p>You can go back to the GH Trust app.</p>"
        f"<p><a href='{app_link}'>Open GH Trust</a></p>"
        f"<script>location.href={app_link!r}</script></body>"
    )


@router.get("/fund/card/{reference}", response_model=CardFundResponse)
async def card_funding_status(reference: str, customer: CurrentCustomer, db: DbSession) -> CardFundResponse:
    return CardFundResponse(**await CardFundingService(db).status(customer, reference))


@router.get("/transactions", response_model=WalletTransactionPage)
async def list_wallet_transactions(
    customer: CurrentCustomer,
    db: DbSession,
    direction: Literal["in", "out"] | None = Query(None, description="Only money in, or only money out"),
    limit: int = Query(20, ge=1, le=MAX_PAGE),
    cursor: str | None = Query(None, max_length=200, description="`next_cursor` from the previous page"),
) -> WalletTransactionPage:
    """Money in and out of the wallet, newest first."""
    try:
        items, next_cursor = await WalletTransactionService(db).page(
            customer.id, direction=direction, limit=limit, cursor=cursor
        )
    except InvalidCursor as exc:
        raise AppError(status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "Invalid cursor") from exc
    return WalletTransactionPage(items=items, next_cursor=next_cursor)


@router.get("/transactions/{transaction_id}", response_model=WalletTransactionResponse)
async def get_wallet_transaction(
    transaction_id: str, customer: CurrentCustomer, db: DbSession
) -> WalletTransactionResponse:
    """One transaction, for its receipt."""
    item = await WalletTransactionService(db).get(customer.id, transaction_id)
    if item is None:
        raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Transaction not found")
    return WalletTransactionResponse(**item)


@router.post("/payout-account", response_model=PayoutAccountSavedResponse)
async def update_payout_account(
    payload: UpdatePayoutAccountRequest,
    customer: CurrentCustomer,
    db: DbSession,
):
    # Changing where withdrawals go is as sensitive as a withdrawal.
    await SecurityService(db).authorize_transaction(customer, payload.transaction_pin)
    updated = await WalletService(db).update_payout_account(
        customer,
        bank_code=payload.bank_code,
        account_number=payload.account_number,
        account_name=payload.account_name or customer.full_name,
        bank_name=payload.bank_name,
    )
    return {
        "message": "Payout account saved",
        "account_name": updated.payout_account_name,
        "account_number": mask_account_number(updated.payout_account_number),
        "payout_account": payout_account_summary(updated),
    }


@router.post(
    "/withdraw",
    response_model=WithdrawalResponse,
    description=(
        "Requires an `Idempotency-Key` header: a retried request with the same key "
        "returns the original withdrawal instead of creating a second one."
    ),
)
async def request_withdrawal(
    payload: WithdrawRequest,
    customer: CurrentCustomer,
    db: DbSession,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=64),
) -> WithdrawalResponse:
    await SecurityService(db).authorize_transaction(customer, payload.transaction_pin)
    try:
        withdrawal = await WalletService(db).request_withdrawal(customer, payload.amount)
    except LedgerError as exc:
        raise_ledger_http(exc)
    return WithdrawalResponse(
        id=withdrawal.id,
        amount=float(withdrawal.amount),
        status=withdrawal.status.value,
        transfer_reference=withdrawal.transfer_reference,
    )
