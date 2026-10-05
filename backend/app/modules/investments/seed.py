"""Sample investment plans so the app has something to show before staff create real ones.

Created only when there are no plans at all: once staff add, edit or switch off plans in
the portal, nothing here touches them. Rates and terms are placeholders, not offers.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.investments.models import InvestmentPlan
from app.modules.investments.schemas import RiskLevel

SAMPLE_PLANS = [
    dict(
        name="Secure Growth Fund",
        min_amount=Decimal("50000"),
        return_rate=Decimal("14"),
        tenure_months=12,
        risk=RiskLevel.LOW,
        description="Sample plan: steady returns from treasury-backed instruments. Paid out after 12 months.",
    ),
    dict(
        name="Balanced Portfolio",
        min_amount=Decimal("100000"),
        return_rate=Decimal("18"),
        tenure_months=18,
        risk=RiskLevel.MEDIUM,
        description="Sample plan: a mix of bonds and commercial paper. Paid out after 18 months.",
    ),
    dict(
        name="High Yield Fund",
        min_amount=Decimal("250000"),
        return_rate=Decimal("24"),
        tenure_months=24,
        risk=RiskLevel.HIGH,
        description="Sample plan: higher returns from SME lending, with more risk. Paid out after 24 months.",
    ),
]


async def seed_sample_plans(db: AsyncSession) -> int:
    if await db.scalar(select(func.count()).select_from(InvestmentPlan)):
        return 0
    db.add_all(InvestmentPlan(**plan) for plan in SAMPLE_PLANS)
    await db.flush()
    return len(SAMPLE_PLANS)
