"""Staff session timeout set in the portal.

- system_settings: organisation-wide settings changed by a super admin (key → JSON value,
  who changed it last and when). First key: staff_session_idle_minutes.
- staff.session_idle_minutes: a shorter timeout a staff member chose for themselves.

Revision ID: 024_session_timeouts
Revises: 023_account_lifecycle
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "024_session_timeouts"
down_revision = "023_account_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("staff.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("staff", sa.Column("session_idle_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("staff", "session_idle_minutes")
    op.drop_table("system_settings")
