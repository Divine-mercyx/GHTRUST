import enum
import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import StrEnum, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.payments.models import CustomerWallet


class CustomerStatus(str, enum.Enum):
    PENDING_OTP = "pending_otp"  # BVN verified, awaiting phone OTP
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"
    DELETED = "deleted"  # deleted by the customer: personal data scrubbed, financial records kept


class Customer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Customer profile populated from Dojah BVN Advanced lookup.
    https://docs.dojah.io/docs/nigeria/lookup-bvn#bvn-advanced
    """

    __tablename__ = "customers"
    __table_args__ = (
        # Directory list is newest-first.
        Index("ix_customers_created_at", "created_at"),
        # Staff search matches substrings (ILIKE '%term%'); B-tree can't serve that, trigram GIN can.
        # On SQLite (tests) these become plain indexes — the postgresql_* options are ignored.
        Index("ix_customers_first_name_trgm", "first_name", postgresql_using="gin", postgresql_ops={"first_name": "gin_trgm_ops"}),
        Index("ix_customers_last_name_trgm", "last_name", postgresql_using="gin", postgresql_ops={"last_name": "gin_trgm_ops"}),
        Index("ix_customers_middle_name_trgm", "middle_name", postgresql_using="gin", postgresql_ops={"middle_name": "gin_trgm_ops"}),
        Index("ix_customers_email_trgm", "email", postgresql_using="gin", postgresql_ops={"email": "gin_trgm_ops"}),
        Index("ix_customers_phone_primary_trgm", "phone_primary", postgresql_using="gin", postgresql_ops={"phone_primary": "gin_trgm_ops"}),
        Index("ix_customers_account_number_trgm", "account_number", postgresql_using="gin", postgresql_ops={"account_number": "gin_trgm_ops"}),
    )

    # --- Core banking ---
    account_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    branch: Mapped[str] = mapped_column(String(100))
    status: Mapped[CustomerStatus] = mapped_column(
        StrEnum(CustomerStatus), default=CustomerStatus.PENDING_OTP, index=True
    )

    # --- BVN identity (Dojah entity) ---
    bvn: Mapped[str] = mapped_column(String(11), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    title: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --- Contact (from BVN registry) ---
    phone_primary: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    phone_secondary: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # --- Address & origin ---
    residential_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_of_residence: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lga_of_residence: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state_of_origin: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lga_of_origin: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(50), nullable=True)
    marital_status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # --- BVN enrollment metadata ---
    enrollment_bank: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enrollment_branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    level_of_account: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name_on_card: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bvn_registration_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    watch_listed: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # --- Photo (base64 from Dojah — move to object storage in production) ---
    # Deferred: can be 100s of KB and was loaded on every authenticated request.
    bvn_photo_base64: Mapped[str | None] = mapped_column(Text, nullable=True, deferred=True)
    # A photo the customer chose for their profile; without one the app shows the BVN photo.
    profile_photo_base64: Mapped[str | None] = mapped_column(Text, nullable=True, deferred=True)
    profile_photo_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Auth tracking ---
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Selfie matched against the BVN photo at account opening (Dojah), and how closely.
    selfie_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    selfie_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- PINs (see app/core/pins.py; hashes only, never the PIN) ---
    # 6-digit PIN that opens the app; 4-digit PIN that approves money leaving the account.
    login_pin_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    login_pin_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    login_pin_failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    transaction_pin_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    transaction_pin_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transaction_pin_failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Money can't leave the account before this (e.g. after signing in without the old phone).
    transfers_blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when the customer deleted their account (status DELETED). See account_deletion.py.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Versions of the Terms of Use / Privacy Policy last accepted (history in legal_acceptances).
    terms_accepted_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    privacy_accepted_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --- Paystack / payout rails ---
    paystack_customer_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    paystack_dva_account_number: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    paystack_dva_bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paystack_dva_bank_slug: Mapped[str | None] = mapped_column(String(50), nullable=True)
    paystack_transfer_recipient_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payout_bank_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    payout_bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payout_account_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payout_account_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Not auto-loaded: every request resolves the customer, and nothing reads
    # the wallet through this relationship (services query it explicitly).
    wallet: Mapped["CustomerWallet | None"] = relationship(
        "CustomerWallet", back_populates="customer", uselist=False, lazy="raise"
    )

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p)

    @staticmethod
    def normalize_phone(phone: str) -> str:
        """Normalize Nigerian phone to E.164 (+234...)."""
        digits = re.sub(r"\D", "", phone)
        if digits.startswith("234"):
            return f"+{digits}"
        if digits.startswith("0"):
            return f"+234{digits[1:]}"
        if len(digits) == 10:
            return f"+234{digits}"
        return f"+{digits}" if not phone.startswith("+") else phone

    @staticmethod
    def mask_phone(phone: str) -> str:
        normalized = Customer.normalize_phone(phone)
        if len(normalized) >= 8:
            return f"{normalized[:4]}****{normalized[-4:]}"
        return "****"

    @staticmethod
    def mask_bvn(bvn: str) -> str:
        if len(bvn) >= 6:
            return f"{bvn[:3]}****{bvn[-3:]}"
        return "****"
