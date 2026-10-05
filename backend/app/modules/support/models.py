import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class TicketStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class TicketCategory(str, enum.Enum):
    PAYMENTS = "payments"  # money in / out, wallet, repayments
    LOANS = "loans"  # applications, offers, schedules
    ACCOUNT = "account"  # sign-in, PINs, phones, personal details
    APP = "app"  # something in the app isn't working
    DATA = "data"  # privacy / data protection requests (NDPA)
    OTHER = "other"


class SupportTicket(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A problem or request a customer raised in the app, and the team's reply."""

    __tablename__ = "support_tickets"

    reference: Mapped[str] = mapped_column(String(20), unique=True)  # e.g. GHT-7K2Q9M, quoted by phone
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customers.id"), index=True)
    category: Mapped[str] = mapped_column(String(20))  # TicketCategory value
    message: Mapped[str] = mapped_column(Text)
    # What it's about, if the customer started from a transaction, loan or application.
    related_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    related_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=TicketStatus.OPEN.value, index=True)
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("staff.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Where it was sent from, to help reproduce app problems.
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(128), nullable=True)


class MessageAuthor(str, enum.Enum):
    CUSTOMER = "customer"
    STAFF = "staff"


class SupportMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One message in a support conversation, from the customer or the team."""

    __tablename__ = "support_messages"

    ticket_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True
    )
    author: Mapped[str] = mapped_column(String(10))  # MessageAuthor value
    staff_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("staff.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    # When the other side read it (customer read a staff reply, or staff read the customer).
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
