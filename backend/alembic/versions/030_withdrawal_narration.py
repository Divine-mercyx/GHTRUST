"""Optional customer note (narration) on a withdrawal, shown to the recipient's bank."""

import sqlalchemy as sa
from alembic import op

revision = "030_withdrawal_narration"
down_revision = "029_loan_catalogue_website"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("withdrawal_requests", sa.Column("narration", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("withdrawal_requests", "narration")
