"""Configurable loan approval workflows and audit trail."""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import StrEnum, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.admin.models import Role, Staff
    from app.modules.loans.models import LoanApplication, LoanProduct


class StageDecisionAction(str, enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class AuditActorType(str, enum.Enum):
    CUSTOMER = "customer"
    STAFF = "staff"
    SYSTEM = "system"


class AuditEventType(str, enum.Enum):
    APPLICATION_CREATED = "application_created"
    APPLICATION_SUBMITTED = "application_submitted"
    APPLICATION_VIEWED = "application_viewed"
    BVN_VIEWED = "bvn_viewed"
    STAGE_ENTERED = "stage_entered"
    STAGE_APPROVED = "stage_approved"
    STAGE_REJECTED = "stage_rejected"
    STATUS_CHANGED = "status_changed"
    DOCUMENT_VERIFIED = "document_verified"
    DOCUMENT_REJECTED = "document_rejected"
    DOCUMENT_UPLOADED = "document_uploaded"
    DISBURSED = "disbursed"
    WORKFLOW_ASSIGNED = "workflow_assigned"


class LoanWorkflow(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Versioned approval pipeline for a loan product."""

    __tablename__ = "loan_workflows"
    __table_args__ = (UniqueConstraint("product_id", "version", name="uq_loan_workflow_product_version"),)

    product_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_products.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_staff_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("staff.id"), nullable=True
    )

    product: Mapped["LoanProduct"] = relationship("LoanProduct", back_populates="workflows")
    stages: Mapped[list["LoanWorkflowStage"]] = relationship(
        "LoanWorkflowStage",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="LoanWorkflowStage.sort_order",
        lazy="selectin",
    )
    applications: Mapped[list["LoanApplication"]] = relationship("LoanApplication", back_populates="workflow")


class LoanWorkflowStage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "loan_workflow_stages"

    workflow_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_workflows.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approver_role_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("roles.id"), index=True
    )

    workflow: Mapped["LoanWorkflow"] = relationship("LoanWorkflow", back_populates="stages")
    approver_role: Mapped["Role"] = relationship("Role", lazy="selectin")
    decisions: Mapped[list["ApplicationStageDecision"]] = relationship(
        "ApplicationStageDecision", back_populates="stage"
    )


class ApplicationStageDecision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Records who acted at each workflow stage and how long the stage took."""

    __tablename__ = "application_stage_decisions"

    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_applications.id", ondelete="CASCADE"), index=True
    )
    stage_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_workflow_stages.id"), index=True
    )
    staff_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("staff.id"), index=True)
    action: Mapped[StageDecisionAction] = mapped_column(StrEnum(StageDecisionAction))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int] = mapped_column(Integer)

    application: Mapped["LoanApplication"] = relationship("LoanApplication", back_populates="stage_decisions")
    stage: Mapped["LoanWorkflowStage"] = relationship("LoanWorkflowStage", back_populates="decisions", lazy="selectin")
    staff: Mapped["Staff"] = relationship("Staff", lazy="selectin")


class ApplicationAuditLog(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "application_audit_logs"
    __table_args__ = (
        # Global feed: WHERE actor_type = ? [AND event_type = ?] ORDER BY created_at DESC.
        Index("ix_audit_logs_actor_type_created_at", "actor_type", "created_at"),
        # One-view-per-window check: application + event + actor within a time range.
        Index("ix_audit_logs_app_event_actor_created", "application_id", "event_type", "actor_id", "created_at"),
    )

    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_applications.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[AuditEventType] = mapped_column(StrEnum(AuditEventType), index=True)
    actor_type: Mapped[AuditActorType] = mapped_column(StrEnum(AuditActorType))
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    application: Mapped["LoanApplication"] = relationship("LoanApplication", back_populates="audit_logs")
