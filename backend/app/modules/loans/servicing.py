"""
Loan servicing: booking, repayment schedules, repayments, overdue tracking.

Assumptions to confirm with GH Trust's credit team (each is one place to change):

* Interest method defaults to FLAT: total interest = principal x monthly rate
  x tenure months, spread evenly over installments. REDUCING_BALANCE
  (amortising) is supported per product via ``loan_products.interest_method``.
* Tenure → installments: monthly/salary-date = one per month; weekly =
  ceil(months x 30 / 7); daily = months x 30 calendar days.
* Salary-date loans are due monthly on ``product_data.salary_day`` (1–31,
  clamped to month end), else the disbursement day-of-month.
* Allocation: oldest installment first; within an installment, interest
  before principal.
* Interest income is recognised when collected (cash basis).
* No late penalties are charged yet. Products carry
  ``default_penalty_pct_daily`` but the rule (base, cap, compounding) is not
  specified, so installments are only *marked* overdue.
"""

import calendar
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from uuid import uuid4

import structlog
from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError, ErrorCode
from app.modules.loans.models import Loan, LoanApplication, LoanRepayment, RepaymentSchedule
from app.modules.loans.schemas import (
    InstallmentStatus,
    InterestMethod,
    LoanStatus,
    RepaymentCadence,
    RepaymentChannel,
)
from app.modules.notifications import events as notify
from app.modules.payments.ledger_service import LedgerError, LedgerService
from app.modules.payments.models import JournalType, LedgerAccountCode, LedgerDirection

logger = structlog.get_logger()

KOBO = Decimal("0.01")
DAYS_PER_MONTH = 30


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(KOBO, rounding=ROUND_HALF_UP)


# ── Pure schedule math ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScheduleLine:
    installment: int
    due_date: date
    principal: Decimal
    interest: Decimal

    @property
    def amount(self) -> Decimal:
        return self.principal + self.interest


def add_months(start: date, months: int, day: int | None = None) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day or start.day, last_day))


def installment_count(tenure_months: int, cadence: RepaymentCadence) -> int:
    if cadence == RepaymentCadence.WEEKLY:
        return math.ceil(tenure_months * DAYS_PER_MONTH / 7)
    if cadence == RepaymentCadence.DAILY:
        return tenure_months * DAYS_PER_MONTH
    return tenure_months  # monthly, salary_date


def due_dates(
    start: date, count: int, cadence: RepaymentCadence, salary_day: int | None = None
) -> list[date]:
    if cadence == RepaymentCadence.WEEKLY:
        return [date.fromordinal(start.toordinal() + 7 * k) for k in range(1, count + 1)]
    if cadence == RepaymentCadence.DAILY:
        return [date.fromordinal(start.toordinal() + k) for k in range(1, count + 1)]
    day = salary_day if cadence == RepaymentCadence.SALARY_DATE and salary_day else None
    return [add_months(start, k, day) for k in range(1, count + 1)]


def _split_evenly(total: Decimal, parts: int) -> list[Decimal]:
    """Split to the kobo; the last part absorbs rounding so the sum is exact."""
    base = (total / parts).quantize(KOBO, rounding=ROUND_DOWN)
    shares = [base] * parts
    shares[-1] = total - base * (parts - 1)
    return shares


def _periodic_rate(monthly_rate: Decimal, cadence: RepaymentCadence) -> Decimal:
    if cadence == RepaymentCadence.WEEKLY:
        return monthly_rate * 12 / 52
    if cadence == RepaymentCadence.DAILY:
        return monthly_rate * 12 / 365
    return monthly_rate


def build_schedule(
    *,
    principal: Decimal,
    monthly_rate_pct: Decimal,
    tenure_months: int,
    cadence: RepaymentCadence,
    method: InterestMethod,
    start: date,
    salary_day: int | None = None,
) -> list[ScheduleLine]:
    if principal <= 0:
        raise ValueError("principal must be positive")
    if tenure_months < 1:
        raise ValueError("tenure_months must be at least 1")

    principal = money(principal)
    monthly_rate = Decimal(str(monthly_rate_pct)) / 100
    n = installment_count(tenure_months, cadence)
    dates = due_dates(start, n, cadence, salary_day)

    if method == InterestMethod.FLAT or monthly_rate == 0:
        total_interest = money(principal * monthly_rate * tenure_months)
        principals = _split_evenly(principal, n)
        interests = _split_evenly(total_interest, n)
        return [
            ScheduleLine(i + 1, dates[i], principals[i], interests[i]) for i in range(n)
        ]

    # Reducing balance: level (annuity) installment on the declining balance.
    rate = _periodic_rate(monthly_rate, cadence)
    level = money(principal * rate / (1 - (1 + rate) ** -n))
    lines: list[ScheduleLine] = []
    balance = principal
    for i in range(n):
        interest = money(balance * rate)
        if i == n - 1:
            principal_part = balance  # clear the residue exactly
        else:
            principal_part = min(level - interest, balance)
        balance -= principal_part
        lines.append(ScheduleLine(i + 1, dates[i], principal_part, interest))
    return lines


# ── Term resolution ─────────────────────────────────────────────────────────

_PERIOD = re.compile(r"(\d+)\s*(month|mo|week|wk|day)", re.IGNORECASE)


def resolve_tenure_months(application: LoanApplication) -> int | None:
    """Staff-approved tenure, else what the customer entered."""
    if application.approved_tenure_months:
        return application.approved_tenure_months
    product_data = application.product_data or {}
    for key in ("tenure_months", "loan_tenure_months", "duration_months"):
        value = product_data.get(key)
        if value:
            try:
                return max(int(value), 1)
            except (TypeError, ValueError):
                pass
    match = _PERIOD.search(str((application.universal_form or {}).get("repayment_period") or ""))
    if match:
        count, unit = int(match.group(1)), match.group(2).lower()
        if unit.startswith("w"):
            return max(math.ceil(count * 7 / DAYS_PER_MONTH), 1)
        if unit.startswith("d"):
            return max(math.ceil(count / DAYS_PER_MONTH), 1)
        return max(count, 1)
    return None


def resolve_cadence(application: LoanApplication) -> RepaymentCadence:
    if application.repayment_cadence:
        return RepaymentCadence(application.repayment_cadence)
    options = (application.product.repayment_cadence_options or []) if application.product else []
    if len(options) == 1:
        return RepaymentCadence(options[0])
    return RepaymentCadence.MONTHLY


def validate_terms(application: LoanApplication) -> tuple[int, RepaymentCadence]:
    """Terms must be complete before money moves. Raises a client-facing error."""
    tenure = resolve_tenure_months(application)
    if not tenure:
        raise AppError(
            status.HTTP_409_CONFLICT,
            ErrorCode.APPLICATION_INCOMPLETE,
            "Set the approved tenure (months) before disbursing.",
        )
    product = application.product
    if product and product.max_tenure_days and tenure * DAYS_PER_MONTH > product.max_tenure_days:
        raise AppError(
            status.HTTP_409_CONFLICT,
            ErrorCode.APPLICATION_INCOMPLETE,
            f"Tenure of {tenure} months exceeds the product maximum of "
            f"{product.max_tenure_days} days.",
        )
    cadence = resolve_cadence(application)
    allowed = (product.repayment_cadence_options or []) if product else []
    if allowed and cadence.value not in allowed:
        raise AppError(
            status.HTTP_409_CONFLICT,
            ErrorCode.APPLICATION_INCOMPLETE,
            f"Repayment cadence '{cadence.value}' is not offered for this product.",
        )
    return tenure, cadence


# ── Service ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Allocation:
    installment: int
    principal: Decimal
    interest: Decimal


class LoanServicingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.ledger = LedgerService(db)

    async def get_loan(self, loan_id: str, *, customer_id: str | None = None, lock: bool = False) -> Loan:
        query = select(Loan).options(selectinload(Loan.schedule)).where(Loan.id == loan_id)
        if customer_id:
            query = query.where(Loan.customer_id == customer_id)
        if lock:
            query = query.with_for_update()
        loan = (await self.db.execute(query)).scalar_one_or_none()
        if not loan:
            raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Loan not found")
        return loan

    # -- booking --------------------------------------------------------------

    async def book_loan(
        self,
        application: LoanApplication,
        *,
        principal: Decimal,
        disbursed_on: date,
        paid_to_wallet: bool = False,
    ) -> Loan:
        """Create the loan and its schedule. Idempotent per application."""
        existing = (
            await self.db.execute(select(Loan).where(Loan.application_id == application.id))
        ).scalar_one_or_none()
        if existing:
            return existing

        tenure, cadence = validate_terms(application)
        product = application.product
        method = product.interest_method or InterestMethod.FLAT
        salary_day = (application.product_data or {}).get("salary_day")
        lines = build_schedule(
            principal=principal,
            monthly_rate_pct=product.interest_rate_pct_monthly,
            tenure_months=tenure,
            cadence=cadence,
            method=method,
            start=disbursed_on,
            salary_day=int(salary_day) if salary_day else None,
        )
        total_interest = sum((line.interest for line in lines), Decimal("0"))
        principal = money(principal)
        total = principal + total_interest

        loan = Loan(
            customer_id=application.customer_id,
            application_id=application.id,
            product_type=product.code,
            principal=principal,
            disbursed_amount=principal,
            outstanding=total,
            principal_outstanding=principal,
            total_interest=total_interest,
            total_repayable=total,
            amount_paid=Decimal("0"),
            interest_rate=product.interest_rate_pct_monthly,
            interest_method=method,
            repayment_cadence=cadence.value,
            installments_count=len(lines),
            tenure_months=tenure,
            monthly_payment=lines[0].amount,
            status=LoanStatus.ACTIVE,
            disbursement_date=disbursed_on,
            next_due_date=lines[0].due_date,
            branch=application.branch,
        )
        self.db.add(loan)
        await self.db.flush()
        for line in lines:
            self.db.add(
                RepaymentSchedule(
                    loan_id=loan.id,
                    installment=line.installment,
                    due_date=line.due_date,
                    amount=line.amount,
                    principal=line.principal,
                    interest=line.interest,
                    status=InstallmentStatus.PENDING,
                )
            )
        await self.db.flush()
        logger.info(
            "loan_booked",
            loan_id=loan.id,
            application_id=application.id,
            principal=str(principal),
            installments=len(lines),
            method=method.value,
        )
        await notify.loan_disbursed(self.db, loan, to_wallet=paid_to_wallet)
        return loan

    # -- repayments -----------------------------------------------------------

    @staticmethod
    def allocate(schedule: list[RepaymentSchedule], amount: Decimal) -> list[Allocation]:
        """Oldest installment first; interest before principal within each."""
        remaining = amount
        allocations: list[Allocation] = []
        for line in sorted(schedule, key=lambda s: s.installment):
            if remaining <= 0:
                break
            interest_due = line.interest - line.interest_paid
            principal_due = line.principal - line.principal_paid
            if interest_due + principal_due <= 0:
                continue
            to_interest = min(remaining, interest_due)
            remaining -= to_interest
            to_principal = min(remaining, principal_due)
            remaining -= to_principal
            if to_interest or to_principal:
                allocations.append(Allocation(line.installment, to_principal, to_interest))
        return allocations

    async def record_repayment(
        self,
        loan_id: str,
        *,
        amount: Decimal,
        channel: RepaymentChannel,
        reference: str,
        paid_at: datetime | None = None,
        customer_id: str | None = None,
        staff_id: str | None = None,
        note: str | None = None,
    ) -> LoanRepayment:
        amount = money(amount)
        if amount <= 0:
            raise AppError(status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "Amount must be positive")

        # Idempotency: the same reference is the same payment.
        prior = (
            await self.db.execute(select(LoanRepayment).where(LoanRepayment.reference == reference))
        ).scalar_one_or_none()
        if prior:
            if prior.loan_id != loan_id or prior.amount != amount:
                raise AppError(
                    status.HTTP_409_CONFLICT,
                    ErrorCode.IDEMPOTENCY_KEY_REUSED,
                    "This payment reference was already used for a different repayment.",
                )
            return prior

        loan = await self.get_loan(loan_id, customer_id=customer_id, lock=True)
        if loan.status in (LoanStatus.COMPLETED, LoanStatus.WRITTEN_OFF):
            raise AppError(
                status.HTTP_409_CONFLICT, ErrorCode.LOAN_NOT_REPAYABLE, f"Loan is {loan.status.value}."
            )
        if amount > loan.outstanding:
            raise AppError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ErrorCode.LOAN_NOT_REPAYABLE,
                f"Amount exceeds the outstanding balance of {loan.outstanding}.",
            )

        allocations = self.allocate(list(loan.schedule), amount)
        principal_total = sum((a.principal for a in allocations), Decimal("0"))
        interest_total = sum((a.interest for a in allocations), Decimal("0"))
        paid_at = paid_at or datetime.now(timezone.utc)

        journal = await self._post_repayment_journal(
            loan,
            amount=amount,
            principal=principal_total,
            interest=interest_total,
            channel=channel,
            reference=reference,
        )

        by_installment = {line.installment: line for line in loan.schedule}
        for a in allocations:
            line = by_installment[a.installment]
            line.principal_paid += a.principal
            line.interest_paid += a.interest
            if line.amount_due <= 0:
                line.status = InstallmentStatus.PAID
                line.paid_at = paid_at
            else:
                line.status = InstallmentStatus.PARTIAL

        loan.amount_paid += amount
        loan.outstanding -= amount
        loan.principal_outstanding -= principal_total
        self._refresh_status(loan, date.today())

        repayment = LoanRepayment(
            loan_id=loan.id,
            customer_id=loan.customer_id,
            amount=amount,
            principal_amount=principal_total,
            interest_amount=interest_total,
            channel=channel,
            reference=reference,
            paid_at=paid_at,
            recorded_by_staff_id=staff_id,
            note=note,
            allocation=[
                {"installment": a.installment, "principal": str(a.principal), "interest": str(a.interest)}
                for a in allocations
            ],
            journal_id=journal.id,
        )
        self.db.add(repayment)
        try:
            await self.db.flush()
        except IntegrityError as exc:  # concurrent request with the same reference
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.IDEMPOTENCY_IN_PROGRESS,
                "This repayment is already being processed.",
            ) from exc
        logger.info("loan_repayment_recorded", loan_id=loan.id, amount=str(amount), channel=channel.value)
        # Wallet repayments are made in the app; anything else (transfer, cash) gets a confirmation.
        if channel != RepaymentChannel.WALLET:
            await notify.repayment_received(self.db, loan, amount=amount, repayment_id=repayment.id)
        return repayment

    async def _post_repayment_journal(
        self,
        loan: Loan,
        *,
        amount: Decimal,
        principal: Decimal,
        interest: Decimal,
        channel: RepaymentChannel,
        reference: str,
    ):
        credits = []
        if principal > 0:
            credits.append((LedgerAccountCode.LOAN_RECEIVABLE, LedgerDirection.CREDIT, principal))
        if interest > 0:
            credits.append((LedgerAccountCode.INTEREST_INCOME, LedgerDirection.CREDIT, interest))
        try:
            if channel == RepaymentChannel.WALLET:
                return await self.ledger.debit_wallet(
                    customer_id=loan.customer_id,
                    amount=amount,
                    journal_type=JournalType.LOAN_REPAYMENT,
                    idempotency_key=f"loan_repayment:{reference}",
                    reference=reference,
                    credits=credits,
                    description=f"Loan repayment {loan.id[:8]} from wallet",
                )
            journal, _ = await self.ledger.post_journal(
                idempotency_key=f"loan_repayment:{reference}",
                journal_type=JournalType.LOAN_REPAYMENT,
                customer_id=loan.customer_id,
                reference=reference,
                description=f"Loan repayment {loan.id[:8]} via {channel.value}",
                entries=[(LedgerAccountCode.PAYSTACK_SETTLEMENT, LedgerDirection.DEBIT, amount), *credits],
            )
            return journal
        except LedgerError as exc:
            code = ErrorCode.INSUFFICIENT_FUNDS if exc.status_code == 409 else "LEDGER_ERROR"
            raise AppError(exc.status_code, code, exc.message) from exc

    # -- status ---------------------------------------------------------------

    @staticmethod
    def _refresh_status(loan: Loan, today: date) -> None:
        unpaid = [line for line in loan.schedule if line.amount_due > 0]
        if not unpaid or loan.outstanding <= 0:
            loan.status = LoanStatus.COMPLETED
            loan.next_due_date = None
            loan.outstanding = Decimal("0")
            loan.closed_at = loan.closed_at or datetime.now(timezone.utc)
            return
        overdue = False
        for line in unpaid:
            if line.due_date < today:
                line.status = InstallmentStatus.OVERDUE
                overdue = True
        loan.next_due_date = min(line.due_date for line in unpaid)
        if loan.status != LoanStatus.WRITTEN_OFF:
            loan.status = LoanStatus.OVERDUE if overdue else LoanStatus.ACTIVE

    async def refresh_open_loans(self, today: date | None = None, *, batch: int = 500) -> int:
        """Daily job: mark overdue installments and roll next_due_date forward.

        Pages through every open loan by id (keyset), so the whole book is
        processed regardless of size without holding it all in memory.
        """
        today = today or date.today()
        processed = 0
        last_id: str | None = None
        while True:
            query = (
                select(Loan)
                .options(selectinload(Loan.schedule))
                .where(Loan.status.in_((LoanStatus.ACTIVE, LoanStatus.OVERDUE)))
                .order_by(Loan.id)
                .limit(batch)
            )
            if last_id:
                query = query.where(Loan.id > last_id)
            loans = (await self.db.execute(query)).scalars().all()
            if not loans:
                break
            for loan in loans:
                self._refresh_status(loan, today)
            await self.db.flush()
            processed += len(loans)
            last_id = loans[-1].id
        return processed


def new_reference(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


# ── Read models for the API ─────────────────────────────────────────────────


async def list_loans(
    db: AsyncSession,
    *,
    customer_id: str | None = None,
    status_filter: LoanStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Loan], int]:
    from sqlalchemy import func

    from app.modules.users.models import Customer
    from app.modules.users.search import customer_search_clause

    conditions = []
    if search and search.strip():
        conditions.append(Loan.customer_id.in_(select(Customer.id).where(customer_search_clause(search))))
    if customer_id:
        conditions.append(Loan.customer_id == customer_id)
    if status_filter:
        conditions.append(Loan.status == status_filter)
    total = await db.scalar(select(func.count()).select_from(Loan).where(*conditions))
    rows = (
        await db.execute(
            select(Loan).where(*conditions).order_by(Loan.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(rows), int(total or 0)


async def loan_responses(db: AsyncSession, loans: list[Loan]):
    """LoanResponse rows with borrower names, fetched in one query for the page."""
    from app.modules.loans.schemas import LoanResponse
    from app.modules.users.models import Customer

    ids = {loan.customer_id for loan in loans}
    names: dict[str, str] = {}
    if ids:
        rows = await db.execute(
            select(Customer.id, Customer.first_name, Customer.middle_name, Customer.last_name).where(
                Customer.id.in_(ids)
            )
        )
        names = {
            cid: " ".join(p for p in (first, middle, last) if p) for cid, first, middle, last in rows.all()
        }
    return [
        LoanResponse.model_validate(loan).model_copy(update={"customer_name": names.get(loan.customer_id)})
        for loan in loans
    ]


async def loan_detail(db: AsyncSession, loan_id: str, *, customer_id: str | None = None):
    from app.modules.loans.schemas import (
        LoanDetailResponse,
        LoanRepaymentResponse,
        RepaymentScheduleItem,
    )

    loan = await LoanServicingService(db).get_loan(loan_id, customer_id=customer_id)
    repayments = (
        await db.execute(
            select(LoanRepayment).where(LoanRepayment.loan_id == loan.id).order_by(LoanRepayment.paid_at)
        )
    ).scalars().all()
    (summary,) = await loan_responses(db, [loan])
    return LoanDetailResponse(
        **summary.model_dump(),
        schedule=[RepaymentScheduleItem.model_validate(line) for line in loan.schedule],
        repayments=[LoanRepaymentResponse.model_validate(r) for r in repayments],
    )
