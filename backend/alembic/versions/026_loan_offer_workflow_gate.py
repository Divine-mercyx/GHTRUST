"""Pause workflow after credit stage until customer accepts the loan offer."""

from alembic import op
import sqlalchemy as sa

revision = "026_loan_offer_gate"
down_revision = "025_investments_and_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "loan_applications",
        sa.Column("offer_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "loan_applications",
        sa.Column(
            "offer_gate_stage_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("loan_workflow_stages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "loan_applications",
        sa.Column(
            "offer_resume_stage_id",
            sa.UUID(as_uuid=False),
            sa.ForeignKey("loan_workflow_stages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_loan_applications_offer_gate_stage_id", "loan_applications", ["offer_gate_stage_id"])
    op.create_index("ix_loan_applications_offer_resume_stage_id", "loan_applications", ["offer_resume_stage_id"])


def downgrade() -> None:
    op.drop_index("ix_loan_applications_offer_resume_stage_id", table_name="loan_applications")
    op.drop_index("ix_loan_applications_offer_gate_stage_id", table_name="loan_applications")
    op.drop_column("loan_applications", "offer_resume_stage_id")
    op.drop_column("loan_applications", "offer_gate_stage_id")
    op.drop_column("loan_applications", "offer_sent_at")
