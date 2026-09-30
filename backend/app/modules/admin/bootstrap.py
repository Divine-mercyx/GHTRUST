"""
Accounts the API makes sure exist every time it starts.

The first staff admin (SEED_SUPER_ADMIN_*) and demo customers (DEMO_PHONES) used to be
created only by `python scripts/seed.py`. A host that never ran it (no pre-deploy
command, no shell) booted "healthy" while portal sign-in said "Staff account not found".
Both steps are idempotent, so running them on every start is safe.

Products and loan workflows stay in the seed script.
"""

import structlog
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings

logger = structlog.get_logger()


async def ensure_configured_accounts(session_factory=None) -> None:
    from app.core.database import AsyncSessionLocal
    from app.modules.admin.service import seed_super_admin
    from app.modules.auth.demo_accounts import seed_demo_customers

    s = get_settings()
    admin = (
        s.seed_super_admin_name.strip(),
        s.seed_super_admin_email.strip(),
        s.seed_super_admin_phone.strip(),
    )
    if not all(admin) and not s.demo_phones.strip():
        return

    async with (session_factory or AsyncSessionLocal)() as session:
        try:
            if all(admin):
                name, email, phone = admin
                await seed_super_admin(session, full_name=name, email=email, phone=phone)
            demo = await seed_demo_customers(session)
            await session.commit()
            logger.info("configured_accounts_ready", super_admin=all(admin), demo_customers=len(demo))
        except IntegrityError:
            # Another worker process created the same rows a moment earlier.
            await session.rollback()
        except Exception:
            # Never block start-up over this; the log says what to fix.
            await session.rollback()
            logger.exception("configured_accounts_failed")
