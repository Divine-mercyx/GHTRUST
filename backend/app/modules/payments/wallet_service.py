from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.integrations.payments.factory import get_payment_client
from app.integrations.payments.schemas import PaymentRailError
from app.modules.notifications import events as notify
from app.modules.payments.ledger_service import LedgerError, LedgerService, raise_ledger_http
from app.modules.payments.models import (
    DvaStatus,
    PaymentChannel,
    PaymentDirection,
    PaymentProvider,
    PaymentTransaction,
    PayoutRecipient,
    WithdrawalRequest,
    WithdrawalStatus,
)
from app.models.base import TransactionStatus
from app.modules.users.models import Customer

logger = structlog.get_logger()


def _active_provider() -> PaymentProvider:
    provider = settings.active_payment_provider
    if provider == "paystack":
        return PaymentProvider.PAYSTACK
    if provider == "zest":
        return PaymentProvider.ZEST
    if provider == "stanbic":
        return PaymentProvider.STANBIC
    return PaymentProvider.MONNIFY


# What our own statement shows for every withdrawal; the recipient sees the customer's note instead.
WITHDRAWAL_NARRATION = "GH Trust wallet withdrawal"


def mask_account_number(number: str) -> str:
    return number[-4:].rjust(len(number), "*")


def payout_account_summary(customer: Customer) -> dict | None:
    if not customer.payout_account_number or not customer.payout_bank_code:
        return None
    return {
        "bank_code": customer.payout_bank_code,
        "bank_name": customer.payout_bank_name,
        "account_name": customer.payout_account_name,
        "account_number_masked": mask_account_number(customer.payout_account_number),
    }


def _blocked_until(customer: Customer) -> datetime | None:
    until = customer.transfers_blocked_until
    if until is None:
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until if until > datetime.now(timezone.utc) else None


class WalletService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.ledger = LedgerService(db)
        self.rail = get_payment_client()
        self.provider = _active_provider()

    async def get_wallet_summary(self, customer: Customer) -> dict:
        wallet = await self.ledger.get_or_create_wallet(customer.id)
        summary = {
            "available_balance": float(wallet.available_balance),
            "locked_balance": float(wallet.locked_balance),
            "currency": wallet.currency,
            "dva_status": wallet.dva_status.value,
            "dva_account_number": customer.paystack_dva_account_number,
            "dva_bank_name": customer.paystack_dva_bank_name,
            "payment_provider": self.provider.value,
            "account_reference": customer.paystack_customer_code,
            "paystack_customer_code": customer.paystack_customer_code,
            "funding_mode": "on_demand_dynamic" if self.provider == PaymentProvider.ZEST else "permanent_dva",
            "payout_account": payout_account_summary(customer),
            "withdrawals_blocked_until": _blocked_until(customer),
        }
        return summary

    async def provision_paystack(self, customer: Customer) -> Customer:
        """Provision payment rail (Monnify reserved account by default)."""
        return await self.provision_payment_rail(customer)

    async def provision_payment_rail(self, customer: Customer, *, strict: bool = True) -> Customer:
        """
        Create the customer's provider account number (reserved account / DVA).

        Safe to repeat: the account reference is fixed per customer, so if the provider already
        made the account (an earlier attempt whose reply was lost, or whose database commit
        never happened) it is looked up and adopted instead of failing. With strict=False a
        provider failure only marks the wallet FAILED for the retry job, and never raises.
        """
        wallet = await self.ledger.get_or_create_wallet(customer.id)
        email = customer.email or f"{customer.id}@wallet.ghtrust.local"
        account_reference = customer.paystack_customer_code or f"ghtrust_{customer.id}"

        if customer.paystack_dva_account_number and wallet.dva_status == DvaStatus.ACTIVE:
            await self.db.flush()
            return customer

        # Zest Notion API: dynamic VAs only (~5 min). No permanent account at signup.
        if self.provider == PaymentProvider.ZEST:
            customer.paystack_customer_code = account_reference
            wallet.dva_status = DvaStatus.PENDING
            await self.db.flush()
            return customer

        account_name = f"GH Trust / {customer.full_name}"[:100]
        from app.modules.payments import stanbic_fvid

        try:
            if stanbic_fvid.enabled():
                # Stanbic: our prefix + a serial + Stanbic's check digit; no create call.
                reserved = await stanbic_fvid.StanbicVirtualAccounts(self.db).assign(customer)
            else:
                reserved = await self.rail.create_reserved_account(
                    account_reference=account_reference,
                    account_name=account_name,
                    customer_email=email,
                    customer_name=customer.full_name,
                    bvn=customer.bvn,
                    phone=customer.phone_primary,
                )
        except PaymentRailError as exc:
            reserved = await self._existing_reserved_account(account_reference)
            if reserved is None:
                wallet.dva_status = DvaStatus.FAILED
                logger.error(
                    "payment_rail_provision_failed",
                    customer_id=customer.id,
                    provider=self.provider.value,
                    error=exc.message,
                )
                await self.db.flush()
                if strict and settings.payment_rail_enabled:
                    raise HTTPException(status_code=502, detail="Unable to provision payment account") from exc
                return customer
            logger.info("payment_rail_account_adopted", customer_id=customer.id, provider=self.provider.value)
        if not reserved.account_number:
            # Accepted but numbered later (async providers confirm by webhook).
            customer.paystack_customer_code = reserved.account_reference
            wallet.dva_status = DvaStatus.PENDING
            await self.db.flush()
            return customer
        customer.paystack_customer_code = reserved.account_reference
        customer.paystack_dva_account_number = reserved.account_number
        customer.paystack_dva_bank_name = reserved.bank_name
        customer.paystack_dva_bank_slug = reserved.bank_code
        wallet.dva_status = DvaStatus.ACTIVE

        await self.db.flush()
        return customer

    async def _existing_reserved_account(self, account_reference: str):
        """The provider's account for this reference, if it already exists (else None)."""
        lookup = getattr(self.rail, "get_reserved_account", None)
        if lookup is None:
            return None
        try:
            found = await lookup(account_reference)
        except PaymentRailError:
            return None
        return found if found.account_number else None

    async def create_funding_session(self, customer: Customer, amount: Decimal) -> dict:
        """Generate a Zest dynamic virtual account for a wallet top-up (expires ~5 min)."""
        if self.provider != PaymentProvider.ZEST:
            raise HTTPException(
                status_code=409,
                detail="On-demand funding sessions are only used with Zest",
            )
        email = customer.email or f"{customer.id}@wallet.ghtrust.local"
        try:
            session = await self.rail.create_wallet_funding_session(
                amount=amount,
                email=email,
                currency="NGN",
            )
        except PaymentRailError as exc:
            raise HTTPException(status_code=502, detail=exc.message) from exc

        customer.paystack_dva_account_number = session["account_number"]
        customer.paystack_dva_bank_name = session["bank_name"]
        customer.paystack_customer_code = session["transaction_ref"]
        wallet = await self.ledger.get_or_create_wallet(customer.id)
        wallet.dva_status = DvaStatus.PENDING
        await self.db.flush()
        return session

    async def update_payout_account(
        self,
        customer: Customer,
        *,
        bank_code: str,
        account_number: str,
        account_name: str,
        bank_name: str | None = None,
    ) -> Customer:
        customer.payout_bank_code = bank_code
        customer.payout_bank_name = bank_name
        customer.payout_account_number = account_number
        customer.payout_account_name = account_name

        try:
            resolved = await self.rail.validate_bank_account(account_number, bank_code)
            customer.payout_account_name = resolved.account_name
        except PaymentRailError:
            if not account_name:
                raise HTTPException(status_code=422, detail="Unable to validate bank account")

        if settings.active_payment_provider == "paystack":
            from app.integrations.paystack.schemas import CreateTransferRecipientRequest

            try:
                recipient = await self.rail.create_transfer_recipient(
                    CreateTransferRecipientRequest(
                        name=customer.payout_account_name or customer.full_name,
                        account_number=account_number,
                        bank_code=bank_code,
                    )
                )
                customer.paystack_transfer_recipient_code = recipient.recipient_code
            except PaymentRailError as exc:
                raise HTTPException(status_code=502, detail="Unable to save payout account") from exc

        await self.provision_payment_rail(customer)
        await self._remember_recipient(customer)
        await self.db.flush()
        return customer

    # ── Saved recipients ("Send money") ─────────────────────────────────────

    async def recipients(self, customer: Customer) -> list[PayoutRecipient]:
        """Saved accounts, most recently used (or added) first."""
        rows = (
            await self.db.execute(select(PayoutRecipient).where(PayoutRecipient.customer_id == customer.id))
        ).scalars()
        return sorted(rows, key=lambda r: _utc(r.last_used_at or r.created_at), reverse=True)

    async def remove_recipient(self, customer: Customer, recipient_id: str) -> None:
        recipient = await self._recipient(customer, recipient_id)
        if self.is_current(customer, recipient):
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.RECIPIENT_IN_USE,
                "This is where withdrawals go now. Choose another account first, then remove it.",
            )
        await self.db.delete(recipient)
        await self.db.flush()

    async def use_recipient(self, customer: Customer, recipient_id: str) -> PayoutRecipient:
        """Make a saved account the one withdrawals go to (the customer picked it to send to)."""
        recipient = await self._recipient(customer, recipient_id)
        customer.payout_bank_code = recipient.bank_code
        customer.payout_bank_name = recipient.bank_name
        customer.payout_account_number = recipient.account_number
        customer.payout_account_name = recipient.account_name
        customer.paystack_transfer_recipient_code = recipient.recipient_code
        recipient.last_used_at = datetime.now(timezone.utc)
        await self.db.flush()
        return recipient

    @staticmethod
    def is_current(customer: Customer, recipient: PayoutRecipient) -> bool:
        return (
            customer.payout_bank_code == recipient.bank_code
            and customer.payout_account_number == recipient.account_number
        )

    async def _recipient(self, customer: Customer, recipient_id: str) -> PayoutRecipient:
        recipient = await self.db.scalar(
            select(PayoutRecipient).where(
                PayoutRecipient.id == recipient_id, PayoutRecipient.customer_id == customer.id
            )
        )
        if recipient is None:
            raise AppError(status.HTTP_404_NOT_FOUND, ErrorCode.RECIPIENT_NOT_FOUND, "Saved account not found")
        return recipient

    async def _remember_recipient(self, customer: Customer) -> None:
        """Keep the payout account just saved in the customer's recipients (once per account)."""
        if not customer.payout_bank_code or not customer.payout_account_number:
            return
        recipient = await self.db.scalar(
            select(PayoutRecipient).where(
                PayoutRecipient.customer_id == customer.id,
                PayoutRecipient.bank_code == customer.payout_bank_code,
                PayoutRecipient.account_number == customer.payout_account_number,
            )
        )
        if recipient is None:
            recipient = PayoutRecipient(
                customer_id=customer.id,
                bank_code=customer.payout_bank_code,
                account_number=customer.payout_account_number,
            )
            self.db.add(recipient)
        recipient.bank_name = customer.payout_bank_name
        recipient.account_name = customer.payout_account_name
        recipient.recipient_code = customer.paystack_transfer_recipient_code
        recipient.last_used_at = datetime.now(timezone.utc)

    async def request_withdrawal(
        self, customer: Customer, amount: Decimal, narration: str | None = None
    ) -> WithdrawalRequest:
        if amount <= 0:
            raise HTTPException(status_code=422, detail="Amount must be positive")
        if not customer.payout_account_number or not customer.payout_bank_code:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.PAYOUT_ACCOUNT_REQUIRED,
                "Add a payout bank account before withdrawing",
            )

        if settings.active_payment_provider == "paystack" and not customer.paystack_transfer_recipient_code:
            await self.update_payout_account(
                customer,
                bank_code=customer.payout_bank_code,
                account_number=customer.payout_account_number,
                account_name=customer.payout_account_name or customer.full_name,
            )

        wallet = await self.ledger.get_or_create_wallet(customer.id)
        reference = f"ghtrust_wdr_{uuid4().hex[:20]}"
        idempotency_key = f"withdrawal_hold:{reference}"

        try:
            await self.ledger.hold_wallet_for_withdrawal(
                customer_id=customer.id,
                amount=amount,
                idempotency_key=idempotency_key,
                reference=reference,
            )
        except LedgerError as exc:
            if exc.status_code == 409:
                raise AppError(status.HTTP_409_CONFLICT, ErrorCode.INSUFFICIENT_FUNDS, exc.message) from exc
            raise_ledger_http(exc)

        withdrawal = WithdrawalRequest(
            customer_id=customer.id,
            wallet_id=wallet.id,
            amount=amount,
            bank_code=customer.payout_bank_code,
            bank_name=customer.payout_bank_name,
            account_number=customer.payout_account_number,
            account_name=customer.payout_account_name or customer.full_name,
            recipient_code=customer.paystack_transfer_recipient_code,
            transfer_reference=reference,
            narration=narration,
            status=WithdrawalStatus.PENDING,
        )
        self.db.add(withdrawal)
        await self.db.flush()
        return withdrawal

    async def process_withdrawal(self, withdrawal: WithdrawalRequest) -> WithdrawalRequest:
        """
        Send a held withdrawal to the rail. Called by the Celery worker, which
        commits after each withdrawal.

        * The PaymentTransaction is created and committed BEFORE the provider is
          called, so reconciliation can always find the transfer by reference.
        * Provider rejection → FAILED and the hold is released.
        * Transient failure (timeout / 5xx) → outcome unknown: stays PROCESSING
          and the hold stays in place until reconciliation confirms either way.
          Releasing it (the old behaviour) let a customer withdraw the same
          money twice whenever a bank timeout hid a successful transfer.
        """
        if withdrawal.status != WithdrawalStatus.PENDING:
            return withdrawal

        payment_tx = PaymentTransaction(
            provider=self.provider,
            provider_reference=withdrawal.transfer_reference,
            direction=PaymentDirection.OUTBOUND,
            channel=PaymentChannel.TRANSFER,
            amount=withdrawal.amount,
            currency="NGN",
            status=TransactionStatus.PENDING,
            customer_id=withdrawal.customer_id,
            wallet_id=withdrawal.wallet_id,
            withdrawal_id=withdrawal.id,
            raw_payload={},
        )
        self.db.add(payment_tx)
        withdrawal.status = WithdrawalStatus.PROCESSING
        await self.db.commit()

        try:
            if settings.active_payment_provider == "paystack":
                from app.integrations.paystack.schemas import InitiateTransferRequest, naira_to_kobo

                transfer = await self.rail.initiate_transfer(
                    InitiateTransferRequest(
                        amount=naira_to_kobo(withdrawal.amount),
                        recipient=withdrawal.recipient_code or "",
                        reason=withdrawal.narration or WITHDRAWAL_NARRATION,
                        reference=withdrawal.transfer_reference,
                    )
                )
                withdrawal.transfer_code = transfer.transfer_code
                payment_tx.provider_transaction_id = str(transfer.id)
                payment_tx.raw_payload = {"transfer_code": transfer.transfer_code, "status": transfer.status}
            else:
                result = await self.rail.initiate_disbursement(
                    amount=withdrawal.amount,
                    reference=withdrawal.transfer_reference,
                    bank_code=withdrawal.bank_code,
                    account_number=withdrawal.account_number,
                    account_name=withdrawal.account_name,
                    narration=withdrawal.narration or WITHDRAWAL_NARRATION,
                    source_narration=WITHDRAWAL_NARRATION,
                )
                withdrawal.transfer_code = result.transaction_id
                payment_tx.provider_transaction_id = result.transaction_id or withdrawal.transfer_reference
                payment_tx.raw_payload = {"status": result.status, "reference": result.reference}
                if isinstance(result.raw, dict) and "_nps_status_payload" in result.raw:
                    # Stanbic NPS status checks need the original transfer details.
                    payment_tx.raw_payload["_nps_status_payload"] = result.raw["_nps_status_payload"]
        except PaymentRailError as exc:
            if exc.outcome_unknown:
                logger.warning(
                    "withdrawal_outcome_unknown",
                    withdrawal_id=withdrawal.id,
                    reference=withdrawal.transfer_reference,
                    error=exc.message,
                )
                return withdrawal
            payment_tx.status = TransactionStatus.FAILED
            payment_tx.failure_reason = exc.message
            withdrawal.status = WithdrawalStatus.FAILED
            withdrawal.failure_reason = exc.message
            withdrawal.processed_at = datetime.now(timezone.utc)
            try:
                await self.ledger.release_withdrawal_hold(
                    customer_id=withdrawal.customer_id,
                    amount=withdrawal.amount,
                    idempotency_key=f"withdrawal_release:{withdrawal.transfer_reference}",
                    reference=withdrawal.transfer_reference,
                )
            except LedgerError as ledger_err:
                logger.error("withdrawal_release_failed", withdrawal_id=withdrawal.id, error=ledger_err.message)
                raise
            await notify.withdrawal_failed(self.db, withdrawal)
        await self.db.flush()
        return withdrawal


def _utc(dt: datetime) -> datetime:
    """SQLite hands back naive datetimes; Postgres aware ones."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
