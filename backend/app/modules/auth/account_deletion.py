"""
Customer-initiated account deletion (in the app, or on the web with SMS code + PIN).

What happens (docs/account-deletion.md has the full table and the reasons):

- Refused while money or a loan is still open: an unpaid loan, an application in
  progress, money in the wallet, or a withdrawal on its way.
- Deleted: sign-in sessions are revoked (every access token stops working at once,
  because each request checks its session), push tokens, trusted phones, sign-in
  approvals, notifications, face-check scores, loan drafts and their uploaded files,
  the profile photo and BVN photo, PINs, contact details, address, payout account.
- Kept, de-identified where possible: loans, repayments, wallet and payment records,
  ledger, submitted applications and their documents, signed loan agreements and
  legal acceptances. The Privacy Policy says financial records are kept for at least
  5 years after the relationship ends. When such records exist, the customer row
  keeps only what links them to a person (BVN, name, date of birth, account number);
  without any, those are scrubbed too.
- Support requests keep their reference, category and dates; message text is removed.

The row itself stays (status DELETED, deleted_at set): financial records point at it.
The work runs in one transaction; a retry after a timeout finds the account already
deleted and is refused by authentication (the client treats that as done).
"""

import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import status
from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.demo import is_demo_phone
from app.core.errors import AppError, ErrorCode
from app.modules.auth.models import AuthSession, CustomerDevice, DeviceApproval, SelfieAttempt, SubjectType
from app.modules.auth.session_service import SessionService
from app.modules.contributions.models import ContributionGroup, GroupContribution, GroupMember
from app.modules.food_basket.models import FoodBasketSubscription
from app.modules.investments.models import CustomerInvestment
from app.modules.loans.models import (
    ApplicationCollateral,
    ApplicationDocument,
    ApplicationGuarantor,
    ApplicationStatusLog,
    Loan,
    LoanApplication,
    LoanDraft,
)
from app.modules.loans.schemas import ApplicationStatus, LoanStatus
from app.modules.notifications.models import Notification
from app.modules.payments.models import (
    CustomerWallet,
    LedgerJournal,
    PaymentTransaction,
    WithdrawalRequest,
    WithdrawalStatus,
)
from app.modules.savings.models import SavingsAccount
from app.modules.support.models import SupportMessage, SupportTicket
from app.modules.users.models import Customer, CustomerStatus

logger = structlog.get_logger()

REMOVED_TEXT = "[Removed when the customer deleted their account]"

# Applications that are still being decided or paid out. Drafts are deleted instead;
# disbursed ones are loans (checked separately); the rest have ended.
_IN_PROGRESS = {
    ApplicationStatus.SUBMITTED,
    ApplicationStatus.UNDER_REVIEW,
    ApplicationStatus.DOCUMENTS_INCOMPLETE,
    ApplicationStatus.APPROVED,
    ApplicationStatus.OFFER_SENT,
    ApplicationStatus.OFFER_ACCEPTED,
    ApplicationStatus.PRODUCT_GATE_PENDING,
    ApplicationStatus.PROCESSING_FEE_PAID,
    ApplicationStatus.READY_TO_DISBURSE,
}
# Still owed: active, overdue, or written off (written off is still a debt).
_OWED = {LoanStatus.ACTIVE, LoanStatus.OVERDUE, LoanStatus.WRITTEN_OFF}

LOAN_BLOCK_MESSAGE = (
    "Account deletion cannot be processed while you have an active loan or outstanding repayment "
    "balance. Please settle all pending dues before requesting deletion."
)


@dataclass(frozen=True)
class Blocker:
    code: str
    message: str


@dataclass(frozen=True)
class DeletionResult:
    deleted_at: datetime
    kept_identity: bool  # BVN, name and date of birth kept with retained financial records


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AccountDeletionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Eligibility ─────────────────────────────────────────────────────────

    async def blockers(self, customer: Customer) -> list[Blocker]:
        cid = customer.id
        found: list[Blocker] = []

        owed = await self.db.scalar(
            select(func.count()).select_from(Loan).where(Loan.customer_id == cid, Loan.status.in_(_OWED))
        )
        if owed:
            found.append(Blocker("LOAN_OUTSTANDING", LOAN_BLOCK_MESSAGE))

        in_progress = await self.db.scalar(
            select(func.count())
            .select_from(LoanApplication)
            .where(LoanApplication.customer_id == cid, LoanApplication.status.in_(_IN_PROGRESS))
        )
        if in_progress:
            found.append(
                Blocker(
                    "APPLICATION_IN_PROGRESS",
                    "You have a loan application being reviewed or paid out. Wait for it to finish, or ask "
                    "us to cancel it, before deleting your account.",
                )
            )

        wallet = (
            await self.db.execute(select(CustomerWallet).where(CustomerWallet.customer_id == cid))
        ).scalar_one_or_none()
        if wallet is not None and (wallet.available_balance > 0 or wallet.locked_balance > 0):
            found.append(
                Blocker(
                    "WALLET_NOT_EMPTY",
                    "You still have money in your wallet. Withdraw it to your bank account before deleting "
                    "your account.",
                )
            )

        pending_out = await self.db.scalar(
            select(func.count())
            .select_from(WithdrawalRequest)
            .where(
                WithdrawalRequest.customer_id == cid,
                WithdrawalRequest.status.in_([WithdrawalStatus.PENDING, WithdrawalStatus.PROCESSING]),
            )
        )
        if pending_out:
            found.append(
                Blocker(
                    "WITHDRAWAL_PENDING",
                    "A withdrawal is still on its way to your bank. Try again once it has arrived.",
                )
            )

        # Modules without customer flows yet; if they ever hold money, a person must close them.
        other = await self.db.scalar(
            select(
                or_(
                    exists().where(SavingsAccount.customer_id == cid),
                    exists().where(CustomerInvestment.customer_id == cid),
                    exists().where(GroupMember.customer_id == cid),
                    exists().where(GroupContribution.member_id == cid),
                    exists().where(ContributionGroup.leader_id == cid),
                    exists().where(FoodBasketSubscription.customer_id == cid),
                )
            )
        )
        if other:
            found.append(
                Blocker(
                    "OTHER_PRODUCTS",
                    "You have savings, investments or group plans with us. Contact support to close them "
                    "before deleting your account.",
                )
            )
        return found

    async def ensure_deletable(self, customer: Customer) -> None:
        found = await self.blockers(customer)
        if found:
            raise AppError(
                status.HTTP_409_CONFLICT,
                found[0].code if len(found) == 1 else ErrorCode.ACCOUNT_DELETION_BLOCKED,
                " ".join(b.message for b in found),
                errors=[{"code": b.code, "message": b.message} for b in found],
            )

    # ── Deletion ────────────────────────────────────────────────────────────

    async def delete(self, customer: Customer) -> DeletionResult:
        """Delete and de-identify the account. Commits. Raises 409 if anything is still open."""
        # Lock the row and re-check inside the transaction, so a loan or credit landing at
        # the same moment can't slip past the checks.
        customer = (
            await self.db.execute(select(Customer).where(Customer.id == customer.id).with_for_update())
        ).scalar_one()
        if customer.status == CustomerStatus.DELETED:
            return DeletionResult(customer.deleted_at or _now(), kept_identity=False)
        await self.ensure_deletable(customer)

        cid = customer.id
        now = _now()
        kept_identity = await self._has_financial_records(customer)
        provider_reference = customer.paystack_customer_code or f"ghtrust_{cid}"
        had_reserved_account = bool(customer.paystack_dva_account_number)

        # Sign out everywhere; each request checks its session, so access tokens die now too.
        await SessionService(self.db).revoke_all(
            subject_type=SubjectType.CUSTOMER, subject_id=cid, reason="account_deleted"
        )
        await self.db.execute(
            update(AuthSession)
            .where(AuthSession.subject_type == SubjectType.CUSTOMER, AuthSession.subject_id == cid)
            .values(push_token=None)
        )
        for model in (CustomerDevice, DeviceApproval, SelfieAttempt, Notification, LoanDraft):
            await self.db.execute(delete(model).where(model.customer_id == cid))

        draft_ids = await self._delete_drafts(cid)
        await self._redact_support(cid)
        self._scrub(customer, keep_identity=kept_identity)
        customer.status = CustomerStatus.DELETED
        customer.deleted_at = now
        await self.db.commit()

        # After the commit: files and the payment provider can't be rolled back anyway.
        self._remove_files(draft_ids)
        if had_reserved_account:
            await self._close_reserved_account(cid, provider_reference)
        logger.info("account_deleted", customer_id=cid, kept_identity=kept_identity)
        return DeletionResult(now, kept_identity=kept_identity)

    async def _has_financial_records(self, customer: Customer) -> bool:
        if is_demo_phone(customer.phone_primary):
            return False  # made-up identity: nothing to keep it for
        cid = customer.id
        return bool(
            await self.db.scalar(
                select(
                    or_(
                        exists().where(Loan.customer_id == cid),
                        exists().where(
                            LoanApplication.customer_id == cid, LoanApplication.status != ApplicationStatus.DRAFT
                        ),
                        exists().where(PaymentTransaction.customer_id == cid),
                        exists().where(LedgerJournal.customer_id == cid),
                    )
                )
            )
        )

    async def _delete_drafts(self, customer_id: str) -> list[str]:
        ids = list(
            (
                await self.db.execute(
                    select(LoanApplication.id).where(
                        LoanApplication.customer_id == customer_id, LoanApplication.status == ApplicationStatus.DRAFT
                    )
                )
            ).scalars()
        )
        if ids:
            for model in (ApplicationDocument, ApplicationGuarantor, ApplicationCollateral, ApplicationStatusLog):
                await self.db.execute(delete(model).where(model.application_id.in_(ids)))
            await self.db.execute(delete(LoanApplication).where(LoanApplication.id.in_(ids)))
        return ids

    async def _redact_support(self, customer_id: str) -> None:
        ticket_ids = select(SupportTicket.id).where(SupportTicket.customer_id == customer_id)
        await self.db.execute(
            update(SupportMessage).where(SupportMessage.ticket_id.in_(ticket_ids)).values(body=REMOVED_TEXT)
        )
        await self.db.execute(
            update(SupportTicket)
            .where(SupportTicket.customer_id == customer_id)
            .values(message=REMOVED_TEXT, reply=None, device_name=None)
        )

    @staticmethod
    def _scrub(customer: Customer, *, keep_identity: bool) -> None:
        if not keep_identity:
            # Unique and 11 characters like a BVN, but never a valid one (BVNs are digits).
            customer.bvn = "X" + "".join(secrets.choice("0123456789") for _ in range(10))
            customer.first_name = "Deleted"
            customer.last_name = "Customer"
            customer.date_of_birth = None
        # Frees the number for someone else; unique, fits String(20), never a real phone.
        customer.phone_primary = f"deleted-{secrets.token_hex(6)}"
        for field in (
            "middle_name", "gender", "title", "phone_secondary", "email", "residential_address",
            "state_of_residence", "lga_of_residence", "state_of_origin", "lga_of_origin", "nationality",
            "marital_status", "enrollment_bank", "enrollment_branch", "level_of_account", "name_on_card",
            "bvn_registration_date", "watch_listed", "bvn_photo_base64", "profile_photo_base64",
            "profile_photo_updated_at", "selfie_match_score", "login_pin_hash", "login_pin_set_at",
            "transaction_pin_hash", "transaction_pin_set_at", "transfers_blocked_until",
            "payout_bank_code", "payout_bank_name", "payout_account_number", "payout_account_name",
            "paystack_transfer_recipient_code",
        ):  # fmt: skip
            setattr(customer, field, None)
        customer.login_pin_failed_attempts = 0
        customer.transaction_pin_failed_attempts = 0

    @staticmethod
    def _remove_files(application_ids: list[str]) -> None:
        base = Path(get_settings().upload_dir) / "loan_applications"
        for app_id in application_ids:
            shutil.rmtree(base / app_id, ignore_errors=True)

    @staticmethod
    async def _close_reserved_account(customer_id: str, reference: str) -> None:
        """
        Stop the customer's dedicated account number from receiving money. Only rails with
        an API for it (Monnify, Stanbic) are closed automatically; the log names the rest
        for operations. A failure never undoes the deletion.
        """
        from app.integrations.payments.factory import get_payment_client

        rail = get_payment_client()
        close = getattr(rail, "deactivate_reserved_account", None)
        provider = get_settings().active_payment_provider
        if close is None:
            logger.warning("account_deletion_reserved_account_manual", customer_id=customer_id, provider=provider)
            return
        try:
            await close(reference)
            logger.info("account_deletion_reserved_account_closed", customer_id=customer_id, provider=provider)
        except Exception as exc:  # noqa: BLE001 - logged for operations; deletion stands
            logger.error(
                "account_deletion_reserved_account_failed",
                customer_id=customer_id,
                provider=provider,
                error=type(exc).__name__,
            )
