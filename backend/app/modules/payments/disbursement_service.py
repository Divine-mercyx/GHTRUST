"""
Loan disbursement.

Single home for the disbursement lifecycle, used by the admin API, provider
webhooks, reconciliation and manual (off-rail) recording:

    initiate()  APPROVED → READY_TO_DISBURSE, transfer sent to the rail
    complete()  → DISBURSED, ledger posted, loan + schedule booked (idempotent)
    fail()      → back to APPROVED so staff can retry
    reverse()   → bank reversed a completed transfer; flagged for operations
    record_manual()  money sent outside the rail; recorded, then complete()

Money-safety rules:
* The disbursement + transaction rows are COMMITTED before the provider is
  called. A crash or timeout mid-call can therefore never lose track of a
  transfer the bank may have executed.
* A provider *rejection* marks the attempt FAILED (staff may retry with a new
  reference). A transient failure (timeout / 5xx) means the outcome is UNKNOWN:
  the attempt stays PENDING and reconciliation resolves it by reference.
  Previously any rail error rolled everything back, leaving the application
  APPROVED — so staff could click Disburse again and pay the loan twice.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import structlog
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.demo import blocks_money_out
from app.core.errors import AppError, ErrorCode
from app.integrations.payments.factory import get_payment_client
from app.integrations.payments.schemas import PaymentRailError
from app.models.base import TransactionStatus
from app.modules.admin.models import Staff
from app.modules.loans.audit_service import ApplicationAuditService
from app.modules.loans.document_gate import ensure_documents_verified
from app.modules.loans.models import LoanApplication
from app.modules.loans.schemas import ApplicationStatus
from app.modules.loans.servicing import LoanServicingService, validate_terms
from app.modules.loans.workflow_models import AuditEventType
from app.modules.payments.ledger_service import LedgerError, LedgerService
from app.modules.payments.models import (
    LoanDisbursement,
    PaymentChannel,
    PaymentDirection,
    PaymentProvider,
    PaymentTransaction,
)
from app.modules.users.models import Customer

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


def wallet_payouts_enabled() -> bool:
    """With the wallet switched on (FEATURE_FLAGS=wallet), loans are paid into it."""
    from app.modules.app_config.service import enabled_features

    return enabled_features().get("wallet", False)


def _conflict(message: str, code: str = "CONFLICT") -> AppError:
    return AppError(status.HTTP_409_CONFLICT, code, message)


class DisbursementService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit = ApplicationAuditService(db)
        self._rail = None

    @property
    def rail(self):
        if self._rail is None:
            self._rail = get_payment_client()
        return self._rail

    # ── helpers ─────────────────────────────────────────────────────────────

    async def _by_application(self, application_id: str) -> LoanDisbursement | None:
        return (
            await self.db.execute(
                select(LoanDisbursement).where(LoanDisbursement.application_id == application_id)
            )
        ).scalar_one_or_none()

    async def _by_reference(self, reference: str, *, lock: bool = False) -> LoanDisbursement | None:
        query = select(LoanDisbursement).where(LoanDisbursement.transfer_reference == reference)
        if lock:
            query = query.with_for_update()
        return (await self.db.execute(query)).scalar_one_or_none()

    async def _prepare_attempt(
        self, application: LoanApplication
    ) -> tuple[LoanDisbursement | None, Decimal]:
        if application.status != ApplicationStatus.APPROVED:
            raise _conflict("Only approved applications can be disbursed", ErrorCode.INVALID_STATUS_TRANSITION)
        amount = application.approved_amount or application.requested_amount
        if not amount or amount <= 0:
            raise _conflict("Approved amount is required for disbursement")
        validate_terms(application)  # fail before any money moves
        ensure_documents_verified(application, action="disbursement")
        from app.modules.legal.service import ensure_offer_accepted

        ensure_offer_accepted(application)

        existing = await self._by_application(application.id)
        if existing and existing.status == TransactionStatus.PENDING:
            raise _conflict("A disbursement for this application is already in progress")
        if existing and existing.status in (TransactionStatus.COMPLETED, TransactionStatus.REVERSED):
            raise _conflict("This application has already been disbursed")
        return existing, Decimal(str(amount))

    async def _open_attempt(
        self,
        application: LoanApplication,
        previous: LoanDisbursement | None,
        *,
        amount: Decimal,
        reference: str,
        provider: PaymentProvider,
    ) -> tuple[LoanDisbursement, PaymentTransaction]:
        payment_tx = PaymentTransaction(
            provider=provider,
            provider_reference=reference,
            direction=PaymentDirection.OUTBOUND,
            channel=PaymentChannel.TRANSFER,
            amount=amount,
            currency="NGN",
            status=TransactionStatus.PENDING,
            customer_id=application.customer_id,
            application_id=application.id,
            raw_payload={},
        )
        self.db.add(payment_tx)
        await self.db.flush()

        if previous is not None:
            # Retry after a failed attempt: one row per application (unique), a
            # fresh reference, and the failed attempt's PaymentTransaction kept
            # as history.
            disbursement = previous
            disbursement.transfer_reference = reference
            disbursement.transfer_code = None
            disbursement.recipient_code = None
            disbursement.amount = amount
            disbursement.status = TransactionStatus.PENDING
            disbursement.failure_reason = None
            disbursement.completed_at = None
            disbursement.payment_transaction_id = payment_tx.id
        else:
            disbursement = LoanDisbursement(
                application_id=application.id,
                customer_id=application.customer_id,
                amount=amount,
                transfer_reference=reference,
                status=TransactionStatus.PENDING,
                payment_transaction_id=payment_tx.id,
            )
            self.db.add(disbursement)
        application.status = ApplicationStatus.READY_TO_DISBURSE
        await self.db.flush()
        return disbursement, payment_tx

    # ── initiate (automated rail) ───────────────────────────────────────────

    async def initiate_loan_disbursement(
        self,
        application: LoanApplication,
        staff: Staff,
        *,
        note: str | None = None,
        ip: str | None = None,
    ) -> LoanApplication:
        previous, amount = await self._prepare_attempt(application)
        if wallet_payouts_enabled():
            return await self._disburse_to_wallet(application, previous, amount, staff, note=note, ip=ip)

        form = application.universal_form or {}
        bank_code = form.get("bank_code") or form.get("payout_bank_code")
        account_number = form.get("bank_account_number") or form.get("payout_account_number")
        account_name = form.get("bank_account_name") or form.get("payout_account_name")
        if not bank_code or not account_number:
            raise _conflict("Applicant bank code and account number are required for disbursement")

        customer = await self.db.get(Customer, application.customer_id)
        if not customer:
            raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Customer not found")
        if blocks_money_out(customer.phone_primary):
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.DEMO_ACCOUNT,
                "This application is from a demo account, so it can't be paid out.",
            )

        provider = _active_provider()
        if not account_name:
            try:
                account_name = (
                    await self.rail.validate_bank_account(str(account_number), str(bank_code))
                ).account_name
            except PaymentRailError:
                account_name = customer.full_name

        reference = f"ghtrust_loan_{application.id[:8]}_{uuid4().hex[:12]}"
        disbursement, payment_tx = await self._open_attempt(
            application, previous, amount=amount, reference=reference, provider=provider
        )
        await self.audit.log_staff(
            application.id,
            AuditEventType.DISBURSED,
            staff,
            message=note or f"Loan disbursement initiated via {provider.value.title()}",
            metadata={
                "transfer_reference": reference,
                "amount": str(amount),
                "provider": provider.value,
                "attempt": "retry" if previous else "first",
            },
            ip_address=ip,
        )
        # Durable intent BEFORE money moves.
        await self.db.commit()

        try:
            transfer_code, provider_tx_id, raw, rail_status = await self._send(
                amount=amount,
                reference=reference,
                bank_code=str(bank_code),
                account_number=str(account_number),
                account_name=str(account_name),
                narration=f"GH Trust loan disbursement {application.id[:8]}",
                disbursement=disbursement,
            )
        except PaymentRailError as exc:
            if exc.outcome_unknown:
                logger.warning(
                    "loan_disbursement_outcome_unknown", reference=reference, error=exc.message
                )
                await self.audit.log_system(
                    application.id,
                    AuditEventType.STATUS_CHANGED,
                    message="Disbursement sent; bank response not received. Awaiting confirmation.",
                    metadata={"transfer_reference": reference, "error": exc.message},
                )
                await self.db.commit()
                return application
            await self.fail(reference, reason=exc.message)
            await self.db.commit()
            raise AppError(
                status.HTTP_502_BAD_GATEWAY,
                ErrorCode.PAYMENT_PROVIDER_ERROR,
                f"Disbursement was rejected by the payment provider: {exc.message}",
            ) from exc

        disbursement.transfer_code = transfer_code
        payment_tx.provider_transaction_id = provider_tx_id
        payment_tx.raw_payload = raw
        await self.db.flush()

        # Some rails settle synchronously; don't wait for a webhook that may never come.
        if self._reports_success(rail_status):
            await self.complete(reference, data=raw)

        logger.info(
            "loan_disbursement_initiated",
            application_id=application.id,
            reference=reference,
            amount=str(amount),
            provider=provider.value,
        )
        return application

    async def _disburse_to_wallet(
        self,
        application: LoanApplication,
        previous: LoanDisbursement | None,
        amount: Decimal,
        staff: Staff,
        *,
        note: str | None,
        ip: str | None,
    ) -> LoanApplication:
        """
        Pay the loan into the customer's GH Trust wallet. There's no bank transfer, so it
        settles at once: the ledger moves the amount from the loan book to the wallet and
        the loan is booked. The customer then withdraws to any bank account in the app.
        """
        reference = f"ghtrust_loan_{application.id[:8]}_{uuid4().hex[:12]}"
        await self._open_attempt(
            application, previous, amount=amount, reference=reference, provider=PaymentProvider.WALLET
        )
        await self.audit.log_staff(
            application.id,
            AuditEventType.DISBURSED,
            staff,
            message=note or "Loan paid into the customer's GH Trust wallet",
            metadata={
                "transfer_reference": reference,
                "amount": str(amount),
                "provider": PaymentProvider.WALLET.value,
                "attempt": "retry" if previous else "first",
            },
            ip_address=ip,
        )
        await self.complete(reference)
        logger.info("loan_paid_to_wallet", application_id=application.id, reference=reference, amount=str(amount))
        return application

    def _reports_success(self, rail_status: str) -> bool:
        checker = getattr(self.rail, "is_disbursement_success", None)
        if checker is not None:
            return bool(checker(rail_status))
        return (rail_status or "").lower() == "success"  # Paystack transfer status

    async def _send(
        self,
        *,
        amount: Decimal,
        reference: str,
        bank_code: str,
        account_number: str,
        account_name: str,
        narration: str,
        disbursement: LoanDisbursement,
    ) -> tuple[str | None, str | None, dict, str]:
        if get_settings().active_payment_provider == "paystack":
            from app.integrations.paystack.schemas import (
                CreateTransferRecipientRequest,
                InitiateTransferRequest,
                naira_to_kobo,
            )

            recipient = await self.rail.create_transfer_recipient(
                CreateTransferRecipientRequest(
                    name=account_name, account_number=account_number, bank_code=bank_code
                )
            )
            disbursement.recipient_code = recipient.recipient_code
            transfer = await self.rail.initiate_transfer(
                InitiateTransferRequest(
                    amount=naira_to_kobo(amount),
                    recipient=recipient.recipient_code,
                    reason=narration,
                    reference=reference,
                )
            )
            return (
                transfer.transfer_code,
                str(transfer.id),
                {"transfer_code": transfer.transfer_code, "status": transfer.status},
                str(transfer.status or ""),
            )

        result = await self.rail.initiate_disbursement(
            amount=amount,
            reference=reference,
            bank_code=bank_code,
            account_number=account_number,
            account_name=account_name,
            narration=narration,
        )
        return (
            result.transaction_id,
            result.transaction_id or reference,
            {"status": result.status, "reference": result.reference},
            str(result.status or ""),
        )

    # ── manual (off-rail) ───────────────────────────────────────────────────

    async def record_manual(
        self,
        application: LoanApplication,
        staff: Staff,
        *,
        external_reference: str,
        disbursed_on: date,
        note: str | None = None,
        ip: str | None = None,
    ) -> LoanApplication:
        """Money was sent outside the integrated rail (bank app, branch). Record it."""
        previous, amount = await self._prepare_attempt(application)
        reference = f"manual:{external_reference.strip()}"
        if await self._by_reference(reference):
            raise _conflict("This transfer reference has already been recorded")

        await self._open_attempt(
            application, previous, amount=amount, reference=reference, provider=PaymentProvider.MANUAL
        )
        await self.audit.log_staff(
            application.id,
            AuditEventType.DISBURSED,
            staff,
            message=note or "Manual disbursement recorded",
            metadata={
                "transfer_reference": reference,
                "amount": str(amount),
                "provider": PaymentProvider.MANUAL.value,
                "disbursed_on": disbursed_on.isoformat(),
            },
            ip_address=ip,
        )
        await self.complete(reference, completed_on=disbursed_on)
        return application

    # ── outcome handling (webhooks, reconciliation, sync success) ──────────

    async def complete(
        self,
        reference: str,
        *,
        data: dict | None = None,
        completed_on: date | None = None,
    ) -> bool:
        """Mark a disbursement successful, post the ledger and book the loan. Idempotent."""
        disbursement = await self._by_reference(reference, lock=True)
        if not disbursement:
            return False
        if disbursement.status == TransactionStatus.COMPLETED:
            return True
        if disbursement.status == TransactionStatus.REVERSED:
            logger.warning("loan_disbursement_success_after_reversal", reference=reference)
            return True

        now = datetime.now(timezone.utc)
        disbursement.status = TransactionStatus.COMPLETED
        disbursement.completed_at = now
        if data and data.get("transfer_code"):
            disbursement.transfer_code = data["transfer_code"]
        failure_reason_before = disbursement.failure_reason
        disbursement.failure_reason = None

        to_wallet = False
        if disbursement.payment_transaction_id:
            payment_tx = await self.db.get(PaymentTransaction, disbursement.payment_transaction_id)
            if payment_tx:
                to_wallet = payment_tx.provider == PaymentProvider.WALLET
                payment_tx.status = TransactionStatus.COMPLETED
                payment_tx.webhook_event = payment_tx.webhook_event or (
                    "wallet.credit" if to_wallet else "transfer.success"
                )
                if data:
                    payment_tx.raw_payload = data

        try:
            await LedgerService(self.db).post_loan_disbursement(
                customer_id=disbursement.customer_id,
                amount=disbursement.amount,
                idempotency_key=f"loan_disburse:{reference}",
                reference=reference,
                payment_transaction_id=disbursement.payment_transaction_id,
                to_wallet=to_wallet,
            )
        except LedgerError as exc:
            logger.error("loan_disburse_ledger_failed", reference=reference, error=exc.message)
            raise

        application = await self.db.get(LoanApplication, disbursement.application_id)
        if application is None:
            logger.error("loan_disbursement_application_missing", reference=reference)
            return True
        application.status = ApplicationStatus.DISBURSED
        application.disbursed_at = now

        disbursed_on = completed_on or now.date()
        await LoanServicingService(self.db).book_loan(
            application, principal=disbursement.amount, disbursed_on=disbursed_on, paid_to_wallet=to_wallet
        )
        await self.audit.log_system(
            application.id,
            AuditEventType.DISBURSED,
            message="Disbursement confirmed; loan booked",
            metadata={
                "transfer_reference": reference,
                "amount": str(disbursement.amount),
                "previous_failure": failure_reason_before,
            },
        )
        await self.db.flush()
        logger.info("loan_disbursement_completed", reference=reference, application_id=application.id)
        return True

    async def fail(self, reference: str, *, reason: str) -> bool:
        disbursement = await self._by_reference(reference, lock=True)
        if not disbursement:
            return False
        if disbursement.status == TransactionStatus.COMPLETED:
            # A "failed" after success is a reversal — never silently un-disburse.
            logger.error("loan_disbursement_failed_after_success", reference=reference, reason=reason)
            return True
        if disbursement.status == TransactionStatus.FAILED:
            return True

        disbursement.status = TransactionStatus.FAILED
        disbursement.failure_reason = reason
        if disbursement.payment_transaction_id:
            payment_tx = await self.db.get(PaymentTransaction, disbursement.payment_transaction_id)
            if payment_tx:
                payment_tx.status = TransactionStatus.FAILED
                payment_tx.failure_reason = reason
        application = await self.db.get(LoanApplication, disbursement.application_id)
        if application and application.status == ApplicationStatus.READY_TO_DISBURSE:
            application.status = ApplicationStatus.APPROVED
            await self.audit.log_system(
                application.id,
                AuditEventType.STATUS_CHANGED,
                message=f"Disbursement failed: {reason}. Returned to approved for retry.",
                metadata={"transfer_reference": reference},
            )
        await self.db.flush()
        return True

    async def reverse(self, reference: str, *, reason: str) -> bool:
        disbursement = await self._by_reference(reference, lock=True)
        if not disbursement:
            return False
        if disbursement.status != TransactionStatus.COMPLETED:
            return await self.fail(reference, reason=reason)

        # Funds came back after the loan was booked. Unwinding a live loan is an
        # operational decision (re-send, or cancel the loan and its ledger), so
        # flag it loudly rather than guess.
        disbursement.status = TransactionStatus.REVERSED
        disbursement.failure_reason = reason
        if disbursement.payment_transaction_id:
            payment_tx = await self.db.get(PaymentTransaction, disbursement.payment_transaction_id)
            if payment_tx:
                payment_tx.status = TransactionStatus.REVERSED
                payment_tx.failure_reason = reason
        await self.audit.log_system(
            disbursement.application_id,
            AuditEventType.STATUS_CHANGED,
            message=f"Disbursement REVERSED by bank after completion: {reason}. Manual action required.",
            metadata={"transfer_reference": reference},
        )
        logger.critical("loan_disbursement_reversed_after_completion", reference=reference, reason=reason)
        await self.db.flush()
        return True
