import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.core.deps import DbSession, RedisClient

from app.modules.admin.router import router as admin_router
from app.modules.admin.onboarding import router as admin_onboarding_router
from app.modules.app_config.router import router as app_config_router
from app.modules.auth.account_router import router as auth_account_router
from app.modules.auth.router import router as auth_router
from app.modules.auth.security_router import router as auth_security_router
from app.modules.loans.admin_router import router as admin_loans_router
from app.modules.contributions.router import router as contributions_router
from app.modules.food_basket.router import router as food_basket_router
from app.modules.payments.admin_router import router as admin_payments_router
from app.modules.payments.banks import router as banks_router
from app.modules.legal.router import router as legal_router
from app.modules.notifications.router import router as notifications_router
from app.modules.support.router import router as support_router
from app.modules.payments.router import router as wallet_router
from app.modules.payments.webhook_router import router as paystack_webhook_router
from app.modules.investments.router import router as investments_router
from app.modules.loans.router import router as loans_router
from app.modules.admin.settings_router import router as admin_settings_router
from app.modules.admin.session_router import router as admin_session_router
from app.modules.savings.router import router as savings_router
from app.modules.users.admin_router import router as admin_customers_router

api_v1_router = APIRouter()

api_v1_router.include_router(app_config_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(auth_account_router)
api_v1_router.include_router(auth_security_router)
api_v1_router.include_router(admin_router)
api_v1_router.include_router(admin_settings_router)
api_v1_router.include_router(admin_session_router)
api_v1_router.include_router(admin_customers_router)
api_v1_router.include_router(admin_loans_router)
api_v1_router.include_router(admin_payments_router)
api_v1_router.include_router(admin_onboarding_router)
api_v1_router.include_router(savings_router)
api_v1_router.include_router(loans_router)
api_v1_router.include_router(investments_router)
api_v1_router.include_router(contributions_router)
api_v1_router.include_router(food_basket_router)
api_v1_router.include_router(wallet_router)
api_v1_router.include_router(banks_router)
api_v1_router.include_router(notifications_router)
api_v1_router.include_router(legal_router)
api_v1_router.include_router(support_router)
api_v1_router.include_router(paystack_webhook_router)


@api_v1_router.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy", "service": "ghtrust-mfb-api", "version": __version__}


@api_v1_router.get("/health/ready", tags=["Health"], summary="Readiness: database and Redis reachable")
async def readiness_check(db: DbSession, redis: RedisClient):
    """For load balancers/orchestrators: 503 until this instance can actually serve traffic."""
    checks: dict[str, str] = {}
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=2)
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    try:
        await asyncio.wait_for(redis.ping(), timeout=2)
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks, "version": __version__},
    )
