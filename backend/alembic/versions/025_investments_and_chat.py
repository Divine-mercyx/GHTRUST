"""Investments go live; support messages get read receipts.

- Ledger: investment_principal (money customers have invested, owed back at maturity),
  investment_return_expense (returns paid); journals investment_purchase / investment_payout.
- investment_plans: max_amount, an image staff upload for the app, when it changed.
- customer_investments: reference, payout amount and when it was paid.
- support_messages.read_at: when the other side read it (real-time chat receipts).

Revision ID: 025_investments_and_chat
Revises: 024_session_timeouts
"""

import sqlalchemy as sa
from alembic import op

revision = "025_investments_and_chat"
down_revision = "024_session_timeouts"
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
    _add_enum_value("ledgeraccountcode", "investment_principal")
    _add_enum_value("ledgeraccountcode", "investment_return_expense")
    _add_enum_value("journaltype", "investment_purchase")
    _add_enum_value("journaltype", "investment_payout")

    op.add_column("investment_plans", sa.Column("max_amount", sa.Numeric(18, 2), nullable=True))
    op.add_column("investment_plans", sa.Column("image_base64", sa.Text(), nullable=True))
    op.add_column("investment_plans", sa.Column("image_content_type", sa.String(30), nullable=True))
    op.add_column("investment_plans", sa.Column("image_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("customer_investments", sa.Column("reference", sa.String(40), nullable=True))
    op.add_column("customer_investments", sa.Column("payout_amount", sa.Numeric(18, 2), nullable=True))
    op.add_column("customer_investments", sa.Column("paid_out_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_customer_investments_status_maturity", "customer_investments", ["status", "maturity_date"])

    op.add_column("support_messages", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("support_messages", "read_at")
    op.drop_index("ix_customer_investments_status_maturity", table_name="customer_investments")
    op.drop_column("customer_investments", "paid_out_at")
    op.drop_column("customer_investments", "payout_amount")
    op.drop_column("customer_investments", "reference")
    op.drop_column("investment_plans", "image_updated_at")
    op.drop_column("investment_plans", "image_content_type")
    op.drop_column("investment_plans", "image_base64")
    op.drop_column("investment_plans", "max_amount")
    # Enum values can't be removed in PostgreSQL; unused values are harmless.
