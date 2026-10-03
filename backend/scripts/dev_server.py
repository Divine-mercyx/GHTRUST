"""
Self-contained API for mobile / UI development: no Docker, Postgres or Redis.

    python scripts/dev_server.py                 # http://0.0.0.0:8000
    python scripts/dev_server.py --wallet        # also switch the wallet feature on
    python scripts/dev_server.py --reset         # start from an empty database

What you get:
* SQLite file ``dev_local.db`` (kept between runs) + in-memory Redis;
* every provider in mock mode (BVN lookup, SMS, payments);
* OTP codes are always 123456 (also printed in the log);
* loan products and approval workflows seeded;
* a staff login (phone 08000000001) for approving applications in the portal.

Development only: it refuses to start with APP_ENV=production.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEV_OTP = "123456"
DEV_WEBHOOK_SECRET = "dev-monnify-webhook-secret"
DB_FILE = ROOT / "dev_local.db"
STAFF_PHONE = "08000000001"


def _configure_env(wallet: bool) -> None:
    if os.environ.get("APP_ENV") == "production":
        sys.exit("dev_server.py is for development only (APP_ENV=production is set).")
    os.environ.update(
        {
            "APP_ENV": "development",
            "DEBUG": "true",
            "ENABLE_API_DOCS": "true",
            "DOJAH_MOCK": "true",
            "SMS_MOCK": "true",
            "PAYMENT_PROVIDER": "monnify",
            "MONNIFY_MOCK": "true",
            # Lets scripts/dev_credit_wallet.py sign a test "transfer received" webhook.
            "MONNIFY_SECRET_KEY": DEV_WEBHOOK_SECRET,
            "PAYSTACK_MOCK": "true",
            "STANBIC_MOCK": "true",
            "ZEST_MOCK": "true",
            "SENTRY_DSN": "",
            "UPLOAD_DIR": str(ROOT / "uploads"),
            "FEATURE_FLAGS": "wallet"
            if wallet
            else os.environ.get("FEATURE_FLAGS", ""),
            "CORS_ORIGINS": ",".join(
                [
                    "http://localhost:8081",
                    "http://127.0.0.1:8081",
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                ]
            ),
        }
    )


async def _prepare(engine) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.models.registry  # noqa: F401
    from app.models import Base
    from app.modules.admin.service import ensure_super_admin_role, seed_super_admin
    from app.modules.loans.service import seed_loan_products
    from app.modules.loans.workflow_seed import seed_default_workflows

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )() as session:
        await seed_loan_products(session)
        await seed_default_workflows(session)
        await ensure_super_admin_role(session)
        try:
            await seed_super_admin(
                session,
                full_name="Dev Admin",
                email="dev-admin@example.com",
                phone=STAFF_PHONE,
            )
        except Exception:
            await session.rollback()  # already seeded on a previous run
        await session.commit()


def _schema_is_stale() -> bool:
    """create_all only adds missing tables, never columns: an older dev_local.db breaks
    every request that reads a new column. Spot that before starting."""
    import sqlite3
    from contextlib import closing

    import app.models.registry  # noqa: F401
    from app.models import Base

    if not DB_FILE.exists():
        return False
    with closing(sqlite3.connect(DB_FILE)) as conn:
        for table in Base.metadata.sorted_tables:
            have = {row[1] for row in conn.execute(f'PRAGMA table_info("{table.name}")')}
            if have and not {c.name for c in table.columns} <= have:
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--wallet", action="store_true", help="enable the wallet feature flag"
    )
    parser.add_argument(
        "--reset", action="store_true", help="delete the dev database first"
    )
    args = parser.parse_args()

    _configure_env(args.wallet)
    if args.reset and DB_FILE.exists():
        DB_FILE.unlink()
    elif _schema_is_stale():
        backup = DB_FILE.with_suffix(".db.bak")
        DB_FILE.replace(backup)
        print(f"\n  The dev database was built for older code; starting a fresh one (old copy: {backup.name}).")

    import fakeredis.aioredis
    import uvicorn
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from app.core.database import get_db
    from app.core.rate_limit import OtpService
    from app.core.redis import get_redis
    from app.main import create_app

    engine = create_async_engine(f"sqlite+aiosqlite:///{DB_FILE.as_posix()}")
    asyncio.run(_prepare(engine))
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def dev_db():
        async with sessions() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def dev_redis():
        return redis

    OtpService._generate = lambda self: DEV_OTP  # type: ignore[method-assign]

    app = create_app()
    app.dependency_overrides[get_db] = dev_db
    app.dependency_overrides[get_redis] = dev_redis

    print(
        f"\n  GH Trust dev API : http://{args.host}:{args.port}/api/v1  (docs: /docs)\n"
        f"  OTP for every sign-in: {DEV_OTP}  |  staff phone: {STAFF_PHONE}\n"
        f"  wallet feature: {'on' if args.wallet else 'off'}  |  database: {DB_FILE.name}\n"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
