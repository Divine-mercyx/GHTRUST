from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials

from app.core.cache import cached_model
from app.core.config import get_settings
from app.core.deps import DbSession, RedisClient, bearer_scheme, request_meta
from app.core.errors import AppError, ErrorCode
from app.core.security import TOKEN_TYPE_STAFF, TokenError, decode_access_token
from app.core.rate_limit import get_client_ip
from app.modules.admin.deps import CurrentStaff, require_permission
from app.modules.admin.models import Staff
from app.modules.admin.permissions import (
    ALL_PERMISSIONS,
    LOAN_READ,
    ROLE_CREATE,
    ROLE_DELETE,
    ROLE_READ,
    ROLE_UPDATE,
    STAFF_ACTIVATE,
    STAFF_CREATE,
    STAFF_READ,
    STAFF_UPDATE,
)
from app.modules.admin.schemas import (
    StaffSelfUpdateRequest,
    AdminDashboardResponse,
    OtpSentResponse,
    PermissionCatalogResponse,
    PermissionGroupResponse,
    RoleCreateRequest,
    RoleResponse,
    RoleUpdateRequest,
    StaffAuthTokenResponse,
    StaffCreateRequest,
    StaffLoginRequest,
    StaffResponse,
    StaffTokenPair,
    StaffUpdateRequest,
    VerifyStaffOtpRequest,
)
from app.modules.admin.service import AdminAuthService, RoleService, StaffService
from app.core.deps import unauthenticated
from app.modules.auth.models import SubjectType
from app.modules.auth.schemas import RefreshTokenRequest
from app.modules.auth.session_service import SessionService
from app.modules.loans.service import LoanService

router = APIRouter(prefix="/admin", tags=["Admin"])

# ── Refresh-token cookie (web portal) ───────────────────────────────────────
# The portal sends `X-Token-Transport: cookie`; its refresh token then lives only in
# an httpOnly, SameSite=Strict session cookie scoped to these auth routes, so page
# scripts can never read it and it disappears when the browser closes. Other
# clients (mobile, scripts) keep receiving the token in the JSON body.
_COOKIE_PATH = "/api/v1/admin/auth"


def _wants_cookie(request: Request) -> bool:
    return request.headers.get("x-token-transport", "").lower() == "cookie"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.staff_refresh_cookie_name,
        token,
        httponly=True,
        secure=settings.app_env != "development",  # http://localhost in dev
        samesite="strict",
        path=_COOKIE_PATH,
        # No max_age/expires: a browser-session cookie. The server also ends
        # sessions after staff_session_idle_minutes without a refresh.
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.staff_refresh_cookie_name,
        path=_COOKIE_PATH,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="strict",
    )


@router.post(
    "/auth/login/request-otp",
    response_model=OtpSentResponse,
    summary="Staff login — request OTP",
)
async def staff_request_login_otp(
    payload: StaffLoginRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
):
    ip = get_client_ip(request)
    return await AdminAuthService(db, redis).request_login_otp(payload.phone, ip=ip)


@router.post(
    "/auth/login/verify-otp",
    response_model=StaffAuthTokenResponse,
    summary="Staff login — verify OTP",
)
async def staff_verify_login_otp(
    payload: VerifyStaffOtpRequest,
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisClient,
):
    result = await AdminAuthService(db, redis).verify_login_otp(
        payload.phone, payload.otp, meta=request_meta(request), device=payload.device
    )
    if _wants_cookie(request):
        _set_refresh_cookie(response, result.refresh_token)
        result.refresh_token = None
    return result


@router.post(
    "/auth/login/resend-otp",
    response_model=OtpSentResponse,
    summary="Staff login — resend OTP",
)
async def staff_resend_login_otp(
    payload: StaffLoginRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
):
    ip = get_client_ip(request)
    return await AdminAuthService(db, redis).resend_login_otp(payload.phone, ip=ip)


@router.post(
    "/auth/token/refresh",
    response_model=StaffTokenPair,
    summary="Staff — refresh access token",
    description="Send the refresh token in the body, or (web portal) rely on the httpOnly cookie.",
)
async def staff_refresh_token(
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisClient,
    payload: RefreshTokenRequest | None = None,
):
    cookie_token = request.cookies.get(get_settings().staff_refresh_cookie_name)
    token = payload.refresh_token if payload else cookie_token
    if not token:
        raise unauthenticated(ErrorCode.REFRESH_TOKEN_INVALID, "Session expired. Please sign in again.")
    pair = await AdminAuthService(db, redis).refresh(token, meta=request_meta(request))
    result = StaffTokenPair(**pair.model_dump())
    if payload is None or _wants_cookie(request):
        _set_refresh_cookie(response, result.refresh_token)
        result.refresh_token = None
    return result


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Staff — sign out",
    description="Ends the session identified by the bearer token and/or the refresh cookie. "
    "Works even when the access token has already expired.",
)
async def staff_logout(
    request: Request,
    db: DbSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    sessions = SessionService(db)
    if credentials:
        try:
            claims = decode_access_token(credentials.credentials, expected_typ=TOKEN_TYPE_STAFF)
            session = await sessions.get_owned(claims.sid, subject_type=SubjectType.STAFF, subject_id=claims.sub)
            await sessions.revoke(session, reason="logout")
        except (TokenError, AppError):
            pass  # expired token or unknown session: fall back to the cookie
    cookie_token = request.cookies.get(get_settings().staff_refresh_cookie_name)
    if cookie_token:
        await sessions.revoke_by_refresh_token(cookie_token, subject_type=SubjectType.STAFF, reason="logout")
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(resp)
    return resp


@router.get("/auth/me", response_model=StaffResponse, summary="Current staff profile")
async def staff_me(staff: CurrentStaff):
    return StaffResponse.from_staff(staff)


@router.patch("/auth/me", response_model=StaffResponse, summary="Update own profile")
async def update_staff_me(payload: StaffSelfUpdateRequest, staff: CurrentStaff, db: DbSession):
    """Name, job title and avatar colour. Send an empty job title to clear it."""
    changes = payload.model_dump(exclude_unset=True)
    if "full_name" in changes and changes["full_name"]:
        staff.full_name = changes["full_name"]
    if "job_title" in changes:
        staff.job_title = changes["job_title"] or None
    if "avatar_color" in changes:
        staff.avatar_color = changes["avatar_color"]
    await db.flush()
    return StaffResponse.from_staff(staff)


@router.get("/dashboard", response_model=AdminDashboardResponse, summary="Admin dashboard aggregates")
async def admin_dashboard(
    db: DbSession,
    redis: RedisClient,
    _: Staff = Depends(require_permission(LOAN_READ)),
):
    # Several screens poll this; served from Redis until the next write anywhere.
    return await cached_model(redis, "admin:dashboard", AdminDashboardResponse, LoanService(db).get_dashboard)


@router.get("/dashboard/demographics/export", summary="Export demographics report as CSV")
async def export_demographics(
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_READ)),
):
    demo = await LoanService(db).get_demographics()
    csv_body = LoanService.demographics_to_csv(demo)
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="gh-trust-demographics.csv"'},
    )


PERMISSION_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Staff management", ("staff:read", "staff:create", "staff:update", "staff:activate")),
    ("Role management", ("role:read", "role:create", "role:update", "role:delete")),
    (
        "Loan operations",
        (
            "loan:read",
            "loan:review",
            "loan:verify_documents",
            "loan:disburse",
            "loan:record_repayment",
            "loan:configure_workflow",
        ),
    ),
    ("Payments", ("payment:read",)),
    ("Customer support", ("support:read", "support:respond")),
    ("Investments", ("investment:read", "investment:manage")),
]


@router.get("/permissions", response_model=PermissionCatalogResponse, summary="Permission catalog")
async def list_permissions(_: Staff = Depends(require_permission(ROLE_READ))):
    grouped_keys = {key for group in PERMISSION_GROUPS for key in group[1]}
    other = [p for p in ALL_PERMISSIONS if p not in grouped_keys]
    groups = [
        PermissionGroupResponse(label=label, permissions=list(keys))
        for label, keys in PERMISSION_GROUPS
    ]
    if other:
        groups.append(PermissionGroupResponse(label="Other", permissions=other))
    return PermissionCatalogResponse(groups=groups)


@router.get("/roles", response_model=list[RoleResponse], summary="List roles")
async def list_roles(
    db: DbSession,
    _: Staff = Depends(require_permission(ROLE_READ)),
):
    return await RoleService(db).list_roles()


@router.post("/roles", response_model=RoleResponse, summary="Create role", status_code=201)
async def create_role(
    payload: RoleCreateRequest,
    db: DbSession,
    _: Staff = Depends(require_permission(ROLE_CREATE)),
):
    return await RoleService(db).create_role(payload)


@router.patch("/roles/{role_id}", response_model=RoleResponse, summary="Update role")
async def update_role(
    role_id: str,
    payload: RoleUpdateRequest,
    db: DbSession,
    _: Staff = Depends(require_permission(ROLE_UPDATE)),
):
    return await RoleService(db).update_role(role_id, payload)


@router.delete("/roles/{role_id}", status_code=204, summary="Delete role")
async def delete_role(
    role_id: str,
    db: DbSession,
    _: Staff = Depends(require_permission(ROLE_DELETE)),
):
    await RoleService(db).delete_role(role_id)


@router.get("/staff", response_model=list[StaffResponse], summary="List staff")
async def list_staff(
    db: DbSession,
    _: Staff = Depends(require_permission(STAFF_READ)),
):
    return await StaffService(db).list_staff()


@router.post("/staff", response_model=StaffResponse, summary="Create staff", status_code=201)
async def create_staff(
    payload: StaffCreateRequest,
    db: DbSession,
    _: Staff = Depends(require_permission(STAFF_CREATE)),
):
    return await StaffService(db).create_staff(payload)


@router.get("/staff/{staff_id}", response_model=StaffResponse, summary="Get staff member")
async def get_staff(
    staff_id: str,
    db: DbSession,
    _: Staff = Depends(require_permission(STAFF_READ)),
):
    return await StaffService(db).get_staff(staff_id)


@router.patch("/staff/{staff_id}", response_model=StaffResponse, summary="Update staff member")
async def update_staff(
    staff_id: str,
    payload: StaffUpdateRequest,
    db: DbSession,
    _: Staff = Depends(require_permission(STAFF_UPDATE)),
):
    return await StaffService(db).update_staff(staff_id, payload)


@router.post("/staff/{staff_id}/activate", response_model=StaffResponse, summary="Activate staff")
async def activate_staff(
    staff_id: str,
    db: DbSession,
    _: Staff = Depends(require_permission(STAFF_ACTIVATE)),
):
    return await StaffService(db).activate_staff(staff_id)


@router.post("/staff/{staff_id}/deactivate", response_model=StaffResponse, summary="Deactivate staff")
async def deactivate_staff(
    staff_id: str,
    db: DbSession,
    actor: CurrentStaff,
    _: Staff = Depends(require_permission(STAFF_ACTIVATE)),
):
    return await StaffService(db).deactivate_staff(staff_id, actor=actor)
