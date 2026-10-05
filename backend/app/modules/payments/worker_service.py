"""
Async job bodies invoked from Celery tasks (app/workers/tasks.py).

Each Celery task runs its coroutine with ``asyncio.run()`` — a brand-new event
loop per run. asyncpg connections are bound to the loop that created them, so
the API's module-level connection pool cannot be reused here: the second task
in a worker process failed with "attached to a different loop". Every job
therefore opens its own short-lived engine via ``worker_session()``.

Jobs commit per item. One bad withdrawal or transaction is logged and skipped
instead of rolling back work already done for the others — which, for
transfers already sent to the bank, would have lost the record of them.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.integrations.monnify.constants import PAYMENT_STATUS_PAID
from app.integrations.payments.factory import get_payment_client
from app.integrations.payments.schemas import PaymentRailError
from app.integrations.paystack.constants import TRANSACTION_STATUS_SUCCESS, TRANSFER_STATUS_SUCCESS
from app.integrations.paystack.schemas import kobo_to_naira
from app.integrations.zest.client import ZestClient
from app.models.base import TransactionStatus
from app.modules.loans.servicing import LoanServicingService
from app.modules.payments.ledger_service import LedgerService
from app.modules.payments.models import (
    PaymentDirection,
    PaymentProvider,
    PaymentTransaction,
    WithdrawalRequest,
    WithdrawalStatus,
)
from app.modules.payments.wallet_service import WalletService
from app.modules.payments.webhook_service import WebhookService

logger = structlog.get_logger()


def _active_provider() -> PaymentProvider:
    provider = get_settings().active_payment_provider
    if provider == "paystack":
        return PaymentProvider.PAYSTACK
    if provider == "zest":
        return PaymentProvider.ZEST
    if provider == "stanbic":
        return PaymentProvider.STANBIC
    return PaymentProvider.MONNIFY


@asynccontextmanager
async def worker_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().async_database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def run_process_pending_withdrawals(limit: int = 50) -> dict:
    processed = failed = 0
    async with worker_session() as db:
        ids = (
            await db.execute(
                select(WithdrawalRequest.id)
                .where(WithdrawalRequest.status == WithdrawalStatus.PENDING)
                .order_by(WithdrawalRequest.created_at.asc())
                .limit(limit)
            )
        ).scalars().all()
        wallet_svc = WalletService(db)
        for withdrawal_id in ids:
            try:
                withdrawal = await db.get(WithdrawalRequest, withdrawal_id, with_for_update=True)
                if withdrawal is None:
                    continue
                await wallet_svc.process_withdrawal(withdrawal)
                await db.commit()
                processed += 1
            except Exception:
                await db.rollback()
                failed += 1
                logger.exception("withdrawal_processing_failed", withdrawal_id=withdrawal_id)
    return {"status": "ok", "processed": processed, "failed": failed}


async def _settle_outbound(db: AsyncSession, rail, tx: PaymentTransaction) -> bool:
    """Resolve a PENDING outbound transfer by asking the rail. Returns True if settled."""
    provider = get_settings().active_payment_provider
    if provider == "zest":
        return False  # no outbound transfers on Zest
    if provider == "paystack":
        transfer = await rail.verify_transfer(tx.provider_reference)
        succeeded = transfer.status == TRANSFER_STATUS_SUCCESS
        failed = transfer.status in ("failed", "reversed")
        reason = f"Paystack transfer {transfer.status}"
    else:
        transfer = await rail.verify_disbursement(tx.provider_reference)
        succeeded = rail.is_disbursement_success(transfer.status)
        failed = rail.is_disbursement_failed(transfer.status)
        reason = transfer.narration or f"Transfer {transfer.status}"

    # Same code paths as the webhooks, so withdrawals are settled/released and
    # loan disbursements are completed/booked identically whichever arrives.
    webhooks = WebhookService(db)
    if succeeded:
        await webhooks._handle_transfer_success({"reference": tx.provider_reference})
        return True
    if failed:
        await webhooks._handle_transfer_failed({"reference": tx.provider_reference, "reason": reason})
        return True
    return False


async def _settle_inbound(db: AsyncSession, rail, tx: PaymentTransaction) -> bool:
    provider = get_settings().active_payment_provider
    verified = await rail.verify_transaction(tx.provider_reference)
    if provider == "zest":
        is_paid = ZestClient.is_payment_success(verified.status)
        amount = Decimal(str(verified.amount))
    elif provider == "paystack":
        is_paid = verified.status == TRANSACTION_STATUS_SUCCESS
        amount = Decimal(str(kobo_to_naira(verified.amount)))
    else:
        is_paid = verified.status == PAYMENT_STATUS_PAID
        amount = Decimal(str(verified.amount))
    if not is_paid or not tx.customer_id:
        return False
    await LedgerService(db).credit_wallet_from_paystack(
        customer_id=tx.customer_id,
        amount=amount,
        idempotency_key=f"wallet_funding:{tx.provider_reference}",
        reference=tx.provider_reference,
        payment_transaction=tx,
    )
    tx.status = TransactionStatus.COMPLETED
    return True


async def run_reconcile_payments(limit: int = 100) -> dict:
    matched = errors = 0
    rail = get_payment_client()
    provider = _active_provider()
    async with worker_session() as db:
        ids = (
            await db.execute(
                select(PaymentTransaction.id)
                .where(
                    PaymentTransaction.provider == provider,
                    PaymentTransaction.status == TransactionStatus.PENDING,
                )
                .order_by(PaymentTransaction.created_at.asc())
                .limit(limit)
            )
        ).scalars().all()

        for tx_id in ids:
            try:
                tx = await db.get(PaymentTransaction, tx_id)
                if tx is None or tx.status != TransactionStatus.PENDING:
                    continue
                if tx.direction == PaymentDirection.OUTBOUND:
                    settled = await _settle_outbound(db, rail, tx)
                else:
                    settled = await _settle_inbound(db, rail, tx)
                await db.commit()
                matched += int(settled)
            except PaymentRailError as exc:
                await db.rollback()
                errors += 1
                logger.warning("reconcile_rail_error", transaction_id=tx_id, error=exc.message)
            except Exception:
                await db.rollback()
                errors += 1
                logger.exception("reconcile_payment_failed", transaction_id=tx_id)
    return {"status": "ok", "matched": matched, "errors": errors}


async def run_refresh_loan_statuses() -> dict:
    """Mark overdue installments and roll each open loan's next due date forward."""
    async with worker_session() as db:
        processed = await LoanServicingService(db).refresh_open_loans()
        await db.commit()
    return {"status": "ok", "loans_processed": processed}


LAGOS = ZoneInfo("Africa/Lagos")


async def run_deliver_notifications() -> dict:
    """Push queued notifications to customers' phones."""
    from app.modules.notifications.service import NotificationService

    async with worker_session() as db:
        counts = await NotificationService(db).deliver_pending()
        await db.commit()
    return {"status": "ok", **counts}


async def run_pay_out_investments() -> dict:
    """Pay matured investments (amount plus returns) into customers' wallets."""
    from app.modules.investments.service import InvestmentService

    async with worker_session() as db:
        paid = await InvestmentService(db).pay_out_matured()
        await db.commit()
    return {"status": "ok", "paid_out": paid}


async def run_send_loan_reminders() -> dict:
    """Queue today's repayment reminders; the delivery job pushes them."""
    from app.modules.notifications.events import send_repayment_reminders

    today = datetime.now(LAGOS).date()
    async with worker_session() as db:
        queued = await send_repayment_reminders(db, today)
        await db.commit()
    return {"status": "ok", "reminders_queued": queued}
