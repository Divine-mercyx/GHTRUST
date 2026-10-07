"""
Legal acceptances: the Terms of Use and Privacy Policy, and the loan offer a customer
accepts before a loan is paid out.

The loan offer is the key facts of the approved loan (amount, interest, fees, total to
repay, schedule) plus the loan agreement. What the customer accepts is pinned by a hash
of those terms: if staff change the amount or duration afterwards, the hash no longer
matches and the acceptance is cleared, so a loan is never paid out on terms the customer
didn't see.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.modules.auth.session_service import RequestMeta
from app.modules.legal.documents import DOCUMENTS, LOAN_AGREEMENT_SECTIONS, LOAN_AGREEMENT_VERSION, pending_documents
from app.modules.legal.models import LegalAcceptance
from app.modules.loans.models import LoanApplication
from app.modules.loans.schemas import ApplicationStatus, InterestMethod
from app.modules.loans.servicing import build_schedule, money, validate_terms
from app.modules.users.models import Customer

LOAN_AGREEMENT = "loan_agreement"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def accepted_versions(customer: Customer) -> dict[str, str | None]:
    return {"terms": customer.terms_accepted_version, "privacy": customer.privacy_accepted_version}


def legal_pending(customer: Customer) -> list[str]:
    return pending_documents(accepted_versions(customer))


@dataclass
class OfferLine:
    installment: int
    due_date: date
    amount: Decimal


@dataclass
class LoanOffer:
    application_id: str
    product_name: str
    principal: Decimal
    tenure_months: int
    cadence: str
    installments: int
    interest_rate_pct_monthly: Decimal
    interest_method: str
    total_interest: Decimal
    processing_fee_pct: Decimal
    processing_fee: Decimal
    total_repayable: Decimal
    total_cost_of_credit: Decimal
    late_charge_pct_daily: Decimal | None
    first_payment: Decimal
    schedule: list[OfferLine]
    payout_bank: str | None
    payout_account_masked: str | None
    payout_account_name: str | None
    agreement_version: str
    terms_hash: str
    accepted_at: datetime | None


def _mask(number: str | None) -> str | None:
    return f"•••• {number[-4:]}" if number and len(number) >= 4 else None


class LegalService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Terms / Privacy ──────────────────────────────────────────────────────

    async def accept_documents(
        self, customer: Customer, accepted: dict[str, str], meta: RequestMeta, device_id: str | None = None
    ) -> list[str]:
        """Record acceptance of the given documents at the given versions. Returns what's still pending."""
        now = _now()
        for slug, version in accepted.items():
            document = DOCUMENTS.get(slug)
            if document is None:
                raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", f"No document called '{slug}'")
            if version != document.version:
                # The app showed an older version (it was updated in between): show the new one first.
                raise AppError(
                    status.HTTP_409_CONFLICT,
                    ErrorCode.LEGAL_VERSION_OUTDATED,
                    f"The {document.title} has been updated. Please read the latest version.",
                )
            self._record(customer.id, slug, version, meta, now, device_id=device_id)
            if slug == "terms":
                customer.terms_accepted_version = version
            elif slug == "privacy":
                customer.privacy_accepted_version = version
        await self.db.flush()
        return legal_pending(customer)

    def _record(
        self,
        customer_id: str,
        document: str,
        version: str,
        meta: RequestMeta,
        at: datetime,
        *,
        device_id: str | None = None,
        application_id: str | None = None,
        terms_hash: str | None = None,
    ) -> None:
        self.db.add(
            LegalAcceptance(
                customer_id=customer_id,
                document=document,
                version=version,
                application_id=application_id,
                terms_hash=terms_hash,
                accepted_at=at,
                ip_address=meta.ip,
                user_agent=(meta.user_agent or "")[:255] or None,
                device_id=device_id,
            )
        )

    # ── Loan offer ───────────────────────────────────────────────────────────

    async def _application(self, application_id: str, customer_id: str) -> LoanApplication:
        application = (
            await self.db.execute(
                select(LoanApplication)
                .options(selectinload(LoanApplication.product))
                .where(LoanApplication.id == application_id, LoanApplication.customer_id == customer_id)
            )
        ).scalar_one_or_none()
        if application is None:
            raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Application not found")
        return application

    async def offer_for_customer(self, application_id: str, customer_id: str) -> LoanOffer:
        application = await self._application(application_id, customer_id)
        offerable = (
            ApplicationStatus.OFFER_SENT,
            ApplicationStatus.OFFER_ACCEPTED,
            ApplicationStatus.APPROVED,
            ApplicationStatus.READY_TO_DISBURSE,
            ApplicationStatus.DISBURSED,
        )
        if application.status not in offerable:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.OFFER_NOT_AVAILABLE,
                "There's no loan offer for this application yet. We'll let you know when it's approved.",
            )
        return build_offer(application)

    async def accept_offer(
        self,
        customer: Customer,
        application_id: str,
        *,
        terms_hash: str,
        meta: RequestMeta,
        device_id: str | None = None,
    ) -> LoanOffer:
        """Accept the loan offer. The transaction PIN is checked by the caller first."""
        application = await self._application(application_id, customer.id)
        acceptable = (ApplicationStatus.OFFER_SENT, ApplicationStatus.APPROVED)
        if application.status not in acceptable:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.OFFER_NOT_AVAILABLE,
                "This offer can't be accepted now. Pull down to refresh the application.",
            )
        offer = build_offer(application)
        if application.offer_accepted_at and application.offer_terms_hash == offer.terms_hash:
            if application.status == ApplicationStatus.OFFER_SENT:
                from app.modules.loans.workflow_service import WorkflowService

                await WorkflowService(self.db).resume_after_customer_offer_accept(application)
                await self.db.flush()
            return offer  # accepting twice (a retry) is fine
        if terms_hash != offer.terms_hash:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.OFFER_CHANGED,
                "Your loan offer has changed. Please review the new terms before accepting.",
            )
        now = _now()
        application.offer_accepted_at = now
        application.offer_terms_hash = offer.terms_hash
        self._record(
            customer.id,
            LOAN_AGREEMENT,
            LOAN_AGREEMENT_VERSION,
            meta,
            now,
            device_id=device_id,
            application_id=application.id,
            terms_hash=offer.terms_hash,
        )
        await self.db.flush()
        if application.status == ApplicationStatus.OFFER_SENT:
            from app.modules.loans.workflow_service import WorkflowService

            await WorkflowService(self.db).resume_after_customer_offer_accept(application)
            await self.db.flush()
        offer.accepted_at = now
        return offer

    async def reject_offer(self, customer: Customer, application_id: str) -> None:
        application = await self._application(application_id, customer.id)
        if application.status != ApplicationStatus.OFFER_SENT:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.OFFER_NOT_AVAILABLE,
                "There's no offer waiting for your decision. Pull down to refresh.",
            )
        from app.modules.loans.workflow_service import WorkflowService

        await WorkflowService(self.db).resume_after_customer_offer_reject(application)
        await self.db.flush()


def offer_terms_hash(application: LoanApplication) -> str:
    return build_offer(application).terms_hash


def build_offer(application: LoanApplication, *, start: date | None = None) -> LoanOffer:
    """The approved terms as the customer will see and accept them. Dates assume payout ``start`` (today)."""
    tenure, cadence = validate_terms(application)
    product = application.product
    principal = money(application.approved_amount or application.requested_amount or 0)
    method = product.interest_method or InterestMethod.FLAT
    salary_day = (application.product_data or {}).get("salary_day")
    lines = build_schedule(
        principal=principal,
        monthly_rate_pct=product.interest_rate_pct_monthly,
        tenure_months=tenure,
        cadence=cadence,
        method=method,
        start=start or date.today(),
        salary_day=int(salary_day) if salary_day else None,
    )
    total_interest = sum((line.interest for line in lines), Decimal("0"))
    fee_pct = Decimal(product.processing_fee_pct or 0)
    fee = money(principal * fee_pct / Decimal("100"))
    form = application.universal_form or {}

    terms = {
        "application": application.id,
        "principal": str(principal),
        "tenure_months": tenure,
        "cadence": cadence.value,
        "rate": str(product.interest_rate_pct_monthly),
        "method": getattr(method, "value", str(method)),
        "fee_pct": str(fee_pct),
        "late_pct_daily": str(product.default_penalty_pct_daily) if product.default_penalty_pct_daily else None,
        "bank_code": form.get("bank_code"),
        "account": form.get("bank_account_number"),
        "agreement": LOAN_AGREEMENT_VERSION,
    }
    digest = hashlib.sha256(json.dumps(terms, sort_keys=True).encode()).hexdigest()

    accepted = application.offer_accepted_at if application.offer_terms_hash == digest else None
    return LoanOffer(
        application_id=application.id,
        product_name=product.name,
        principal=principal,
        tenure_months=tenure,
        cadence=cadence.value,
        installments=len(lines),
        interest_rate_pct_monthly=Decimal(product.interest_rate_pct_monthly),
        interest_method=getattr(method, "value", str(method)),
        total_interest=total_interest,
        processing_fee_pct=fee_pct,
        processing_fee=fee,
        total_repayable=principal + total_interest,
        total_cost_of_credit=total_interest + fee,
        late_charge_pct_daily=product.default_penalty_pct_daily,
        first_payment=lines[0].amount,
        schedule=[OfferLine(line.installment, line.due_date, line.amount) for line in lines],
        payout_bank=form.get("bank_name"),
        payout_account_masked=_mask(form.get("bank_account_number")),
        payout_account_name=form.get("bank_account_name"),
        agreement_version=LOAN_AGREEMENT_VERSION,
        terms_hash=digest,
        accepted_at=accepted,
    )


def ensure_offer_accepted(application: LoanApplication) -> None:
    """Disbursement gate: the customer must have accepted the current terms."""
    if not get_settings().loan_offer_acceptance_required:
        return
    if not application.offer_accepted_at or application.offer_terms_hash != offer_terms_hash(application):
        raise AppError(
            status.HTTP_409_CONFLICT,
            ErrorCode.OFFER_NOT_ACCEPTED,
            "The customer hasn't accepted the loan offer yet. They'll see it in the app; "
            "it can be paid out once they accept.",
        )


AGREEMENT_SECTIONS = LOAN_AGREEMENT_SECTIONS
