import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.monnify.constants import (
    DISBURSEMENT_FAILED,
    DISBURSEMENT_REVERSED,
    DISBURSEMENT_SUCCESS,
    DISBURSEMENT_WEBHOOK_EVENTS,
    PAYMENT_STATUS_PAID,
    PRODUCT_TYPE_RESERVED_ACCOUNT,
)
from app.integrations.paystack.constants import (
    TRANSACTION_STATUS_SUCCESS,
)
from app.integrations.paystack.schemas import kobo_to_naira
from app.integrations.zest.constants import WEBHOOK_EVENT_TRANSACTION
from app.integrations.zest.client import ZestClient
from app.integrations.stanbic.constants import (
    ACCOUNT_WEBHOOK_EVENTS,
    EVENT_ACCOUNT_ACTIVATED,
    EVENT_PAYMENT_SUCCESS,
    EVENT_TRANSFER_FAILED,
    EVENT_TRANSFER_REVERSED,
    EVENT_TRANSFER_SUCCESS,
    INBOUND_WEBHOOK_EVENTS,
    TRANSFER_WEBHOOK_EVENTS,
)
from app.integrations.stanbic.constants import (
    PAYMENT_STATUS_PAID as STANBIC_PAYMENT_STATUS_PAID,
)
from app.models.base import TransactionStatus
from app.modules.notifications import events as notify
from app.modules.payments.disbursement_service import DisbursementService
from app.modules.payments.ledger_service import LedgerError, LedgerService
from app.modules.payments.models import (
    DvaStatus,
    PaymentChannel,
    PaymentDirection,
    PaymentProvider,
    PaymentTransaction,
    ProcessedWebhookEvent,
    WithdrawalRequest,
    WithdrawalStatus,
)
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


class WebhookService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.ledger = LedgerService(db)

    @staticmethod
    def _event_key(provider: str, event_type: str, data: dict[str, Any]) -> str:
        event_id = (
            data.get("id")
            or data.get("reference")
            or data.get("transfer_code")
            or data.get("transactionReference")
            or data.get("paymentReference")
        )
        return f"{provider}:{event_type}:{event_id}"

    @staticmethod
    def _payload_hash(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    async def _claim_event(
        self, provider: str, event_type: str, data: dict[str, Any], payload: bytes
    ) -> bool:
        key = self._event_key(provider, event_type, data)
        existing = await self.db.execute(
            select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.event_key == key)
        )
        if existing.scalar_one_or_none():
            return False
        # Savepoint: a concurrent delivery of the same event may insert between
        # our check and this flush. The unique constraint then means "already
        # claimed" — treat it as a duplicate instead of failing the request.
        try:
            async with self.db.begin_nested():
                self.db.add(
                    ProcessedWebhookEvent(
                        event_key=key,
                        event_type=event_type,
                        provider=provider,
                        payload_hash=self._payload_hash(payload),
                        processed_at=datetime.now(timezone.utc),
                    )
                )
                await self.db.flush()
        except IntegrityError:
            logger.info("webhook_event_claim_race", event_key=key)
            return False
        return True

    async def handle_event(self, event_type: str, data: dict[str, Any], raw_payload: bytes) -> None:
        claimed = await self._claim_event("paystack", event_type, data, raw_payload)
        if not claimed:
            logger.info("paystack_webhook_duplicate", webhook_event_type=event_type)
            return

        if event_type == "charge.success":
            await self._handle_charge_success(data)
        elif event_type == "dedicatedaccount.assign.success":
            await self._handle_dva_assigned(data)
        elif event_type == "dedicatedaccount.assign.failed":
            await self._handle_dva_failed(data)
        elif event_type == "transfer.success":
            await self._handle_transfer_success(data)
        elif event_type == "transfer.failed":
            await self._handle_transfer_failed(data)
        elif event_type == "transfer.reversed":
            await self._handle_transfer_reversed(data)
        else:
            logger.info("paystack_webhook_ignored", webhook_event_type=event_type)

    async def handle_monnify_payload(self, payload: dict[str, Any], raw_payload: bytes) -> None:
        event_type = payload.get("eventType")
        if event_type == "SUCCESSFUL_TRANSACTION":
            data = payload.get("eventData") or {}
            await self._handle_monnify_inbound(data, raw_payload, event_type)
        elif event_type in DISBURSEMENT_WEBHOOK_EVENTS:
            data = payload.get("eventData") or {}
            await self._handle_monnify_disbursement(event_type, data, raw_payload)
        elif payload.get("paymentStatus"):
            await self._handle_monnify_inbound(payload, raw_payload, "SUCCESSFUL_TRANSACTION")
        else:
            logger.info("monnify_webhook_ignored", webhook_event_type=event_type)

    async def handle_zest_payload(self, payload: dict[str, Any], raw_payload: bytes) -> None:
        event_type = str(payload.get("event_type") or payload.get("eventType") or WEBHOOK_EVENT_TRANSACTION)
        status = str(payload.get("event_status") or payload.get("status") or payload.get("trans_status") or "")
        if not ZestClient.is_payment_success(status):
            logger.info("zest_webhook_ignored_status", status=status, event_type=event_type)
            return
        await self._handle_zest_inbound(payload, raw_payload, event_type)

    async def _handle_zest_inbound(
        self, data: dict[str, Any], raw_payload: bytes, event_type: str
    ) -> None:
        amount_raw = data.get("AmountPaid") or data.get("amountPaid") or data.get("amount") or 0
        amount = Decimal(str(amount_raw))
        if amount <= 0:
            logger.warning("zest_inbound_zero_amount", reference=data.get("Reference"))
            return

        reference = str(
            data.get("Reference")
            or data.get("reference")
            or data.get("TrackingRef")
            or data.get("transactionRef")
            or data.get("TrackingID")
        )
        account_number = str(data.get("AccountNo") or data.get("accountNumber") or "")
        account_reference = str(data.get("AccountRef") or data.get("accountReference") or "")

        claimed = await self._claim_event("zest", event_type, data, raw_payload)
        if not claimed:
            logger.info("zest_webhook_duplicate", webhook_event_type=event_type)
            return

        customer = await self._find_customer_by_account_reference(account_reference)
        if not customer and account_number:
            customer = await self._find_customer_by_dva(account_number)
        if not customer:
            logger.error(
                "zest_inbound_customer_not_found",
                reference=reference,
                account_reference=account_reference,
                account_number=account_number[-4:] if account_number else None,
            )
            return

        provider = PaymentProvider.ZEST
        existing_tx = await self.db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.provider == provider,
                PaymentTransaction.provider_reference == reference,
            )
        )
        if existing_tx.scalar_one_or_none():
            return

        wallet = await self.ledger.get_or_create_wallet(customer.id)
        payment_tx = PaymentTransaction(
            provider=provider,
            provider_reference=reference,
            provider_transaction_id=reference,
            direction=PaymentDirection.INBOUND,
            channel=PaymentChannel.DVA,
            amount=amount,
            currency=data.get("currency") or "NGN",
            status=TransactionStatus.COMPLETED,
            customer_id=customer.id,
            wallet_id=wallet.id,
            webhook_event=event_type,
            raw_payload=data,
        )
        self.db.add(payment_tx)
        await self.db.flush()

        try:
            await self.ledger.credit_wallet_from_paystack(
                customer_id=customer.id,
                amount=amount,
                idempotency_key=f"wallet_funding:{reference}",
                reference=reference,
                payment_transaction=payment_tx,
            )
        except LedgerError as exc:
            logger.error("zest_inbound_ledger_failed", reference=reference, error=exc.message)
            payment_tx.status = TransactionStatus.FAILED
            payment_tx.failure_reason = exc.message

    # -- Stanbic IBTC bank partner ------------------------------------------

    async def handle_stanbic_payload(self, payload: dict[str, Any], raw_payload: bytes) -> None:
        """
        Route a Stanbic webhook (requirements doc section 4).

        TODO(stanbic-spec): confirm the envelope. We accept the event name at
        ``event_type``/``eventType``/``event`` and the body at ``data`` or the
        payload root.
        """
        event_type = str(
            payload.get("event_type") or payload.get("eventType") or payload.get("event") or ""
        ).lower()
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        if event_type in INBOUND_WEBHOOK_EVENTS or (
            not event_type and data.get("payment_status")
        ):
            await self._handle_stanbic_inbound(
                data, raw_payload, event_type or EVENT_PAYMENT_SUCCESS
            )
            return

        if event_type in ACCOUNT_WEBHOOK_EVENTS:
            claimed = await self._claim_event("stanbic", event_type, data, raw_payload)
            if not claimed:
                logger.info("stanbic_webhook_duplicate", webhook_event_type=event_type)
                return
            await self._handle_stanbic_account_event(
                data, activated=event_type == EVENT_ACCOUNT_ACTIVATED
            )
            return

        if event_type in TRANSFER_WEBHOOK_EVENTS:
            claimed = await self._claim_event("stanbic", event_type, data, raw_payload)
            if not claimed:
                logger.info("stanbic_webhook_duplicate", webhook_event_type=event_type)
                return
            if event_type == EVENT_TRANSFER_SUCCESS:
                await self._handle_transfer_success(data)
            elif event_type == EVENT_TRANSFER_FAILED:
                await self._handle_transfer_failed(data)
            elif event_type == EVENT_TRANSFER_REVERSED:
                await self._handle_transfer_reversed(data)
            return

        logger.info("stanbic_webhook_ignored", webhook_event_type=event_type)

    async def _handle_stanbic_inbound(
        self, data: dict[str, Any], raw_payload: bytes, event_type: str
    ) -> None:
        """Credit a customer wallet from an inbound NUBAN transfer (req C1)."""
        payment_status = str(
            data.get("payment_status")
            or data.get("paymentStatus")
            or STANBIC_PAYMENT_STATUS_PAID
        ).upper()
        if payment_status != STANBIC_PAYMENT_STATUS_PAID:
            logger.info("stanbic_inbound_ignored_status", status=payment_status)
            return

        amount = Decimal(str(data.get("amount") or 0))
        reference = str(
            data.get("transaction_reference")
            or data.get("transactionReference")
            or data.get("payment_reference")
            or data.get("paymentReference")
            or ""
        )
        if not reference:
            logger.error("stanbic_inbound_missing_reference")
            return
        if amount <= 0:
            logger.warning("stanbic_inbound_zero_amount", reference=reference)
            return

        account_reference = str(
            data.get("account_reference") or data.get("accountReference") or ""
        )
        account_number = str(
            data.get("destination_account_number")
            or data.get("destinationAccountNumber")
            or data.get("accountNumber")
            or ""
        )

        claimed = await self._claim_event("stanbic", event_type, data, raw_payload)
        if not claimed:
            logger.info("stanbic_webhook_duplicate", webhook_event_type=event_type)
            return

        customer = await self._find_customer_by_account_reference(account_reference)
        if not customer and account_number:
            customer = await self._find_customer_by_dva(account_number)
        if not customer:
            logger.error(
                "stanbic_inbound_customer_not_found",
                reference=reference,
                account_reference=account_reference,
                account_number=account_number[-4:] if account_number else None,
            )
            return

        existing_tx = await self.db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.provider == PaymentProvider.STANBIC,
                PaymentTransaction.provider_reference == reference,
            )
        )
        if existing_tx.scalar_one_or_none():
            return

        wallet = await self.ledger.get_or_create_wallet(customer.id)
        payment_tx = PaymentTransaction(
            provider=PaymentProvider.STANBIC,
            provider_reference=reference,
            provider_transaction_id=reference,
            direction=PaymentDirection.INBOUND,
            channel=PaymentChannel.DVA,
            amount=amount,
            currency=str(data.get("currency") or "NGN"),
            status=TransactionStatus.COMPLETED,
            customer_id=customer.id,
            wallet_id=wallet.id,
            webhook_event=event_type,
            raw_payload=data,
        )
        self.db.add(payment_tx)
        await self.db.flush()

        try:
            await self.ledger.credit_wallet_from_paystack(
                customer_id=customer.id,
                amount=amount,
                idempotency_key=f"wallet_funding:{reference}",
                reference=reference,
                payment_transaction=payment_tx,
                description="Wallet funded via Stanbic transfer",
            )
        except LedgerError as exc:
            logger.error("stanbic_inbound_ledger_failed", reference=reference, error=exc.message)
            payment_tx.status = TransactionStatus.FAILED
            payment_tx.failure_reason = exc.message

    async def _handle_stanbic_account_event(
        self, data: dict[str, Any], *, activated: bool
    ) -> None:
        """Async NUBAN provisioning result (req B1 / section 4)."""
        account_reference = str(
            data.get("account_reference") or data.get("accountReference") or ""
        )
        customer = await self._find_customer_by_account_reference(account_reference)
        if not customer:
            logger.error(
                "stanbic_account_event_customer_not_found",
                account_reference=account_reference,
            )
            return

        wallet = await self.ledger.get_or_create_wallet(customer.id)
        if activated:
            account_number = str(
                data.get("account_number")
                or data.get("accountNumber")
                or data.get("nuban")
                or ""
            )
            if account_number:
                customer.paystack_dva_account_number = account_number
            customer.paystack_dva_bank_name = str(
                data.get("bank_name") or data.get("bankName") or "Stanbic IBTC Bank"
            )
            bank_code = str(data.get("bank_code") or data.get("bankCode") or "")
            if bank_code:
                customer.paystack_dva_bank_slug = bank_code
            wallet.dva_status = DvaStatus.ACTIVE
        else:
            wallet.dva_status = DvaStatus.FAILED
        await self.db.flush()

    async def _handle_monnify_inbound(
        self, data: dict[str, Any], raw_payload: bytes, event_type: str
    ) -> None:
        if data.get("paymentStatus") != PAYMENT_STATUS_PAID:
            return

        product = data.get("product") or {}
        if product.get("type") != PRODUCT_TYPE_RESERVED_ACCOUNT:
            from app.modules.payments.card_funding import CardFundingService

            if str(data.get("paymentReference") or "").startswith("GHT-CARD-"):
                if await self._claim_event("monnify", event_type, data, raw_payload):
                    await CardFundingService(self.db).handle_webhook(data)
                return
            logger.info("monnify_inbound_ignored_product", product_type=product.get("type"))
            return

        amount = Decimal(str(data.get("amountPaid") or 0))
        if amount <= 0:
            logger.warning("monnify_inbound_zero_amount", reference=data.get("paymentReference"))
            return

        reference = str(
            data.get("transactionReference") or data.get("paymentReference") or data.get("reference")
        )
        account_reference = str(product.get("reference") or "")
        account_number = (data.get("destinationAccountInformation") or {}).get("accountNumber")

        claimed = await self._claim_event("monnify", event_type, data, raw_payload)
        if not claimed:
            logger.info("monnify_webhook_duplicate", webhook_event_type=event_type)
            return

        customer = await self._find_customer_by_account_reference(account_reference)
        if not customer and account_number:
            customer = await self._find_customer_by_dva(account_number)
        if not customer:
            logger.error(
                "monnify_inbound_customer_not_found",
                reference=reference,
                account_reference=account_reference,
            )
            return

        provider = _active_provider()
        existing_tx = await self.db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.provider == provider,
                PaymentTransaction.provider_reference == reference,
            )
        )
        if existing_tx.scalar_one_or_none():
            return

        wallet = await self.ledger.get_or_create_wallet(customer.id)
        payment_method = str(data.get("paymentMethod") or "").upper()
        channel = PaymentChannel.DVA
        if "CARD" in payment_method:
            channel = PaymentChannel.CARD

        payment_tx = PaymentTransaction(
            provider=provider,
            provider_reference=reference,
            provider_transaction_id=reference,
            direction=PaymentDirection.INBOUND,
            channel=channel,
            amount=amount,
            currency=data.get("currency") or "NGN",
            status=TransactionStatus.COMPLETED,
            customer_id=customer.id,
            wallet_id=wallet.id,
            webhook_event=event_type,
            raw_payload=data,
        )
        self.db.add(payment_tx)
        await self.db.flush()

        try:
            await self.ledger.credit_wallet_from_paystack(
                customer_id=customer.id,
                amount=amount,
                idempotency_key=f"wallet_funding:{reference}",
                reference=reference,
                payment_transaction=payment_tx,
            )
        except LedgerError as exc:
            logger.error("monnify_inbound_ledger_failed", reference=reference, error=exc.message)
            payment_tx.status = TransactionStatus.FAILED
            payment_tx.failure_reason = exc.message

    async def _handle_monnify_disbursement(
        self, event_type: str, data: dict[str, Any], raw_payload: bytes
    ) -> None:
        claimed = await self._claim_event("monnify", event_type, data, raw_payload)
        if not claimed:
            logger.info("monnify_webhook_duplicate", webhook_event_type=event_type)
            return

        reference = str(data.get("reference") or "")
        if not reference:
            return

        if event_type == DISBURSEMENT_SUCCESS:
            await self._handle_transfer_success(data)
        elif event_type == DISBURSEMENT_FAILED:
            reason = data.get("transactionDescription") or data.get("status") or "Disbursement failed"
            await self._handle_transfer_failed({**data, "reason": reason})
        elif event_type == DISBURSEMENT_REVERSED:
            await self._handle_transfer_reversed(data)

    async def _find_customer_by_account_reference(self, account_reference: str | None) -> Customer | None:
        if not account_reference:
            return None
        result = await self.db.execute(
            select(Customer).where(Customer.paystack_customer_code == account_reference)
        )
        return result.scalar_one_or_none()

    async def _find_customer_by_dva(self, account_number: str | None) -> Customer | None:
        if not account_number:
            return None
        result = await self.db.execute(
            select(Customer).where(Customer.paystack_dva_account_number == account_number)
        )
        return result.scalar_one_or_none()

    async def _handle_charge_success(self, data: dict[str, Any]) -> None:
        if data.get("status") != TRANSACTION_STATUS_SUCCESS:
            return

        amount = kobo_to_naira(int(data.get("amount") or 0))
        if amount <= 0:
            logger.warning("paystack_charge_zero_amount", reference=data.get("reference"))
            return

        reference = str(data.get("reference") or data.get("id"))
        authorization = data.get("authorization") or {}
        account_number = authorization.get("receiver_bank_account_number")

        customer = await self._find_customer_by_dva(account_number)
        if not customer:
            customer_code = (data.get("customer") or {}).get("customer_code")
            if customer_code:
                result = await self.db.execute(
                    select(Customer).where(Customer.paystack_customer_code == customer_code)
                )
                customer = result.scalar_one_or_none()
        if not customer:
            logger.error("paystack_charge_customer_not_found", reference=reference, dva=account_number)
            return

        existing_tx = await self.db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.provider == PaymentProvider.PAYSTACK,
                PaymentTransaction.provider_reference == reference,
            )
        )
        if existing_tx.scalar_one_or_none():
            return

        wallet = await self.ledger.get_or_create_wallet(customer.id)
        channel = PaymentChannel.DVA
        if authorization.get("channel") == "card":
            channel = PaymentChannel.CARD

        payment_tx = PaymentTransaction(
            provider=PaymentProvider.PAYSTACK,
            provider_reference=reference,
            provider_transaction_id=str(data.get("id") or ""),
            direction=PaymentDirection.INBOUND,
            channel=channel,
            amount=Decimal(str(amount)),
            currency=data.get("currency") or "NGN",
            status=TransactionStatus.COMPLETED,
            customer_id=customer.id,
            wallet_id=wallet.id,
            webhook_event="charge.success",
            raw_payload=data,
        )
        self.db.add(payment_tx)
        await self.db.flush()

        try:
            await self.ledger.credit_wallet_from_paystack(
                customer_id=customer.id,
                amount=Decimal(str(amount)),
                idempotency_key=f"wallet_funding:{reference}",
                reference=reference,
                payment_transaction=payment_tx,
            )
        except LedgerError as exc:
            logger.error("paystack_charge_ledger_failed", reference=reference, error=exc.message)
            payment_tx.status = TransactionStatus.FAILED
            payment_tx.failure_reason = exc.message

    async def _handle_dva_assigned(self, data: dict[str, Any]) -> None:
        account_number = data.get("account_number")
        customer_data = data.get("customer") or {}
        customer_code = customer_data.get("customer_code")
        if not customer_code:
            return

        result = await self.db.execute(
            select(Customer).where(Customer.paystack_customer_code == customer_code)
        )
        customer = result.scalar_one_or_none()
        if not customer:
            return

        customer.paystack_dva_account_number = account_number
        bank = data.get("bank") or {}
        customer.paystack_dva_bank_name = bank.get("name")
        customer.paystack_dva_bank_slug = bank.get("slug")

        wallet = await self.ledger.get_or_create_wallet(customer.id)
        wallet.dva_status = DvaStatus.ACTIVE
        await self.db.flush()

    async def _handle_dva_failed(self, data: dict[str, Any]) -> None:
        customer_data = data.get("customer") or {}
        customer_code = customer_data.get("customer_code")
        if not customer_code:
            return
        result = await self.db.execute(
            select(Customer).where(Customer.paystack_customer_code == customer_code)
        )
        customer = result.scalar_one_or_none()
        if not customer:
            return
        wallet = await self.ledger.get_or_create_wallet(customer.id)
        wallet.dva_status = DvaStatus.FAILED
        await self.db.flush()

    async def _get_outbound_payment(self, reference: str) -> PaymentTransaction | None:
        result = await self.db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.provider_reference == reference,
                PaymentTransaction.direction == PaymentDirection.OUTBOUND,
            )
        )
        return result.scalar_one_or_none()

    # -- Outbound transfer outcomes (withdrawals and loan disbursements) ------
    #
    # Shared by every provider's webhook AND by reconciliation, so a missed
    # webhook is settled by exactly the same code path.

    async def _handle_transfer_success(self, data: dict[str, Any]) -> None:
        reference = str(data.get("reference") or "")
        if not reference:
            return

        payment_tx = await self._get_outbound_payment(reference)
        # Loan disbursements. Previously these were only completed when NO
        # PaymentTransaction existed — but initiation always creates one, so a
        # disbursed loan was never marked disbursed, booked, or posted.
        if payment_tx is None or payment_tx.application_id:
            await DisbursementService(self.db).complete(reference, data=data)
            return

        if payment_tx.status == TransactionStatus.COMPLETED:
            return
        payment_tx.status = TransactionStatus.COMPLETED
        payment_tx.webhook_event = payment_tx.webhook_event or "transfer.success"
        payment_tx.raw_payload = data

        withdrawal = await self._withdrawal_for(payment_tx)
        if withdrawal and withdrawal.status != WithdrawalStatus.COMPLETED:
            try:
                await self.ledger.settle_withdrawal_hold(
                    customer_id=withdrawal.customer_id,
                    amount=withdrawal.amount,
                    idempotency_key=f"withdrawal_settle:{reference}",
                    reference=reference,
                    payment_transaction_id=payment_tx.id,
                )
            except LedgerError as exc:
                logger.error("withdrawal_settle_failed", reference=reference, error=exc.message)
                raise
            withdrawal.status = WithdrawalStatus.COMPLETED
            withdrawal.processed_at = datetime.now(timezone.utc)
            await notify.withdrawal_completed(self.db, withdrawal)

    async def _handle_transfer_failed(self, data: dict[str, Any]) -> None:
        reference = str(data.get("reference") or "")
        if not reference:
            return
        reason = str(data.get("reason") or data.get("gateway_response") or "Transfer failed")

        payment_tx = await self._get_outbound_payment(reference)
        if payment_tx is None or payment_tx.application_id:
            await DisbursementService(self.db).fail(reference, reason=reason)
            return

        if payment_tx.status in (TransactionStatus.FAILED, TransactionStatus.REVERSED):
            return
        if payment_tx.status == TransactionStatus.COMPLETED:
            # Failure after success is a reversal, never a silent un-settle.
            await self._reverse_withdrawal(payment_tx, reason)
            return
        payment_tx.status = TransactionStatus.FAILED
        payment_tx.failure_reason = reason
        payment_tx.webhook_event = "transfer.failed"
        await self._release_withdrawal(payment_tx, reason)

    async def _handle_transfer_reversed(self, data: dict[str, Any]) -> None:
        reference = str(data.get("reference") or "")
        if not reference:
            return
        reason = str(data.get("reason") or "Transfer reversed by bank")

        payment_tx = await self._get_outbound_payment(reference)
        if payment_tx is None or payment_tx.application_id:
            await DisbursementService(self.db).reverse(reference, reason=reason)
            return
        if payment_tx.status == TransactionStatus.COMPLETED:
            await self._reverse_withdrawal(payment_tx, reason)
        elif payment_tx.status == TransactionStatus.PENDING:
            payment_tx.status = TransactionStatus.REVERSED
            payment_tx.failure_reason = reason
            await self._release_withdrawal(payment_tx, reason)

    async def _withdrawal_for(self, payment_tx: PaymentTransaction) -> WithdrawalRequest | None:
        if not payment_tx.withdrawal_id:
            return None
        return await self.db.get(WithdrawalRequest, payment_tx.withdrawal_id)

    async def _release_withdrawal(self, payment_tx: PaymentTransaction, reason: str) -> None:
        withdrawal = await self._withdrawal_for(payment_tx)
        if not withdrawal or withdrawal.status in (WithdrawalStatus.FAILED, WithdrawalStatus.COMPLETED):
            return
        await self.ledger.release_withdrawal_hold(
            customer_id=withdrawal.customer_id,
            amount=withdrawal.amount,
            idempotency_key=f"withdrawal_release:{payment_tx.provider_reference}",
            reference=payment_tx.provider_reference,
        )
        withdrawal.status = WithdrawalStatus.FAILED
        withdrawal.failure_reason = reason
        withdrawal.processed_at = datetime.now(timezone.utc)
        await notify.withdrawal_failed(self.db, withdrawal)

    async def _reverse_withdrawal(self, payment_tx: PaymentTransaction, reason: str) -> None:
        """The bank returned money for a withdrawal we had already settled: refund the wallet."""
        payment_tx.status = TransactionStatus.REVERSED
        payment_tx.failure_reason = reason
        withdrawal = await self._withdrawal_for(payment_tx)
        if not withdrawal:
            return
        await self.ledger.refund_settled_withdrawal(
            customer_id=withdrawal.customer_id,
            amount=withdrawal.amount,
            idempotency_key=f"withdrawal_reversal:{payment_tx.provider_reference}",
            reference=payment_tx.provider_reference,
            payment_transaction_id=payment_tx.id,
        )
        withdrawal.status = WithdrawalStatus.FAILED
        withdrawal.failure_reason = f"Reversed after completion: {reason}"
        await notify.withdrawal_failed(self.db, withdrawal)
        logger.warning("withdrawal_reversed_after_settlement", reference=payment_tx.provider_reference)
