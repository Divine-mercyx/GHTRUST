from fastapi import APIRouter, Depends, Query, Response, status

from app.core.deps import CurrentCustomer, DbSession
from app.core.errors import AppError
from app.modules.admin.deps import require_permission
from app.modules.admin.models import Staff
from app.modules.admin.permissions import INVESTMENT_MANAGE, INVESTMENT_READ
from app.modules.auth.security_service import SecurityService
from app.modules.investments.schemas import (
    AdminHoldingsPage,
    AdminPlanResponse,
    CreatePlanRequest,
    InvestmentCalculatorRequest,
    InvestmentCalculatorResponse,
    InvestmentPlanResponse,
    InvestmentResponse,
    InvestRequest,
    PlanImageRequest,
    UpdatePlanRequest,
)
from app.modules.investments.service import InvestmentService

router = APIRouter(prefix="/investments", tags=["Investments"])
admin_router = APIRouter(prefix="/admin/investments", tags=["Admin — Investments"])


def _ensure_enabled() -> None:
    from app.modules.app_config.service import enabled_features

    if not enabled_features().get("investments"):
        raise AppError(status.HTTP_403_FORBIDDEN, "FEATURE_DISABLED", "Investments aren't available yet.")


@router.get("/plans", response_model=list[InvestmentPlanResponse])
async def list_investment_plans(db: DbSession):
    return await InvestmentService(db).list_plans()


@router.get("/plans/{plan_id}/image", summary="A plan's picture")
async def plan_image(plan_id: str, db: DbSession) -> Response:
    found = await InvestmentService(db).plan_image(plan_id)
    if found is None:
        raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "No image")
    content_type, raw = found
    # The URL carries ?v=<changed at>, so a new picture is a new URL.
    return Response(content=raw, media_type=content_type, headers={"Cache-Control": "public, max-age=604800"})


@router.post("/calculator", response_model=InvestmentCalculatorResponse)
async def investment_calculator(payload: InvestmentCalculatorRequest):
    return InvestmentService.calculate(payload)


@router.get("/me", response_model=list[InvestmentResponse])
async def list_my_investments(db: DbSession, customer: CurrentCustomer):
    return await InvestmentService(db).list_customer_investments(customer.id)


@router.post("/me", response_model=InvestmentResponse, status_code=status.HTTP_201_CREATED)
async def create_my_investment(payload: InvestRequest, db: DbSession, customer: CurrentCustomer):
    """Invest wallet money in a plan. Needs the transaction PIN; send an Idempotency-Key."""
    _ensure_enabled()
    await SecurityService(db).authorize_transaction(customer, payload.transaction_pin)
    return await InvestmentService(db).invest(customer.id, payload.plan_id, payload.amount)


# ── Staff ────────────────────────────────────────────────────────────────────


@admin_router.get("/plans", response_model=list[AdminPlanResponse])
async def admin_list_plans(db: DbSession, _: Staff = Depends(require_permission(INVESTMENT_READ))):
    return await InvestmentService(db).admin_plans()


@admin_router.post("/plans", response_model=AdminPlanResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_plan(
    payload: CreatePlanRequest, db: DbSession, _: Staff = Depends(require_permission(INVESTMENT_MANAGE))
):
    return await InvestmentService(db).create_plan(payload)


@admin_router.patch("/plans/{plan_id}", response_model=AdminPlanResponse)
async def admin_update_plan(
    plan_id: str, payload: UpdatePlanRequest, db: DbSession, _: Staff = Depends(require_permission(INVESTMENT_MANAGE))
):
    """Changes apply to new investments; existing ones keep the rate they were bought at."""
    return await InvestmentService(db).update_plan(plan_id, payload)


@admin_router.put("/plans/{plan_id}/image", response_model=AdminPlanResponse)
async def admin_set_plan_image(
    plan_id: str, payload: PlanImageRequest, db: DbSession, _: Staff = Depends(require_permission(INVESTMENT_MANAGE))
):
    return await InvestmentService(db).set_image(plan_id, payload.image)


@admin_router.delete("/plans/{plan_id}/image", response_model=AdminPlanResponse)
async def admin_remove_plan_image(
    plan_id: str, db: DbSession, _: Staff = Depends(require_permission(INVESTMENT_MANAGE))
):
    return await InvestmentService(db).set_image(plan_id, None)


@admin_router.get("/holdings", response_model=AdminHoldingsPage)
async def admin_holdings(
    db: DbSession,
    _: Staff = Depends(require_permission(INVESTMENT_READ)),
    status_filter: str | None = Query(None, alias="status", pattern="^(active|paid_out)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return await InvestmentService(db).holdings(status_filter=status_filter, limit=limit, offset=offset)
