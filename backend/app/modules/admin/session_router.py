"""
Staff session timeout: the organisation's setting, a staff member's own shorter one, and
the portal's activity signal. See security_settings.py.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from app.core.deps import DbSession
from app.core.errors import AppError, ErrorCode
from app.modules.admin import security_settings as sec
from app.modules.admin.deps import CurrentStaff
from app.modules.auth.models import AuthSession
from app.modules.auth.session_service import SessionService

router = APIRouter(prefix="/admin", tags=["Admin — Session timeout"])


class SecuritySettingsResponse(BaseModel):
    staff_idle_minutes: int = Field(description="The organisation's idle timeout")
    min_minutes: int
    max_minutes: int
    updated_at: datetime | None
    updated_by_name: str | None
    my_idle_minutes: int | None = Field(description="A shorter timeout this staff member chose, if any")
    effective_idle_minutes: int = Field(description="What applies to this staff member")
    can_edit: bool = Field(description="Super admins change the organisation's timeout")


class UpdateOrgTimeoutRequest(BaseModel):
    staff_idle_minutes: int = Field(..., ge=sec.MIN_IDLE_MINUTES, le=sec.MAX_IDLE_MINUTES)


class UpdateMyTimeoutRequest(BaseModel):
    minutes: int | None = Field(
        None, ge=sec.MIN_IDLE_MINUTES, le=sec.MAX_IDLE_MINUTES, description="null: use the organisation's"
    )


class ActivityResponse(BaseModel):
    effective_idle_minutes: int
    last_activity_at: datetime
    idle_expires_at: datetime


async def _response(db, staff) -> SecuritySettingsResponse:
    org = await sec.org_timeout(db)
    return SecuritySettingsResponse(
        staff_idle_minutes=org.minutes,
        min_minutes=sec.MIN_IDLE_MINUTES,
        max_minutes=sec.MAX_IDLE_MINUTES,
        updated_at=org.updated_at,
        updated_by_name=await sec.staff_name(db, org.updated_by),
        my_idle_minutes=staff.session_idle_minutes,
        effective_idle_minutes=sec.effective_minutes(org.minutes, staff),
        can_edit=staff.is_super_admin,
    )


@router.get("/settings/security", response_model=SecuritySettingsResponse, summary="Session timeout settings")
async def get_security_settings(staff: CurrentStaff, db: DbSession) -> SecuritySettingsResponse:
    return await _response(db, staff)


@router.put("/settings/security", response_model=SecuritySettingsResponse, summary="Change the staff idle timeout")
async def update_security_settings(
    payload: UpdateOrgTimeoutRequest, staff: CurrentStaff, db: DbSession
) -> SecuritySettingsResponse:
    """Super admins only. Applies to every staff member from their next request."""
    if not staff.is_super_admin:
        raise AppError(
            status.HTTP_403_FORBIDDEN, ErrorCode.PERMISSION_DENIED, "Only a super admin can change this."
        )
    await sec.set_org_timeout(db, payload.staff_idle_minutes, staff)
    return await _response(db, staff)


@router.put("/auth/me/session-timeout", response_model=SecuritySettingsResponse, summary="Choose a shorter timeout")
async def update_my_timeout(
    payload: UpdateMyTimeoutRequest, staff: CurrentStaff, db: DbSession
) -> SecuritySettingsResponse:
    """A staff member may sign out sooner than the organisation requires, never later."""
    org = (await sec.org_timeout(db)).minutes
    if payload.minutes is not None and payload.minutes > org:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_ERROR",
            f"Choose {org} minutes or less: the organisation's timeout is {org} minutes.",
        )
    staff.session_idle_minutes = payload.minutes
    await db.flush()
    return await _response(db, staff)


@router.post("/auth/activity", response_model=ActivityResponse, summary="Record activity (staff portal)")
async def record_activity(request: Request, staff: CurrentStaff, db: DbSession) -> ActivityResponse:
    """
    The portal calls this when the staff member actually does something (click, type,
    navigate), at most about once a minute. Only this restarts the idle clock.
    """
    session = await db.get(AuthSession, request.state.session_id)
    at = await SessionService(db).touch(session)
    minutes = await sec.staff_idle_minutes(db, staff.id)
    return ActivityResponse(
        effective_idle_minutes=minutes, last_activity_at=at, idle_expires_at=at + timedelta(minutes=minutes)
    )
