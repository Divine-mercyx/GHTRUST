"""
Investments: customers put wallet money into a plan staff configure, and get it back with
returns at maturity.

Rules (defaults until GH Trust's product rules say otherwise; see docs/investments.md):
- Returns are simple interest at the plan's yearly rate: amount x rate x months / 12,
  fixed when the customer invests (later rate changes don't touch existing investments).
- The money is locked until maturity; there is no early withdrawal.
- At maturity a daily job pays the amount plus returns into the wallet.

Ledger: investing debits the wallet and credits investment_principal; the payout debits
investment_principal and investment_return_expense and credits the wallet.
"""

import base64
import binascii
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import structlog
from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.investments.models import CustomerInvestment, InvestmentPlan
from app.modules.investments.schemas import (
    AdminHoldingResponse,
    AdminHoldingsPage,
    AdminPlanResponse,
    CreatePlanRequest,
    InvestmentCalculatorRequest,
    InvestmentCalculatorResponse,
    InvestmentPlanResponse,
    InvestmentResponse,
    UpdatePlanRequest,
)
from app.modules.loans.servicing import add_months
from app.modules.payments.ledger_service import LedgerError, LedgerService

logger = structlog.get_logger()

ACTIVE = "active"
PAID_OUT = "paid_out"
MAX_IMAGE_BYTES = 2 * 1024 * 1024
CENT = Decimal("0.01")


def projected_return(amount: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    return (amount * annual_rate / Decimal(100) * Decimal(months) / Decimal(12)).quantize(CENT, ROUND_HALF_UP)


def _image_url(plan: InvestmentPlan) -> str | None:
    if not plan.image_updated_at:
        return None
    return f"/api/v1/investments/plans/{plan.id}/image?v={int(plan.image_updated_at.timestamp())}"


def _plan(plan: InvestmentPlan) -> InvestmentPlanResponse:
    return InvestmentPlanResponse(
        id=plan.id,
        name=plan.name,
        min_amount=plan.min_amount,
        max_amount=plan.max_amount,
        return_rate=plan.return_rate,
        tenure_months=plan.tenure_months,
        risk=plan.risk,
        description=plan.description,
        is_active=plan.is_active,
        image_url=_image_url(plan),
    )


def _holding(inv: CustomerInvestment, plan: InvestmentPlan) -> InvestmentResponse:
    return InvestmentResponse(
        id=inv.id,
        reference=inv.reference,
        plan_id=plan.id,
        plan_name=plan.name,
        image_url=_image_url(plan),
        amount=inv.amount,
        return_rate=inv.return_rate,
        start_date=inv.start_date,
        maturity_date=inv.maturity_date,
        projected_return=inv.projected_return,
        maturity_value=inv.amount + inv.projected_return,
        status=inv.status,
        paid_out_at=inv.paid_out_at,
    )


def decode_image(image: str) -> tuple[str, bytes]:
    image = (image or "").strip()
    if image.startswith("data:"):
        image = image.split(",", 1)[-1]
    try:
        raw = base64.b64decode(image, validate=True)
    except (binascii.Error, ValueError):
        raw = b""
    if raw.startswith(b"\xff\xd8\xff"):
        kind = "image/jpeg"
    elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
        kind = "image/png"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        kind = "image/webp"
    else:
        kind = ""
    if not kind or not 500 <= len(raw) <= MAX_IMAGE_BYTES:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "IMAGE_INVALID", "Upload a JPG, PNG or WebP image under 2 MB."
        )
    return kind, raw


class InvestmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Customers ───────────────────────────────────────────────────────────

    async def list_plans(self) -> list[InvestmentPlanResponse]:
        result = await self.db.execute(
            select(InvestmentPlan).where(InvestmentPlan.is_active.is_(True)).order_by(InvestmentPlan.tenure_months)
        )
        return [_plan(p) for p in result.scalars().all()]

    async def plan_image(self, plan_id: str) -> tuple[str, bytes] | None:
        row = (
            await self.db.execute(
                select(InvestmentPlan.image_base64, InvestmentPlan.image_content_type).where(InvestmentPlan.id == plan_id)
            )
        ).first()
        if not row or not row[0]:
            return None
        return row[1] or "image/jpeg", base64.b64decode(row[0])

    async def list_customer_investments(self, customer_id: str) -> list[InvestmentResponse]:
        result = await self.db.execute(
            select(CustomerInvestment, InvestmentPlan)
            .join(InvestmentPlan, InvestmentPlan.id == CustomerInvestment.plan_id)
            .where(CustomerInvestment.customer_id == customer_id)
            .order_by(CustomerInvestment.created_at.desc())
        )
        return [_holding(inv, plan) for inv, plan in result.all()]

    @staticmethod
    def calculate(payload: InvestmentCalculatorRequest) -> InvestmentCalculatorResponse:
        projected = projected_return(payload.amount, payload.annual_rate, payload.tenure_months)
        return InvestmentCalculatorResponse(
            amount=payload.amount,
            tenure_months=payload.tenure_months,
            projected_return=projected,
            maturity_value=payload.amount + projected,
        )

    async def invest(self, customer_id: str, plan_id: str, amount: Decimal) -> InvestmentResponse:
        """Debit the wallet and start the investment. The caller has checked the transaction PIN."""
        plan = await self.db.get(InvestmentPlan, plan_id)
        if plan is None or not plan.is_active:
            raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "This investment isn't available.")
        amount = amount.quantize(CENT)
        if amount < plan.min_amount:
            raise AppError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "AMOUNT_TOO_SMALL",
                f"The minimum for {plan.name} is ₦{plan.min_amount:,.2f}.",
            )
        if plan.max_amount is not None and amount > plan.max_amount:
            raise AppError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "AMOUNT_TOO_LARGE",
                f"The maximum for {plan.name} is ₦{plan.max_amount:,.2f}.",
            )

        today = date.today()
        reference = f"INV-{secrets.token_hex(5).upper()}"
        try:
            await LedgerService(self.db).invest_from_wallet(
                customer_id=customer_id, amount=amount, idempotency_key=f"investment:{reference}", reference=reference
            )
        except LedgerError as exc:
            if exc.status_code == 409:
                raise AppError(
                    status.HTTP_409_CONFLICT,
                    "INSUFFICIENT_FUNDS",
                    "There isn't enough money in your wallet. Add money, then try again.",
                ) from exc
            raise
        investment = CustomerInvestment(
            customer_id=customer_id,
            plan_id=plan.id,
            reference=reference,
            amount=amount,
            return_rate=plan.return_rate,
            start_date=today,
            maturity_date=add_months(today, plan.tenure_months),
            projected_return=projected_return(amount, plan.return_rate, plan.tenure_months),
            status=ACTIVE,
        )
        self.db.add(investment)
        await self.db.flush()

        from app.modules.notifications import events as notify

        await notify.investment_started(self.db, investment, plan.name)
        logger.info("investment_started", investment_id=investment.id, plan_id=plan.id, amount=str(amount))
        return _holding(investment, plan)

    async def pay_out_matured(self, today: date | None = None, limit: int = 200) -> int:
        """Pay matured investments into wallets. Safe to run repeatedly (idempotent per investment)."""
        today = today or date.today()
        rows = (
            await self.db.execute(
                select(CustomerInvestment, InvestmentPlan.name)
                .join(InvestmentPlan, InvestmentPlan.id == CustomerInvestment.plan_id)
                .where(CustomerInvestment.status == ACTIVE, CustomerInvestment.maturity_date <= today)
                .order_by(CustomerInvestment.maturity_date)
                .limit(limit)
                .with_for_update(of=CustomerInvestment, skip_locked=True)
            )
        ).all()
        from app.modules.notifications import events as notify

        for inv, plan_name in rows:
            await LedgerService(self.db).pay_out_investment(
                customer_id=inv.customer_id,
                principal=inv.amount,
                returns=inv.projected_return,
                idempotency_key=f"investment_payout:{inv.id}",
                reference=inv.reference or inv.id,
            )
            inv.status = PAID_OUT
            inv.payout_amount = inv.amount + inv.projected_return
            inv.paid_out_at = datetime.now(timezone.utc)
            await notify.investment_matured(self.db, inv, plan_name)
            logger.info("investment_paid_out", investment_id=inv.id, amount=str(inv.payout_amount))
        await self.db.flush()
        return len(rows)

    # ── Staff ───────────────────────────────────────────────────────────────

    async def admin_plans(self) -> list[AdminPlanResponse]:
        stats = (
            select(
                CustomerInvestment.plan_id,
                func.count().label("investors"),
                func.coalesce(func.sum(CustomerInvestment.amount), 0).label("amount"),
            )
            .where(CustomerInvestment.status == ACTIVE)
            .group_by(CustomerInvestment.plan_id)
            .subquery()
        )
        rows = await self.db.execute(
            select(InvestmentPlan, stats.c.investors, stats.c.amount)
            .outerjoin(stats, stats.c.plan_id == InvestmentPlan.id)
            .order_by(InvestmentPlan.is_active.desc(), InvestmentPlan.tenure_months)
        )
        return [
            AdminPlanResponse(
                **_plan(plan).model_dump(),
                active_investors=investors or 0,
                active_amount=Decimal(amount or 0),
                created_at=plan.created_at,
            )
            for plan, investors, amount in rows.all()
        ]

    async def _admin_plan(self, plan_id: str) -> AdminPlanResponse:
        for p in await self.admin_plans():
            if p.id == plan_id:
                return p
        raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Plan not found")

    async def create_plan(self, payload: CreatePlanRequest) -> AdminPlanResponse:
        plan = InvestmentPlan(**payload.model_dump())
        self.db.add(plan)
        await self.db.flush()
        return await self._admin_plan(plan.id)

    async def update_plan(self, plan_id: str, payload: UpdatePlanRequest) -> AdminPlanResponse:
        plan = await self.db.get(InvestmentPlan, plan_id)
        if plan is None:
            raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Plan not found")
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            if key in {"name", "min_amount", "return_rate", "tenure_months", "risk", "is_active"} and value is None:
                continue  # required fields can't be cleared
            setattr(plan, key, value)
        if plan.max_amount is not None and plan.max_amount < plan.min_amount:
            raise AppError(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "The maximum must be at least the minimum."
            )
        await self.db.flush()
        return await self._admin_plan(plan.id)

    async def set_image(self, plan_id: str, image: str | None) -> AdminPlanResponse:
        plan = await self.db.get(InvestmentPlan, plan_id)
        if plan is None:
            raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Plan not found")
        if image is None:
            plan.image_base64 = plan.image_content_type = plan.image_updated_at = None
        else:
            kind, raw = decode_image(image)
            plan.image_base64 = base64.b64encode(raw).decode()
            plan.image_content_type = kind
            plan.image_updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return await self._admin_plan(plan.id)

    async def holdings(self, *, status_filter: str | None, limit: int, offset: int) -> AdminHoldingsPage:
        from app.modules.users.models import Customer

        query = (
            select(CustomerInvestment, InvestmentPlan.name, Customer)
            .join(InvestmentPlan, InvestmentPlan.id == CustomerInvestment.plan_id)
            .join(Customer, Customer.id == CustomerInvestment.customer_id)
        )
        count = select(func.count()).select_from(CustomerInvestment)
        if status_filter:
            query = query.where(CustomerInvestment.status == status_filter)
            count = count.where(CustomerInvestment.status == status_filter)
        rows = (
            await self.db.execute(query.order_by(CustomerInvestment.created_at.desc()).limit(limit).offset(offset))
        ).all()
        active_amount = await self.db.scalar(
            select(func.coalesce(func.sum(CustomerInvestment.amount), 0)).where(CustomerInvestment.status == ACTIVE)
        )
        due_soon = await self.db.scalar(
            select(
                func.coalesce(func.sum(CustomerInvestment.amount + CustomerInvestment.projected_return), 0)
            ).where(
                CustomerInvestment.status == ACTIVE,
                CustomerInvestment.maturity_date <= date.today() + timedelta(days=30),
            )
        )
        return AdminHoldingsPage(
            items=[
                AdminHoldingResponse(
                    id=inv.id,
                    reference=inv.reference,
                    customer_id=inv.customer_id,
                    customer_name=customer.full_name,
                    plan_name=plan_name,
                    amount=inv.amount,
                    return_rate=inv.return_rate,
                    projected_return=inv.projected_return,
                    start_date=inv.start_date,
                    maturity_date=inv.maturity_date,
                    status=inv.status,
                    paid_out_at=inv.paid_out_at,
                )
                for inv, plan_name, customer in rows
            ],
            total=await self.db.scalar(count) or 0,
            active_amount=Decimal(active_amount or 0),
            due_in_30_days=Decimal(due_soon or 0),
        )
