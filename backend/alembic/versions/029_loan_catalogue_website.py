"""Loan catalogue from GH Trust's website: product wording, the Business loan's ₦100,000
guarantor-or-collateral rule, and LPO / invoice financing switched on with its one-off 7% charge.

Only products still carrying the old built-in wording are changed, so edits made in the admin
portal are kept. The new Cluster / Group loan is added by scripts/seed.py (pre-deploy), with
the approval workflows for it and for LPO financing.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "029_loan_catalogue_website"
down_revision = "028_payout_recipients"
branch_labels = None
depends_on = None

OLD_TO_NEW = {
    "business_loan": (
        "For traders buying and selling products and commodities. Existing businesses only (3+ years).",
        "Working capital for traders who buy and sell goods: restock, pay suppliers and meet demand. "
        "For businesses trading for 3 years or more. Repay daily, weekly or monthly to match your cash flow. "
        "From ₦100,000, add a guarantor or acceptable collateral.",
    ),
    "payday_loan": (
        "Salary earner loan with Remita direct debit on salary account.",
        "Quick support for salary earners before payday: medical bills, school fees, rent and other "
        "urgent needs. Repay over up to 120 days, in line with your salary cycle.",
    ),
    "study_loan": (
        "Study abroad tuition financing (Famolex affiliation). Guardian applies on behalf of student.",
        "Study-abroad tuition financing with Famolex Integrated: up to 70% of the student's first-year "
        "tuition, decided within 7 working days. A parent or guardian applies for the student.",
    ),
}

LPO = {
    "name": "Trust LPO / Invoice / Supply Financing",
    "description": "Working capital to deliver verified LPOs, supply contracts and approved invoices from reputable "
    "organisations. 3% processing fee upfront, then a 7% charge when the job is paid.",
    "rate": "7.00",
    "cadences": ["end_of_term"],
    "documents": ["valid_id", "bvn", "business_registration", "lpo_invoice", "guarantor_id"],
    "steps": ["product_selection", "universal_form", "lpo_details", "guarantor_collateral", "documents", "review_submit"],
    "rules": {"requires_verified_lpo": True, "collateral_if_no_domiciliation": True},
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # A new enum value can't be used in the transaction that adds it.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE interestmethod ADD VALUE IF NOT EXISTS 'one_off'")

    for code, (old, new) in OLD_TO_NEW.items():
        bind.execute(
            sa.text("UPDATE loan_products SET description = :new WHERE code = :code AND description = :old"),
            {"new": new, "code": code, "old": old},
        )

    row = bind.execute(
        sa.text("SELECT id, eligibility_rules FROM loan_products WHERE code = 'business_loan'")
    ).first()
    if row is not None:
        rules = row.eligibility_rules if isinstance(row.eligibility_rules, dict) else json.loads(row.eligibility_rules or "{}")
        if "security_from_amount" not in rules:
            rules["security_from_amount"] = 100000
            bind.execute(
                sa.text("UPDATE loan_products SET eligibility_rules = CAST(:rules AS JSON) WHERE id = :id"),
                {"rules": json.dumps(rules), "id": row.id},
            )

    bind.execute(
        sa.text(
            """
            UPDATE loan_products
            SET name = :name, description = :description, is_active = true,
                interest_rate_pct_monthly = :rate, interest_method = 'one_off',
                repayment_cadence_options = CAST(:cadences AS JSON),
                required_document_types = CAST(:documents AS JSON),
                workflow_steps = CAST(:steps AS JSON), eligibility_rules = CAST(:rules AS JSON)
            WHERE code = 'lpo_invoice_financing' AND description = 'Reserved for future release.'
            """
        ),
        {
            "name": LPO["name"],
            "description": LPO["description"],
            "rate": LPO["rate"],
            "cadences": json.dumps(LPO["cadences"]),
            "documents": json.dumps(LPO["documents"]),
            "steps": json.dumps(LPO["steps"]),
            "rules": json.dumps(LPO["rules"]),
        },
    )


def downgrade() -> None:
    # Wording changes are left in place; LPO financing goes back to switched off.
    op.execute(
        "UPDATE loan_products SET is_active = false, interest_method = 'flat' WHERE code = 'lpo_invoice_financing'"
    )
