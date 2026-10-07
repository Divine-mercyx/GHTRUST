from typing import TYPE_CHECKING
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import StrEnum, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.loans.schemas import (
    ApplicationChannel,
    ApplicationStatus,
    CollateralCustody,
    DocumentStatus,
    InstallmentStatus,
    InterestMethod,
    LoanStatus,
    RepaymentChannel,
)

if TYPE_CHECKING:
    from app.modules.loans.workflow_models import (
        ApplicationAuditLog,
        ApplicationStageDecision,
        LoanWorkflow,
        LoanWorkflowStage,
    )



class LoanProduct(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "loan_products"

    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    processing_fee_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("3.00"))
    interest_rate_pct_monthly: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("8.00"))
    interest_method: Mapped[InterestMethod] = mapped_column(
        StrEnum(InterestMethod), default=InterestMethod.FLAT, server_default=InterestMethod.FLAT.value
    )
    max_tenure_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_penalty_pct_daily: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    repayment_cadence_options: Mapped[list] = mapped_column(JSON, default=list)
    required_document_types: Mapped[list] = mapped_column(JSON, default=list)
    workflow_steps: Mapped[list] = mapped_column(JSON, default=list)
    eligibility_rules: Mapped[dict] = mapped_column(JSON, default=dict)

    applications: Mapped[list["LoanApplication"]] = relationship("LoanApplication", back_populates="product")
    workflows: Mapped[list["LoanWorkflow"]] = relationship("LoanWorkflow", back_populates="product")


class LoanApplication(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "loan_applications"
    __table_args__ = (
        # Staff queue: WHERE status = ? ORDER BY created_at DESC, and the unfiltered newest-first list.
        Index("ix_loan_applications_status_created_at", "status", "created_at"),
        Index("ix_loan_applications_created_at", "created_at"),
    )

    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customers.id"), index=True)
    product_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("loan_products.id"), index=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        StrEnum(ApplicationStatus), default=ApplicationStatus.DRAFT, index=True
    )
    channel: Mapped[ApplicationChannel] = mapped_column(
        StrEnum(ApplicationChannel), default=ApplicationChannel.WEB
    )
    step: Mapped[int] = mapped_column(Integer, default=1)
    total_steps: Mapped[int] = mapped_column(Integer, default=6)
    branch: Mapped[str] = mapped_column(String(100))

    # Universal form (paper loan form)
    universal_form: Mapped[dict] = mapped_column(JSON, default=dict)
    product_data: Mapped[dict] = mapped_column(JSON, default=dict)

    requested_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    approved_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    repayment_cadence: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Set by staff when confirming terms; falls back to what the customer entered.
    approved_tenure_months: Mapped[int | None] = mapped_column(Integer, nullable=True)

    assigned_officer_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("staff.id"), nullable=True, index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    applicant_signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The customer accepted the final loan offer (the key facts and agreement) with their
    # transaction PIN. Cleared if staff change the terms afterwards.
    offer_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offer_terms_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    offer_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set while the workflow waits for the customer to accept or decline the offer.
    offer_gate_stage_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_workflow_stages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    offer_resume_stage_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_workflow_stages.id", ondelete="SET NULL"), nullable=True, index=True
    )

    workflow_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_workflows.id"), nullable=True, index=True
    )
    current_stage_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_workflow_stages.id"), nullable=True, index=True
    )
    current_stage_entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped["LoanProduct"] = relationship("LoanProduct", back_populates="applications", lazy="joined")
    workflow: Mapped["LoanWorkflow | None"] = relationship("LoanWorkflow", back_populates="applications", lazy="joined")
    current_stage: Mapped["LoanWorkflowStage | None"] = relationship(
        "LoanWorkflowStage", foreign_keys=[current_stage_id], lazy="joined"
    )
    documents: Mapped[list["ApplicationDocument"]] = relationship(
        "ApplicationDocument", back_populates="application", cascade="all, delete-orphan"
    )
    guarantors: Mapped[list["ApplicationGuarantor"]] = relationship(
        "ApplicationGuarantor", back_populates="application", cascade="all, delete-orphan"
    )
    collaterals: Mapped[list["ApplicationCollateral"]] = relationship(
        "ApplicationCollateral", back_populates="application", cascade="all, delete-orphan"
    )
    status_logs: Mapped[list["ApplicationStatusLog"]] = relationship(
        "ApplicationStatusLog", back_populates="application", cascade="all, delete-orphan"
    )
    stage_decisions: Mapped[list["ApplicationStageDecision"]] = relationship(
        "ApplicationStageDecision", back_populates="application", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["ApplicationAuditLog"]] = relationship(
        "ApplicationAuditLog", back_populates="application", cascade="all, delete-orphan"
    )


class ApplicationDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "application_documents"

    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_applications.id", ondelete="CASCADE"), index=True
    )
    document_type: Mapped[str] = mapped_column(String(50), index=True)
    file_key: Mapped[str] = mapped_column(String(500))
    file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[DocumentStatus] = mapped_column(StrEnum(DocumentStatus), default=DocumentStatus.PENDING)
    uploaded_by: Mapped[str] = mapped_column(String(20), default="customer")
    verified_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("staff.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    application: Mapped["LoanApplication"] = relationship("LoanApplication", back_populates="documents")


class ApplicationGuarantor(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "application_guarantors"

    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_applications.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bvn: Mapped[str | None] = mapped_column(String(11), nullable=True)
    id_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    id_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    relationship_to_borrower: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)

    application: Mapped["LoanApplication"] = relationship("LoanApplication", back_populates="guarantors")


class ApplicationCollateral(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "application_collaterals"

    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_applications.id", ondelete="CASCADE"), index=True
    )
    collateral_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    custody_status: Mapped[CollateralCustody] = mapped_column(
        StrEnum(CollateralCustody), default=CollateralCustody.WITH_CUSTOMER
    )
    affidavit_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    original_docs_received: Mapped[bool] = mapped_column(Boolean, default=False)

    application: Mapped["LoanApplication"] = relationship("LoanApplication", back_populates="collaterals")


class ApplicationStatusLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "application_status_logs"

    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_applications.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_staff_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("staff.id"), nullable=True)
    changed_by_customer_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("customers.id"), nullable=True
    )

    application: Mapped["LoanApplication"] = relationship("LoanApplication", back_populates="status_logs")


class LoanDraft(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Legacy draft store — new applications use LoanApplication with status=draft."""

    __tablename__ = "loan_drafts"

    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customers.id"), index=True)
    product_type: Mapped[str] = mapped_column(String(50))  # a loan_products.code
    step: Mapped[int] = mapped_column(Integer, default=1)
    total_steps: Mapped[int] = mapped_column(Integer, default=5)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Loan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A booked (disbursed) loan.

    Money fields:
      principal            amount lent
      total_interest       interest over the whole schedule
      total_repayable      principal + total_interest
      amount_paid          sum of repayments received
      outstanding          total_repayable - amount_paid (what the customer still owes)
      principal_outstanding  principal not yet repaid (the ledger receivable)
      monthly_payment      the regular installment amount (per cadence period;
                           name kept for API compatibility)
    """

    __tablename__ = "loans"
    __table_args__ = (Index("ix_loans_status_created_at", "status", "created_at"),)

    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customers.id"), index=True)
    application_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_applications.id"), unique=True, nullable=True
    )
    product_type: Mapped[str] = mapped_column(String(50))  # a loan_products.code
    principal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    disbursed_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    principal_outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    total_interest: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    total_repayable: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    interest_method: Mapped[InterestMethod] = mapped_column(
        StrEnum(InterestMethod), default=InterestMethod.FLAT, server_default=InterestMethod.FLAT.value
    )
    repayment_cadence: Mapped[str] = mapped_column(String(30), default="monthly", server_default="monthly")
    installments_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tenure_months: Mapped[int] = mapped_column(Integer)
    monthly_payment: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[LoanStatus] = mapped_column(StrEnum(LoanStatus), default=LoanStatus.ACTIVE, index=True)
    disbursement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    branch: Mapped[str] = mapped_column(String(100))

    schedule: Mapped[list["RepaymentSchedule"]] = relationship(
        "RepaymentSchedule",
        order_by="RepaymentSchedule.installment",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class RepaymentSchedule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "repayment_schedules"
    __table_args__ = (UniqueConstraint("loan_id", "installment", name="uq_repayment_schedule_installment"),)

    loan_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("loans.id"), index=True)
    installment: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    principal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    interest: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    principal_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    interest_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    status: Mapped[InstallmentStatus] = mapped_column(
        StrEnum(InstallmentStatus), default=InstallmentStatus.PENDING, server_default=InstallmentStatus.PENDING.value
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def amount_due(self) -> Decimal:
        return (self.principal - self.principal_paid) + (self.interest - self.interest_paid)


class LoanRepayment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A payment received against a loan, allocated across installments."""

    __tablename__ = "loan_repayments"
    __table_args__ = (UniqueConstraint("reference", name="uq_loan_repayments_reference"),)

    loan_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("loans.id"), index=True)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customers.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    interest_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    channel: Mapped[RepaymentChannel] = mapped_column(StrEnum(RepaymentChannel))
    # Idempotency key: bank/teller reference for staff-recorded payments, or a
    # client Idempotency-Key for in-app wallet repayments.
    reference: Mapped[str] = mapped_column(String(128))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_by_staff_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("staff.id"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    allocation: Mapped[list] = mapped_column(JSON, default=list)
    journal_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("ledger_journals.id"), nullable=True
    )
