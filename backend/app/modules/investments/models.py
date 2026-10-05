from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import StrEnum, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.investments.schemas import RiskLevel


class InvestmentPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An investment product staff configure in the portal and customers buy from the wallet."""

    __tablename__ = "investment_plans"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    return_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # % a year, simple interest
    tenure_months: Mapped[int] = mapped_column(Integer)
    risk: Mapped[RiskLevel] = mapped_column(StrEnum(RiskLevel))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True)
    # Picture shown on the plan in the app (uploaded by staff).
    image_base64: Mapped[str | None] = mapped_column(Text, nullable=True, deferred=True)
    image_content_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    image_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomerInvestment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Money a customer put into a plan from their wallet; paid back with returns at maturity."""

    __tablename__ = "customer_investments"
    __table_args__ = (Index("ix_customer_investments_status_maturity", "status", "maturity_date"),)

    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customers.id"), index=True)
    plan_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("investment_plans.id"))
    reference: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    return_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))  # the plan's rate when bought
    start_date: Mapped[date] = mapped_column(Date)
    maturity_date: Mapped[date] = mapped_column(Date)
    projected_return: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | paid_out
    payout_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    paid_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
