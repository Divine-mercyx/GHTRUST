"""Seed default workflow roles and published workflows per loan product."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Role
from app.modules.admin.permissions import (
    LOAN_DISBURSE,
    LOAN_READ,
    LOAN_RECORD_REPAYMENT,
    LOAN_REVIEW,
    LOAN_VERIFY_DOCS,
)
from app.modules.loans.constants import ASSET_LOAN, BUSINESS_LOAN, CLUSTER_LOAN, LPO_LOAN, PAYDAY_LOAN, STUDY_LOAN
from app.modules.loans.models import LoanProduct
from app.modules.loans.workflow_service import WorkflowService

DEFAULT_ROLES: list[dict] = [
    {
        "name": "Loan Officer",
        "description": "Front-line review and document verification",
        "permissions": [LOAN_READ, LOAN_REVIEW, LOAN_VERIFY_DOCS],
    },
    {
        "name": "Credit Analyst",
        "description": "Credit assessment and risk review",
        "permissions": [LOAN_READ, LOAN_REVIEW],
    },
    {
        "name": "Branch Manager",
        "description": "Final branch-level approval",
        "permissions": [LOAN_READ, LOAN_REVIEW, LOAN_DISBURSE],
    },
    {
        "name": "Operations Officer",
        "description": "Disbursement, repayments and operations",
        "permissions": [LOAN_READ, LOAN_DISBURSE, LOAN_RECORD_REPAYMENT],
    },
]

# role_name -> stage definitions per product
DEFAULT_PRODUCT_WORKFLOWS: dict[str, list[dict]] = {
    BUSINESS_LOAN: [
        {"name": "Document verification", "role": "Loan Officer"},
        {"name": "Credit assessment", "role": "Credit Analyst"},
        {"name": "Branch approval", "role": "Branch Manager"},
        {"name": "Disbursement", "role": "Operations Officer"},
    ],
    PAYDAY_LOAN: [
        {"name": "Document verification", "role": "Loan Officer"},
        {"name": "Credit check", "role": "Credit Analyst"},
        {"name": "Disbursement", "role": "Operations Officer"},
    ],
    STUDY_LOAN: [
        {"name": "Document verification", "role": "Loan Officer"},
        {"name": "Guardian & school verification", "role": "Credit Analyst"},
        {"name": "Branch approval", "role": "Branch Manager"},
        {"name": "Disbursement to school", "role": "Operations Officer"},
    ],
    ASSET_LOAN: [
        {"name": "Document verification", "role": "Loan Officer"},
        {"name": "Asset & collateral review", "role": "Credit Analyst"},
        {"name": "Branch approval", "role": "Branch Manager"},
        {"name": "Disbursement", "role": "Operations Officer"},
    ],
    LPO_LOAN: [
        {"name": "Document verification", "role": "Loan Officer"},
        {"name": "LPO / invoice verification", "role": "Credit Analyst"},
        {"name": "Branch approval", "role": "Branch Manager"},
        {"name": "Disbursement", "role": "Operations Officer"},
    ],
    CLUSTER_LOAN: [
        {"name": "Group & document verification", "role": "Loan Officer"},
        {"name": "Group credit assessment", "role": "Credit Analyst"},
        {"name": "Branch approval", "role": "Branch Manager"},
        {"name": "Disbursement", "role": "Operations Officer"},
    ],
}


async def seed_workflow_roles(db: AsyncSession) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for item in DEFAULT_ROLES:
        result = await db.execute(select(Role).where(Role.name == item["name"]))
        role = result.scalar_one_or_none()
        if not role:
            role = Role(
                name=item["name"],
                description=item["description"],
                permissions=item["permissions"],
                is_system=False,
            )
            db.add(role)
            await db.flush()
        elif role.is_system:
            # Default lending roles are editable templates, not locked system roles.
            role.is_system = False
        roles[item["name"]] = role
    return roles


async def seed_default_workflows(db: AsyncSession) -> None:
    roles = await seed_workflow_roles(db)
    workflow_svc = WorkflowService(db)

    for product_code, stage_defs in DEFAULT_PRODUCT_WORKFLOWS.items():
        result = await db.execute(select(LoanProduct).where(LoanProduct.code == product_code))
        product = result.scalar_one_or_none()
        if not product:
            continue

        existing = await workflow_svc.get_active_workflow(product.id)
        if existing:
            continue

        stages = [
            {
                "name": s["name"],
                "approver_role_id": roles[s["role"]].id,
                "description": f"{s['name']} for {product.name}",
            }
            for s in stage_defs
        ]
        workflow = await workflow_svc.create_draft_workflow(product, stages=stages)
        await workflow_svc.publish_workflow(workflow.id)

    await db.flush()
