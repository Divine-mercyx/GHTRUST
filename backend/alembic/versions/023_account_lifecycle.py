"""Account deletion, profile photos, support conversations, loan payouts to the wallet.

- customers.deleted_at; 'deleted' customer status (account deleted by the customer,
  personal data scrubbed, financial records kept).
- customers.profile_photo_base64 / profile_photo_updated_at: a photo the customer
  chose; without one the app shows the BVN photo.
- support_messages: a support request becomes a conversation. Existing requests are
  copied in (the customer's message, then the team's reply if any).
- 'wallet' payment provider: a loan paid into the customer's GH Trust wallet.

Revision ID: 023_account_lifecycle
Revises: 022_selfie_attempts
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "023_account_lifecycle"
down_revision = "022_selfie_attempts"
branch_labels = None
depends_on = None


def _add_enum_value(type_name: str, value: str) -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            ALTER TYPE {type_name} ADD VALUE '{value}';
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def upgrade() -> None:
    _add_enum_value("customerstatus", "deleted")
    _add_enum_value("paymentprovider", "wallet")

    op.add_column("customers", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("customers", sa.Column("profile_photo_base64", sa.Text(), nullable=True))
    op.add_column(
        "customers", sa.Column("profile_photo_updated_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "support_messages",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "ticket_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("support_tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author", sa.String(10), nullable=False),
        sa.Column(
            "staff_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("staff.id"), nullable=True
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_support_messages_ticket_id", "support_messages", ["ticket_id"])

    # Existing requests: the opening message, then the team's reply.
    op.execute(
        """
        INSERT INTO support_messages (id, ticket_id, author, staff_id, body, created_at, updated_at)
        SELECT gen_random_uuid(), id, 'customer', NULL, message, created_at, created_at
        FROM support_tickets
        """
    )
    op.execute(
        """
        INSERT INTO support_messages (id, ticket_id, author, staff_id, body, created_at, updated_at)
        SELECT gen_random_uuid(), id, 'staff', replied_by, reply,
               COALESCE(replied_at, updated_at), COALESCE(replied_at, updated_at)
        FROM support_tickets WHERE reply IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_support_messages_ticket_id", table_name="support_messages")
    op.drop_table("support_messages")
    op.drop_column("customers", "profile_photo_updated_at")
    op.drop_column("customers", "profile_photo_base64")
    op.drop_column("customers", "deleted_at")
    # Enum values can't be removed in PostgreSQL; unused values are harmless.
