"""Saved withdrawal recipients ("Send money"), seeded from each customer's payout account."""

import sqlalchemy as sa
from alembic import op

revision = "028_payout_recipients"
down_revision = "027_stanbic_virtual_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payout_recipients",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column("customer_id", sa.UUID(as_uuid=False), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("bank_code", sa.String(10), nullable=False),
        sa.Column("bank_name", sa.String(100), nullable=True),
        sa.Column("account_number", sa.String(20), nullable=False),
        sa.Column("account_name", sa.String(200), nullable=True),
        sa.Column("recipient_code", sa.String(100), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("customer_id", "bank_code", "account_number", name="uq_payout_recipients_account"),
    )
    op.create_index("ix_payout_recipients_customer_id", "payout_recipients", ["customer_id"])
    # Every existing payout account becomes the customer's first saved recipient.
    op.execute(
        """
        INSERT INTO payout_recipients
            (id, customer_id, bank_code, bank_name, account_number, account_name, recipient_code)
        SELECT gen_random_uuid(), id, payout_bank_code, payout_bank_name, payout_account_number,
               payout_account_name, paystack_transfer_recipient_code
        FROM customers
        WHERE payout_bank_code IS NOT NULL AND payout_account_number IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_payout_recipients_customer_id", table_name="payout_recipients")
    op.drop_table("payout_recipients")
