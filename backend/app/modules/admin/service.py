import structlog
from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rate_limit import OtpService, RateLimiter
from app.core.errors import AppError, ErrorCode
from app.modules.admin.models import Role, Staff, StaffStatus
from app.modules.admin.permissions import ALL_PERMISSIONS, SUPER_ADMIN_ROLE_NAME
from app.modules.admin.schemas import (
    OtpSentResponse,
    RoleCreateRequest,
    RoleResponse,
    RoleUpdateRequest,
    StaffAuthTokenResponse,
    StaffCreateRequest,
    StaffResponse,
    StaffUpdateRequest,
)
from app.modules.auth.models import SubjectType
from app.modules.auth.schemas import DeviceInfo, TokenPair
from app.modules.auth.session_service import RequestMeta, SessionService
from app.modules.users.models import Customer

logger = structlog.get_logger()


class AdminAuthService:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis
        self.otp = OtpService(redis)

    async def _ensure_active_staff(self, phone: str) -> Staff:
        normalized = Customer.normalize_phone(phone)
        result = await self.db.execute(select(Staff).where(Staff.phone == normalized))
        staff = result.scalar_one_or_none()
        if not staff:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff account not found")
        if staff.status != StaffStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Staff account is inactive. Contact your administrator.",
            )
        return staff

    async def request_login_otp(self, phone: str, *, ip: str) -> OtpSentResponse:
        normalized = Customer.normalize_phone(phone)
        limiter = RateLimiter(self.redis)
        await limiter.check_login_request(ip, normalized)
        await self._ensure_active_staff(phone)

        await limiter.check_otp_send(ip, normalized)
        expires_in = await self.otp.send("staff_login", normalized, normalized)
        return OtpSentResponse(
            message="OTP sent to your registered phone number.",
            phone_masked=Customer.mask_phone(normalized),
            expires_in=expires_in,
        )

    async def verify_login_otp(
        self,
        phone: str,
        otp: str,
        *,
        meta: RequestMeta,
        device: DeviceInfo | None = None,
    ) -> StaffAuthTokenResponse:
        normalized = Customer.normalize_phone(phone)
        await RateLimiter(self.redis).check_otp_verify(meta.ip or "unknown")
        await self.otp.verify("staff_login", normalized, otp)

        result = await self.db.execute(
            select(Staff).options(selectinload(Staff.role)).where(Staff.phone == normalized)
        )
        staff = result.scalar_one_or_none()
        if not staff or staff.status != StaffStatus.ACTIVE:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        pair = await SessionService(self.db).issue(
            subject_type=SubjectType.STAFF,
            subject_id=staff.id,
            phone=staff.phone,
            is_super_admin=staff.is_super_admin,
            device=device,
            meta=meta,
        )
        return StaffAuthTokenResponse(**pair.model_dump(), staff=StaffResponse.from_staff(staff))

    async def refresh(self, refresh_token: str, *, meta: RequestMeta) -> TokenPair:
        await RateLimiter(self.redis).check_refresh(meta.ip or "unknown")
        sessions = SessionService(self.db)
        session, new_refresh = await sessions.rotate(
            refresh_token, subject_type=SubjectType.STAFF, meta=meta
        )
        staff = await self.db.get(Staff, session.subject_id)
        if not staff or staff.status != StaffStatus.ACTIVE:
            await sessions.revoke(session, reason="account_inactive")
            await self.db.commit()
            raise AppError(
                status.HTTP_401_UNAUTHORIZED,
                ErrorCode.ACCOUNT_INACTIVE,
                "Staff account not found or inactive",
            )
        return sessions.pair_for(
            session, new_refresh, phone=staff.phone, is_super_admin=staff.is_super_admin
        )

    async def resend_login_otp(self, phone: str, *, ip: str) -> OtpSentResponse:
        normalized = Customer.normalize_phone(phone)
        await self._ensure_active_staff(phone)
        limiter = RateLimiter(self.redis)
        await limiter.check_otp_send(ip, normalized)
        expires_in = await self.otp.send("staff_login", normalized, normalized)
        return OtpSentResponse(
            message="OTP sent to your registered phone number.",
            phone_masked=Customer.mask_phone(normalized),
            expires_in=expires_in,
        )


class RoleService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_roles(self) -> list[RoleResponse]:
        result = await self.db.execute(select(Role).order_by(Role.name))
        return [RoleResponse.from_role(r) for r in result.scalars().all()]

    async def create_role(self, payload: RoleCreateRequest) -> RoleResponse:
        self._validate_permissions(payload.permissions)
        existing = await self.db.execute(select(Role).where(Role.name == payload.name.strip()))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role name already exists")

        role = Role(
            name=payload.name.strip(),
            description=payload.description,
            permissions=sorted(set(payload.permissions)),
        )
        self.db.add(role)
        await self.db.flush()
        return RoleResponse.from_role(role)

    async def update_role(self, role_id: str, payload: RoleUpdateRequest) -> RoleResponse:
        role = await self._get_role(role_id)
        if role.is_system:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="System roles cannot be modified")

        if payload.name is not None:
            name = payload.name.strip()
            clash = await self.db.execute(
                select(Role).where(Role.name == name, Role.id != role_id)
            )
            if clash.scalar_one_or_none():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role name already exists")
            role.name = name
        if payload.description is not None:
            role.description = payload.description
        if payload.permissions is not None:
            self._validate_permissions(payload.permissions)
            role.permissions = sorted(set(payload.permissions))

        await self.db.flush()
        return RoleResponse.from_role(role)

    async def delete_role(self, role_id: str) -> None:
        role = await self._get_role(role_id)
        if role.is_system:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="System roles cannot be deleted")

        count = await self.db.execute(select(func.count()).select_from(Staff).where(Staff.role_id == role_id))
        if count.scalar_one() > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Role is assigned to staff members and cannot be deleted",
            )
        await self.db.delete(role)

    async def _get_role(self, role_id: str) -> Role:
        result = await self.db.execute(select(Role).where(Role.id == role_id))
        role = result.scalar_one_or_none()
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        return role

    @staticmethod
    def _validate_permissions(permissions: list[str]) -> None:
        invalid = set(permissions) - set(ALL_PERMISSIONS)
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown permissions: {', '.join(sorted(invalid))}",
            )


class StaffService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_staff(self) -> list[StaffResponse]:
        result = await self.db.execute(
            select(Staff).options(selectinload(Staff.role)).order_by(Staff.full_name)
        )
        return [StaffResponse.from_staff(s) for s in result.scalars().all()]

    async def get_staff(self, staff_id: str) -> StaffResponse:
        staff = await self._get_staff(staff_id)
        return StaffResponse.from_staff(staff)

    async def create_staff(self, payload: StaffCreateRequest) -> StaffResponse:
        phone = Customer.normalize_phone(payload.phone)
        email = payload.email.lower().strip()
        await self._ensure_unique_contact(email=email, phone=phone)

        role = None
        if payload.role_id:
            role = await self._get_role(payload.role_id)

        staff = Staff(
            full_name=payload.full_name.strip(),
            email=email,
            phone=phone,
            role_id=role.id if role else None,
            status=StaffStatus.INACTIVE,
            is_super_admin=False,
        )
        self.db.add(staff)
        await self.db.flush()
        await self.db.refresh(staff, attribute_names=["role"])
        logger.info("staff_created", staff_id=staff.id, email=email)
        return StaffResponse.from_staff(staff)

    async def update_staff(self, staff_id: str, payload: StaffUpdateRequest) -> StaffResponse:
        staff = await self._get_staff(staff_id)
        if staff.is_super_admin and payload.role_id is not None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin role cannot be changed")

        email = payload.email.lower().strip() if payload.email else None
        phone = Customer.normalize_phone(payload.phone) if payload.phone else None
        await self._ensure_unique_contact(email=email, phone=phone, exclude_id=staff_id)

        if payload.full_name is not None:
            staff.full_name = payload.full_name.strip()
        if email is not None:
            staff.email = email
        if phone is not None:
            staff.phone = phone
        if payload.role_id is not None:
            role = await self._get_role(payload.role_id)
            staff.role_id = role.id

        await self.db.flush()
        return StaffResponse.from_staff(staff)

    async def activate_staff(self, staff_id: str) -> StaffResponse:
        staff = await self._get_staff(staff_id)
        if not staff.is_super_admin and not staff.role_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Assign a role before activating this staff member",
            )
        staff.status = StaffStatus.ACTIVE
        await self.db.flush()
        return StaffResponse.from_staff(staff)

    async def deactivate_staff(self, staff_id: str, *, actor: Staff) -> StaffResponse:
        staff = await self._get_staff(staff_id)
        if staff.is_super_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin cannot be deactivated")
        if staff.id == actor.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot deactivate your own account")

        staff.status = StaffStatus.INACTIVE
        # Kill live sessions now — otherwise the staff member keeps access until
        # their current token expires.
        await SessionService(self.db).revoke_all(
            subject_type=SubjectType.STAFF, subject_id=staff.id, reason="staff_deactivated"
        )
        await self.db.flush()
        return StaffResponse.from_staff(staff)

    async def _get_staff(self, staff_id: str) -> Staff:
        result = await self.db.execute(
            select(Staff).options(selectinload(Staff.role)).where(Staff.id == staff_id)
        )
        staff = result.scalar_one_or_none()
        if not staff:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff not found")
        return staff

    async def _get_role(self, role_id: str) -> Role:
        result = await self.db.execute(select(Role).where(Role.id == role_id))
        role = result.scalar_one_or_none()
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        return role

    async def _ensure_unique_contact(
        self,
        *,
        email: str | None,
        phone: str | None,
        exclude_id: str | None = None,
    ) -> None:
        if email:
            q = select(Staff).where(Staff.email == email)
            if exclude_id:
                q = q.where(Staff.id != exclude_id)
            if (await self.db.execute(q)).scalar_one_or_none():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")
        if phone:
            q = select(Staff).where(Staff.phone == phone)
            if exclude_id:
                q = q.where(Staff.id != exclude_id)
            if (await self.db.execute(q)).scalar_one_or_none():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number already in use")


async def ensure_super_admin_role(db: AsyncSession) -> Role:
    result = await db.execute(select(Role).where(Role.name == SUPER_ADMIN_ROLE_NAME))
    role = result.scalar_one_or_none()
    if role:
        return role
    role = Role(
        name=SUPER_ADMIN_ROLE_NAME,
        description="Full system access",
        permissions=list(ALL_PERMISSIONS),
        is_system=True,
    )
    db.add(role)
    await db.flush()
    return role


async def seed_super_admin(
    db: AsyncSession,
    *,
    full_name: str,
    email: str,
    phone: str,
) -> Staff:
    """
    Make sure the admin named by SEED_SUPER_ADMIN_* can sign in. Idempotent.

    Keyed on the configured phone and email, not on "any super admin exists": after
    SEED_SUPER_ADMIN_PHONE changes (e.g. a lost number), the next run moves that admin
    to the new phone instead of silently leaving nobody able to sign in with it.
    """
    normalized_phone = Customer.normalize_phone(phone)
    email = email.lower().strip()

    existing = await db.execute(
        select(Staff).where(or_(Staff.phone == normalized_phone, Staff.email == email))
    )
    staff = existing.scalars().first()
    if staff:
        if staff.phone != normalized_phone:
            logger.warning("super_admin_phone_updated", staff_id=staff.id, email=staff.email)
            staff.phone = normalized_phone
            await db.flush()
        return staff

    await ensure_super_admin_role(db)
    staff = Staff(
        full_name=full_name,
        email=email,
        phone=normalized_phone,
        role_id=None,
        is_super_admin=True,
        status=StaffStatus.ACTIVE,
    )
    db.add(staff)
    await db.flush()
    logger.info("super_admin_seeded", email=email)
    return staff
