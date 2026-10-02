import enum
from typing import TYPE_CHECKING
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import StrEnum, TimestampMixin, TransactionStatus, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.users.models import Customer



class JournalType(str, enum.Enum):
    WALLET_FUNDING = "wallet_funding"
    WALLET_WITHDRAWAL = "wallet_withdrawal"
    WALLET_WITHDRAWAL_HOLD = "wallet_withdrawal_hold"
    WALLET_WITHDRAWAL_RELEASE = "wallet_withdrawal_release"
    LOAN_DISBURSEMENT = "loan_disbursement"
    LOAN_REPAYMENT = "loan_repayment"


class LedgerDirection(str, enum.Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class LedgerAccountCode(str, enum.Enum):
    PAYSTACK_SETTLEMENT = "paystack_settlement"
    CUSTOMER_WALLET = "customer_wallet"
    CUSTOMER_WALLET_LOCKED = "customer_wallet_locked"
    LOAN_RECEIVABLE = "loan_receivable"
    # Interest is recognised when collected (cash basis) until GH Trust's
    # accounting policy says otherwise.
    INTEREST_INCOME = "interest_income"


class PaymentDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class PaymentProvider(str, enum.Enum):
    PAYSTACK = "paystack"
    MONNIFY = "monnify"
    ZEST = "zest"
    STANBIC = "stanbic"
    # Funds moved outside any integrated rail (e.g. bank app / branch) and
    # recorded by staff with the external reference.
    MANUAL = "manual"
    # Loan paid into the customer's GH Trust wallet (no bank transfer).
    WALLET = "wallet"


class PaymentChannel(str, enum.Enum):
    DVA = "dva"
    TRANSFER = "transfer"
    CARD = "card"
    USSD = "ussd"
    OTHER = "other"


class WithdrawalStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DvaStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    FAILED = "failed"


class CustomerWallet(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "customer_wallets"

    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("customers.id"), unique=True, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    available_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    locked_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    dva_status: Mapped[DvaStatus] = mapped_column(StrEnum(DvaStatus), default=DvaStatus.PENDING)

    customer: Mapped["Customer"] = relationship("Customer", back_populates="wallet", lazy="raise")


class LedgerJournal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ledger_journals"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_ledger_journals_idempotency_key"),)

    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    journal_type: Mapped[JournalType] = mapped_column(StrEnum(JournalType), index=True)
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("customers.id"), nullable=True, index=True
    )
    payment_transaction_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payment_transactions.id"), nullable=True
    )
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry", back_populates="journal", cascade="all, delete-orphan"
    )


class LedgerEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ledger_entries"

    journal_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("ledger_journals.id"), index=True
    )
    account_code: Mapped[LedgerAccountCode] = mapped_column(StrEnum(LedgerAccountCode), index=True)
    direction: Mapped[LedgerDirection] = mapped_column(StrEnum(LedgerDirection))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    customer_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("customers.id"), nullable=True, index=True
    )

    journal: Mapped["LedgerJournal"] = relationship("LedgerJournal", back_populates="entries")


class PaymentTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "payment_transactions"
    __table_args__ = (
        UniqueConstraint("provider", "provider_reference", name="uq_payment_provider_reference"),
        Index("ix_payment_transactions_customer_status", "customer_id", "status"),
        Index("ix_payment_transactions_created_at", "created_at"),
    )

    provider: Mapped[PaymentProvider] = mapped_column(StrEnum(PaymentProvider), default=PaymentProvider.PAYSTACK)
    provider_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    direction: Mapped[PaymentDirection] = mapped_column(StrEnum(PaymentDirection), index=True)
    channel: Mapped[PaymentChannel] = mapped_column(StrEnum(PaymentChannel), default=PaymentChannel.OTHER)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    status: Mapped[TransactionStatus] = mapped_column(
        StrEnum(TransactionStatus), default=TransactionStatus.PENDING, index=True
    )
    customer_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("customers.id"), nullable=True, index=True
    )
    wallet_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("customer_wallets.id"), nullable=True
    )
    application_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_applications.id"), nullable=True, index=True
    )
    withdrawal_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("withdrawal_requests.id"), nullable=True
    )
    webhook_event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class WithdrawalRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "withdrawal_requests"
    __table_args__ = (
        UniqueConstraint("transfer_reference", name="uq_withdrawal_transfer_reference"),
    )

    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customers.id"), index=True)
    wallet_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customer_wallets.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    bank_code: Mapped[str] = mapped_column(String(10))
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    account_number: Mapped[str] = mapped_column(String(20))
    account_name: Mapped[str] = mapped_column(String(200))
    recipient_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transfer_reference: Mapped[str] = mapped_column(String(128))
    transfer_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[WithdrawalStatus] = mapped_column(
        StrEnum(WithdrawalStatus), default=WithdrawalStatus.PENDING, index=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessedWebhookEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "processed_webhook_events"
    __table_args__ = (UniqueConstraint("event_key", name="uq_processed_webhook_event_key"),)

    event_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="paystack")
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LoanDisbursement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tracks Paystack outbound transfer for a loan application."""

    __tablename__ = "loan_disbursements"
    __table_args__ = (UniqueConstraint("application_id", name="uq_loan_disbursements_application_id"),)

    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("loan_applications.id"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customers.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    transfer_reference: Mapped[str] = mapped_column(String(128), unique=True)
    transfer_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[TransactionStatus] = mapped_column(
        StrEnum(TransactionStatus), default=TransactionStatus.PENDING, index=True
    )
    payment_transaction_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payment_transactions.id"), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
