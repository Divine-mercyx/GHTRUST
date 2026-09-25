"""Customer mobile app: application channel + document re-upload audit event.

Revision ID: 013_mobile_app_support
Revises: 012_query_indexes
"""

from alembic import op

revision = "013_mobile_app_support"
down_revision = "012_query_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE cannot run inside a transaction block on older Postgres.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE applicationchannel ADD VALUE IF NOT EXISTS 'mobile'")
        op.execute(
            "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'document_uploaded'"
        )


def downgrade() -> None:
    # Postgres cannot drop enum values; existing rows keep them. Nothing to undo safely.
    pass
