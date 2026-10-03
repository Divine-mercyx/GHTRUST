from typing import Annotated, Callable

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import DbSession, bearer_scheme, unauthenticated
from app.core.errors import AppError, ErrorCode
from app.core.security import TOKEN_TYPE_STAFF, TokenError, decode_access_token
from app.modules.admin.models import Staff, StaffStatus
from app.modules.auth.models import AuthSession, SubjectType
from app.modules.auth.session_service import SessionService


async def get_current_staff(
    request: Request,
    db: DbSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Staff:
    if not credentials:
        raise unauthenticated()
    try:
        claims = decode_access_token(credentials.credentials, expected_typ=TOKEN_TYPE_STAFF)
    except TokenError:
        raise unauthenticated(ErrorCode.TOKEN_INVALID, "Invalid or expired token")

    sessions = SessionService(db)
    if not await sessions.is_active(claims.sid, subject_type=SubjectType.STAFF, subject_id=claims.sub):
        raise unauthenticated(ErrorCode.SESSION_REVOKED, "Session ended. Please sign in again.")
    # Idle for longer than the timeout: refused now, not only at the next token refresh.
    await sessions.end_if_idle(await db.get(AuthSession, claims.sid))

    result = await db.execute(
        select(Staff)
        .options(selectinload(Staff.role))
        .where(Staff.id == claims.sub, Staff.status == StaffStatus.ACTIVE)
    )
    staff = result.scalar_one_or_none()
    if not staff:
        raise unauthenticated(ErrorCode.ACCOUNT_INACTIVE, "Staff account not found or inactive")

    request.state.session_id = claims.sid
    return staff


CurrentStaff = Annotated[Staff, Depends(get_current_staff)]


def require_permission(permission: str) -> Callable:
    async def _checker(staff: CurrentStaff) -> Staff:
        if not staff.has_permission(permission):
            raise AppError(
                status.HTTP_403_FORBIDDEN, ErrorCode.PERMISSION_DENIED, "Insufficient permissions"
            )
        return staff

    return _checker
