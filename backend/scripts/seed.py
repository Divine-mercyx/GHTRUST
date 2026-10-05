"""
Seed default products and the first super admin.

Idempotent: safe to run on every deploy. Every record is looked up by its
natural key before insert, so re-running never duplicates rows.

Schema is owned by Alembic. Run ``alembic upgrade head`` first; this script
refuses to run against an unmigrated database rather than building tables
itself (the old ``create_all`` path let the schema drift from migrations).
"""

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

# Allow `python scripts/seed.py` without PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.modules.admin.service import seed_super_admin  # noqa: E402
from app.modules.auth.demo_accounts import DemoSeedError, seed_demo_customers  # noqa: E402
from app.modules.food_basket.models import FoodBasketPlan  # noqa: E402
from app.modules.food_basket.schemas import FoodBasketPlanType  # noqa: E402
from app.modules.investments.seed import seed_sample_plans  # noqa: E402
from app.modules.loans.service import seed_loan_products  # noqa: E402
from app.modules.loans.workflow_seed import seed_default_workflows  # noqa: E402
from app.modules.savings.models import SavingsProduct  # noqa: E402
from app.modules.savings.schemas import SavingsProductType  # noqa: E402

SAVINGS_PRODUCTS = [
    dict(name="Yearly Thrift", product_type=SavingsProductType.YEARLY_THRIFT, interest_rate=Decimal("12"), min_deposit=Decimal("5000"), description="12-month locked savings"),
    dict(name="Regular Savings", product_type=SavingsProductType.REGULAR, interest_rate=Decimal("8"), min_deposit=Decimal("1000"), description="Flexible access savings"),
    dict(name="Fixed Savings", product_type=SavingsProductType.FIXED, interest_rate=Decimal("15"), min_deposit=Decimal("50000"), description="Premium fixed deposit"),
    dict(name="Save to Invest", product_type=SavingsProductType.SAVE_TO_INVEST, interest_rate=Decimal("7.5"), min_deposit=Decimal("10000"), description="Interest converts to investment capital"),
]


FOOD_BASKET_PLANS = [
    dict(name="Basic Basket", plan_type=FoodBasketPlanType.BASIC, monthly_price=Decimal("15000"), description="Essential household items", items_included=["Rice 5kg", "Oil 1L", "Tomato paste", "Spaghetti"]),
    dict(name="Standard Basket", plan_type=FoodBasketPlanType.STANDARD, monthly_price=Decimal("25000"), description="Family essentials pack", items_included=["Rice 10kg", "Oil 2L", "Protein", "Vegetables"]),
    dict(name="Premium Basket", plan_type=FoodBasketPlanType.PREMIUM, monthly_price=Decimal("45000"), description="Full household nutrition plan", items_included=["Rice 10kg", "Oil 3L", "Protein", "Vegetables", "Snacks", "Beverages"]),
]


class SeedError(RuntimeError):
    pass


async def ensure_migrated() -> None:
    """Fail fast with a useful message if `alembic upgrade head` hasn't run."""
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    if "alembic_version" not in tables or "customers" not in tables:
        raise SeedError(
            "Database is not migrated. Run `alembic upgrade head` "
            "(or `make migrate-local`) before seeding."
        )


def super_admin_config() -> tuple[str, str, str]:
    settings = get_settings()
    name = settings.seed_super_admin_name.strip()
    email = settings.seed_super_admin_email.strip()
    phone = settings.seed_super_admin_phone.strip()
    missing = [
        var
        for var, value in (
            ("SEED_SUPER_ADMIN_NAME", name),
            ("SEED_SUPER_ADMIN_EMAIL", email),
            ("SEED_SUPER_ADMIN_PHONE", phone),
        )
        if not value
    ]
    if missing:
        raise SeedError(
            "Set " + ", ".join(missing) + " in .env — the first super admin logs in "
            "with an OTP sent to SEED_SUPER_ADMIN_PHONE."
        )
    return name, email, phone


async def _seed_by_name(session, model, rows: list[dict]) -> int:
    created = 0
    for row in rows:
        exists = await session.execute(select(model.id).where(model.name == row["name"]))
        if exists.scalar_one_or_none() is None:
            session.add(model(**row))
            created += 1
    await session.flush()
    return created


async def seed() -> None:
    await ensure_migrated()
    name, email, phone = super_admin_config()

    async with AsyncSessionLocal() as session:
        await seed_super_admin(session, full_name=name, email=email, phone=phone)
        await seed_loan_products(session)
        await seed_default_workflows(session)
        savings = await _seed_by_name(session, SavingsProduct, SAVINGS_PRODUCTS)
        investments = await seed_sample_plans(session)
        food = await _seed_by_name(session, FoodBasketPlan, FOOD_BASKET_PLANS)
        # After the super admin, so a staff number in DEMO_PHONES isn't made a customer.
        demo = await seed_demo_customers(session)
        await session.commit()

    print(
        "Seed complete: super admin, loan products, workflows "
        f"(+{savings} savings, +{investments} investment, +{food} food basket plans)"
    )
    if demo:
        print(f"Demo customers ready: {', '.join(demo)}")


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    except (SeedError, DemoSeedError) as exc:
        print(f"Seed aborted: {exc}", file=sys.stderr)
        sys.exit(1)
