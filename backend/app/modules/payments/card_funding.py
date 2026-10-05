"""
Card top-ups: the customer pays on Monnify's hosted card page and the money lands in the wallet.

POST /wallet/fund/card records a pending PaymentTransaction (provider_reference is our payment
reference) and returns Monnify's checkout URL. The wallet is credited by whichever comes first:
Monnify's SUCCESSFUL_TRANSACTION webhook, or the app asking for the status and Monnify's query
saying PAID. The ledger idempotency key makes the second one a no-op.

Without Monnify keys (mock mode, never allowed in production) the top-up is credited at once,
so the flow can be tried end to end on a demo server.
"""

from decimal import Decimal
from secrets import token_hex
from typing import Any

import structlog
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.integrations.monnify.client import MonnifyClient
from app.integrations.payments.schemas import PaymentRailError
from app.models.base import TransactionStatus
from app.modules.payments.ledger_service import LedgerService
from app.modules.payments.models import PaymentChannel, PaymentDirection, PaymentProvider, PaymentTransaction
from app.modules.users.models import Customer

logger = structlog.get_logger()

# Monnify payment statuses that will never turn into money.
FAILED_STATUSES = {"FAILED", "CANCELLED", "EXPIRED", "REVERSED"}
PAID_STATUSES = {"PAID", "OVERPAID"}


def _view(tx: PaymentTransaction, checkout_url: str | None = None) -> dict[str, Any]:
    return {
        "reference": tx.provider_reference,
        "amount": tx.amount,
        "status": tx.status.value,
        "checkout_url": checkout_url,
    }


class CardFundingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.monnify = MonnifyClient()

    async def start(self, customer: Customer, amount: Decimal, redirect_url: str) -> dict[str, Any]:
        if settings.active_payment_provider != "monnify":
            raise AppError(
                status.HTTP_409_CONFLICT, "CARD_UNAVAILABLE", "Card top-ups aren't available. Use bank transfer."
            )
        wallet = await LedgerService(self.db).get_or_create_wallet(customer.id)
        reference = f"GHT-CARD-{token_hex(8).upper()}"
        tx = PaymentTransaction(
            provider=PaymentProvider.MONNIFY,
            provider_reference=reference,
            direction=PaymentDirection.INBOUND,
            channel=PaymentChannel.CARD,
            amount=amount,
            status=TransactionStatus.PENDING,
            customer_id=customer.id,
            wallet_id=wallet.id,
        )
        self.db.add(tx)
        await self.db.flush()
        try:
            checkout = await self.monnify.init_card_checkout(
                amount=amount,
                payment_reference=reference,
                customer_name=customer.full_name,
                customer_email=customer.email or f"{customer.id}@wallet.ghtrust.local",
                redirect_url=redirect_url,
            )
        except PaymentRailError as exc:
            logger.warning("card_checkout_failed", reference=reference, error=exc.message)
            raise AppError(
                status.HTTP_502_BAD_GATEWAY,
                "CARD_UNAVAILABLE",
                "We couldn't open the card payment page. Try again, or use bank transfer.",
            ) from exc
        tx.provider_transaction_id = checkout.transaction_reference
        if checkout.mock:
            await self.complete(tx, amount, source="mock")
        await self.db.flush()
        logger.info("card_topup_started", reference=reference, amount=str(amount), mock=checkout.mock)
        return _view(tx, checkout.checkout_url)

    async def status(self, customer: Customer, reference: str) -> dict[str, Any]:
        tx = await self._find(reference, customer_id=customer.id)
        if tx is None:
            raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Top-up not found")
        if tx.status == TransactionStatus.PENDING:
            try:
                found = await self.monnify.query_by_payment_reference(reference)
            except PaymentRailError as exc:
                logger.info("card_topup_query_failed", reference=reference, error=exc.message)
            else:
                state = found.status.upper()
                if state in PAID_STATUSES:
                    await self.complete(tx, found.amount, source="query", transaction_reference=found.transaction_reference)
                elif state in FAILED_STATUSES:
                    tx.status = TransactionStatus.FAILED
                    tx.failure_reason = f"Card payment {state.lower()}"
                    await self.db.flush()
        return _view(tx)

    async def handle_webhook(self, data: dict[str, Any]) -> bool:
        """Credit a card top-up from Monnify's webhook. False if the payment isn't one of ours."""
        reference = str(data.get("paymentReference") or "")
        if not reference.startswith("GHT-CARD-"):
            return False
        tx = await self._find(reference)
        if tx is None:
            logger.warning("card_topup_webhook_unknown", reference=reference)
            return True
        await self.complete(
            tx,
            Decimal(str(data.get("amountPaid") or 0)),
            source="webhook",
            transaction_reference=str(data.get("transactionReference") or "") or None,
            raw=data,
        )
        return True

    async def complete(
        self,
        tx: PaymentTransaction,
        paid: Decimal,
        *,
        source: str,
        transaction_reference: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        if tx.status == TransactionStatus.COMPLETED:
            return
        # Credit what was asked for; a short payment credits only what arrived.
        amount = tx.amount if paid <= 0 and source == "mock" else min(paid, tx.amount)
        if amount <= 0:
            return
        if transaction_reference:
            tx.provider_transaction_id = transaction_reference
        if raw is not None:
            tx.raw_payload = raw
            tx.webhook_event = "SUCCESSFUL_TRANSACTION"
        await LedgerService(self.db).credit_wallet_from_paystack(
            customer_id=tx.customer_id,
            amount=amount,
            idempotency_key=f"card_funding:{tx.provider_reference}",
            reference=tx.provider_reference,
            payment_transaction=tx,
            description="Wallet funded by card",
        )
        tx.status = TransactionStatus.COMPLETED
        await self.db.flush()
        logger.info("card_topup_credited", reference=tx.provider_reference, amount=str(amount), source=source)

    async def _find(self, reference: str, customer_id: str | None = None) -> PaymentTransaction | None:
        query = select(PaymentTransaction).where(
            PaymentTransaction.provider == PaymentProvider.MONNIFY,
            PaymentTransaction.provider_reference == reference,
            PaymentTransaction.channel == PaymentChannel.CARD,
        )
        if customer_id:
            query = query.where(PaymentTransaction.customer_id == customer_id)
        return (await self.db.execute(query.with_for_update())).scalar_one_or_none()
