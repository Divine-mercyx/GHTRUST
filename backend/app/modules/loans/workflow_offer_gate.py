"""Credit-stage customer offer: workflow pauses until the borrower accepts or rejects."""

from __future__ import annotations

from app.modules.loans.workflow_models import LoanWorkflowStage

# Default seeded slugs (WorkflowService._slugify). Custom workflows: slug must contain "credit"
# or match one of these for the post-credit offer gate.
CREDIT_OFFER_GATE_SLUGS = frozenset(
    {
        "credit_assessment",
        "credit_check",
        "guardian_school_verification",
        "asset_collateral_review",
    }
)


def is_credit_offer_gate_stage(stage: LoanWorkflowStage) -> bool:
    slug = (stage.slug or "").replace("-", "_").lower()
    if slug in CREDIT_OFFER_GATE_SLUGS:
        return True
    return "credit" in slug
