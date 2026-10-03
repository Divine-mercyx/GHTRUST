import enum

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import StrEnum, TimestampMixin, UUIDPrimaryKeyMixin


class StaffStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Role(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    staff_members: Mapped[list["Staff"]] = relationship("Staff", back_populates="role")


class Staff(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "staff"

    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    # Self-service profile (PATCH /admin/auth/me).
    job_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role_id: Mapped[str | None] = mapped_column(
        ForeignKey("roles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # A shorter idle timeout this person chose for themselves (never longer than the
    # organisation's; see security_settings.py). None: use the organisation's.
    session_idle_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[StaffStatus] = mapped_column(
        StrEnum(StaffStatus), default=StaffStatus.INACTIVE, index=True
    )

    role: Mapped[Role | None] = relationship("Role", back_populates="staff_members", lazy="joined")

    @property
    def effective_permissions(self) -> set[str]:
        if self.is_super_admin:
            from app.modules.admin.permissions import ALL_PERMISSIONS

            return set(ALL_PERMISSIONS)
        if self.role and self.role.permissions:
            return set(self.role.permissions)
        return set()

    def has_permission(self, permission: str) -> bool:
        return permission in self.effective_permissions


class SystemSetting(Base):
    """An organisation-wide setting a super admin changes in the portal (see security_settings.py)."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | int | str | bool] = mapped_column(JSON, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("staff.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
