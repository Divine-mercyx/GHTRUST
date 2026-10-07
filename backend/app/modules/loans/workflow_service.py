"""Workflow configuration and stage progression."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

if TYPE_CHECKING:
    from app.modules.loans.workflow_schemas import WorkflowResponse

from app.modules.admin.models import Role, Staff
from app.modules.loans.audit_service import ApplicationAuditService
from app.modules.loans.document_gate import ensure_documents_verified
from app.modules.payments.disbursement_service import DisbursementService
from app.modules.loans.models import LoanApplication, LoanProduct
from app.modules.loans.schemas import ApplicationStatus
from app.modules.loans.workflow_models import (
    ApplicationStageDecision,
    AuditEventType,
    LoanWorkflow,
    LoanWorkflowStage,
    StageDecisionAction,
)
from app.modules.loans.servicing import validate_terms
from app.modules.loans.workflow_offer_gate import is_credit_offer_gate_stage
from app.modules.notifications import events as notify


def _utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class WorkflowService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit = ApplicationAuditService(db)

    async def get_active_workflow(self, product_id: str) -> LoanWorkflow | None:
        result = await self.db.execute(
            select(LoanWorkflow)
            .options(selectinload(LoanWorkflow.stages).selectinload(LoanWorkflowStage.approver_role))
            .where(LoanWorkflow.product_id == product_id, LoanWorkflow.is_published.is_(True))
            .order_by(LoanWorkflow.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_workflow_by_id(self, workflow_id: str) -> LoanWorkflow:
        result = await self.db.execute(
            select(LoanWorkflow)
            .options(selectinload(LoanWorkflow.stages).selectinload(LoanWorkflowStage.approver_role))
            .where(LoanWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        if not workflow:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
        return workflow

    async def list_workflows_for_product(self, product_id: str) -> list[LoanWorkflow]:
        result = await self.db.execute(
            select(LoanWorkflow)
            .options(selectinload(LoanWorkflow.stages).selectinload(LoanWorkflowStage.approver_role))
            .where(LoanWorkflow.product_id == product_id)
            .order_by(LoanWorkflow.version.desc())
        )
        return list(result.scalars().all())

    async def create_draft_workflow(
        self,
        product: LoanProduct,
        *,
        stages: list[dict],
        staff_id: str | None = None,
    ) -> LoanWorkflow:
        latest = await self.db.execute(
            select(func.max(LoanWorkflow.version)).where(LoanWorkflow.product_id == product.id)
        )
        next_version = (latest.scalar() or 0) + 1

        workflow = LoanWorkflow(
            product_id=product.id,
            version=next_version,
            is_published=False,
            created_by_staff_id=staff_id,
        )
        self.db.add(workflow)
        await self.db.flush()
        await self._replace_stages(workflow, stages)
        return await self.get_workflow_by_id(workflow.id)

    async def update_draft_stages(self, workflow_id: str, stages: list[dict]) -> LoanWorkflow:
        workflow = await self.get_workflow_by_id(workflow_id)
        if workflow.is_published:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Published workflows cannot be edited. Create a new version.",
            )
        await self._replace_stages(workflow, stages)
        return await self.get_workflow_by_id(workflow.id)

    async def publish_workflow(self, workflow_id: str) -> LoanWorkflow:
        workflow = await self.get_workflow_by_id(workflow_id)
        if workflow.is_published:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow already published")
        stage_count = await self.db.execute(
            select(LoanWorkflowStage.id).where(LoanWorkflowStage.workflow_id == workflow.id).limit(1)
        )
        if stage_count.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Workflow must have at least one stage before publishing",
            )

        prev = await self.db.execute(
            select(LoanWorkflow).where(
                LoanWorkflow.product_id == workflow.product_id,
                LoanWorkflow.is_published.is_(True),
            )
        )
        for old in prev.scalars().all():
            old.is_published = False

        workflow.is_published = True
        workflow.published_at = datetime.now(timezone.utc)
        await self.db.flush()
        return await self.get_workflow_by_id(workflow.id)

    async def to_response(self, workflow: LoanWorkflow) -> "WorkflowResponse":
        from app.modules.loans.workflow_schemas import WorkflowResponse, WorkflowStageResponse

        loaded = await self.get_workflow_by_id(workflow.id)
        stages_result = await self.db.execute(
            select(LoanWorkflowStage)
            .where(LoanWorkflowStage.workflow_id == loaded.id)
            .order_by(LoanWorkflowStage.sort_order.asc())
        )
        stage_rows: list[WorkflowStageResponse] = []
        for stage in stages_result.scalars().all():
            role = await self.db.get(Role, stage.approver_role_id)
            stage_rows.append(
                WorkflowStageResponse(
                    id=stage.id,
                    sort_order=stage.sort_order,
                    name=stage.name,
                    slug=stage.slug,
                    description=stage.description,
                    approver_role_id=stage.approver_role_id,
                    approver_role_name=role.name if role else None,
                )
            )
        return WorkflowResponse(
            id=loaded.id,
            product_id=loaded.product_id,
            version=loaded.version,
            is_published=loaded.is_published,
            published_at=loaded.published_at,
            stages=stage_rows,
        )

    async def assign_workflow_to_application(self, application: LoanApplication) -> None:
        workflow = await self.get_active_workflow(application.product_id)
        if not workflow or not workflow.stages:
            application.status = ApplicationStatus.SUBMITTED
            return

        first_stage_result = await self.db.execute(
            select(LoanWorkflowStage)
            .where(LoanWorkflowStage.workflow_id == workflow.id)
            .order_by(LoanWorkflowStage.sort_order.asc())
            .limit(1)
        )
        first_stage = first_stage_result.scalar_one_or_none()
        if not first_stage:
            application.status = ApplicationStatus.SUBMITTED
            return

        now = datetime.now(timezone.utc)
        application.workflow_id = workflow.id
        application.current_stage_id = first_stage.id
        application.current_stage_entered_at = now
        application.status = ApplicationStatus.UNDER_REVIEW
        first_name = first_stage.name
        first_id = first_stage.id

        await self.audit.log_system(
            application.id,
            AuditEventType.WORKFLOW_ASSIGNED,
            message=f"Assigned workflow v{workflow.version}",
            metadata={
                "workflow_id": workflow.id,
                "workflow_version": workflow.version,
                "first_stage": first_name,
            },
        )
        await self.audit.log_system(
            application.id,
            AuditEventType.STAGE_ENTERED,
            message=f"Entered stage: {first_name}",
            metadata={"stage_id": first_id, "stage_name": first_name},
        )

    async def act_on_current_stage(
        self,
        application: LoanApplication,
        staff: Staff,
        *,
        action: StageDecisionAction,
        note: str | None = None,
        ip: str | None = None,
    ) -> LoanApplication:
        if not application.current_stage_id or not application.workflow_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Application is not in an active workflow stage",
            )
        if application.status in (ApplicationStatus.REJECTED, ApplicationStatus.DISBURSED):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Application is already closed")
        if application.status == ApplicationStatus.OFFER_SENT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Waiting for the customer to accept or reject the loan offer",
            )

        stage = await self._get_stage(application.current_stage_id)
        self._ensure_staff_can_approve(staff, stage)

        now = datetime.now(timezone.utc)
        entered_at = _utc_aware(application.current_stage_entered_at or now)
        duration = int((now - entered_at).total_seconds())

        self.db.add(
            ApplicationStageDecision(
                application_id=application.id,
                stage_id=stage.id,
                staff_id=staff.id,
                action=action,
                note=note,
                entered_at=entered_at,
                decided_at=now,
                duration_seconds=max(duration, 0),
            )
        )

        if action == StageDecisionAction.REJECTED:
            application.status = ApplicationStatus.REJECTED
            application.rejected_at = now
            application.rejection_reason = note
            application.current_stage_id = None
            application.current_stage_entered_at = None
            stage_name = stage.name
            stage_id = stage.id
            await self.audit.log_staff(
                application.id,
                AuditEventType.STAGE_REJECTED,
                staff,
                message=f"Rejected at stage: {stage_name}",
                metadata={"stage_id": stage_id, "stage_name": stage_name, "duration_seconds": duration},
                ip_address=ip,
            )
            await notify.application_rejected(self.db, application)
            return application

        next_stage = await self._next_stage(application.workflow_id, stage.sort_order)
        if next_stage is None:
            ensure_documents_verified(application, action="final approval")
        stage_name = stage.name
        stage_id = stage.id

        if is_credit_offer_gate_stage(stage):
            amount = application.approved_amount or application.requested_amount
            if amount is None or amount <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Set the approved loan amount before sending the offer to the customer",
                )
            validate_terms(application)
            application.status = ApplicationStatus.OFFER_SENT
            application.offer_sent_at = now
            application.offer_gate_stage_id = stage.id
            application.offer_resume_stage_id = next_stage.id if next_stage else None
            await self.audit.log_staff(
                application.id,
                AuditEventType.STAGE_APPROVED,
                staff,
                message=f"Approved stage: {stage_name} — offer sent to customer",
                metadata={
                    "stage_id": stage_id,
                    "stage_name": stage_name,
                    "duration_seconds": duration,
                    "offer_resume_stage_id": application.offer_resume_stage_id,
                },
                ip_address=ip,
            )
            await notify.offer_sent_to_customer(self.db, application)
            return application

        if next_stage:
            application.current_stage_id = next_stage.id
            application.current_stage_entered_at = now
            next_name = next_stage.name
            next_id = next_stage.id
            await self.audit.log_staff(
                application.id,
                AuditEventType.STAGE_APPROVED,
                staff,
                message=f"Approved stage: {stage_name}",
                metadata={"stage_id": stage_id, "stage_name": stage_name, "duration_seconds": duration},
                ip_address=ip,
            )
            await self.audit.log_system(
                application.id,
                AuditEventType.STAGE_ENTERED,
                message=f"Entered stage: {next_name}",
                metadata={"stage_id": next_id, "stage_name": next_name},
            )
        else:
            application.status = ApplicationStatus.APPROVED
            application.approved_at = now
            application.current_stage_id = None
            application.current_stage_entered_at = None
            await self.audit.log_staff(
                application.id,
                AuditEventType.STAGE_APPROVED,
                staff,
                message=f"Final approval at stage: {stage_name}",
                metadata={"stage_id": stage_id, "stage_name": stage_name, "duration_seconds": duration},
                ip_address=ip,
            )
            if application.offer_accepted_at:
                await notify.application_fully_approved(self.db, application)
            else:
                await notify.application_approved(self.db, application)

        return application

    async def resume_after_customer_offer_accept(self, application: LoanApplication) -> None:
        """Move the pipeline forward after the borrower accepts a post-credit offer."""
        if application.status != ApplicationStatus.OFFER_SENT:
            return
        now = datetime.now(timezone.utc)
        resume_id = application.offer_resume_stage_id
        application.offer_gate_stage_id = None
        application.offer_sent_at = None
        application.offer_resume_stage_id = None

        if not resume_id:
            ensure_documents_verified(application, action="final approval")
            application.status = ApplicationStatus.APPROVED
            application.approved_at = now
            application.current_stage_id = None
            application.current_stage_entered_at = None
            await self.audit.log_system(
                application.id,
                AuditEventType.STATUS_CHANGED,
                message="Customer accepted offer — application fully approved",
                metadata={"status": ApplicationStatus.APPROVED.value},
            )
            await notify.application_fully_approved(self.db, application)
            return

        resume_stage = await self._get_stage(resume_id)
        application.status = ApplicationStatus.OFFER_ACCEPTED
        application.current_stage_id = resume_stage.id
        application.current_stage_entered_at = now
        await self.audit.log_system(
            application.id,
            AuditEventType.STATUS_CHANGED,
            message="Customer accepted offer — workflow resumed",
            metadata={"status": ApplicationStatus.OFFER_ACCEPTED.value, "stage_id": resume_stage.id},
        )
        await self.audit.log_system(
            application.id,
            AuditEventType.STAGE_ENTERED,
            message=f"Entered stage: {resume_stage.name}",
            metadata={"stage_id": resume_stage.id, "stage_name": resume_stage.name},
        )
        application.status = ApplicationStatus.UNDER_REVIEW

    async def resume_after_customer_offer_reject(self, application: LoanApplication) -> None:
        """Return to credit review after the borrower declines the offer."""
        if application.status != ApplicationStatus.OFFER_SENT:
            return
        application.offer_sent_at = None
        application.offer_resume_stage_id = None
        application.offer_accepted_at = None
        application.offer_terms_hash = None
        if application.offer_gate_stage_id:
            application.current_stage_id = application.offer_gate_stage_id
        application.offer_gate_stage_id = None
        application.status = ApplicationStatus.UNDER_REVIEW
        await self.audit.log_system(
            application.id,
            AuditEventType.STATUS_CHANGED,
            message="Customer declined the loan offer",
            metadata={"status": ApplicationStatus.UNDER_REVIEW.value},
        )

    async def disburse_application(
        self,
        application: LoanApplication,
        staff: Staff,
        *,
        note: str | None = None,
        ip: str | None = None,
    ) -> LoanApplication:
        return await DisbursementService(self.db).initiate_loan_disbursement(
            application, staff, note=note, ip=ip
        )

    @staticmethod
    def compute_processing_seconds(application: LoanApplication) -> int | None:
        if not application.submitted_at:
            return None
        end = application.rejected_at or application.disbursed_at or application.approved_at
        if not end:
            return None
        return int((_utc_aware(end) - _utc_aware(application.submitted_at)).total_seconds())

    async def _replace_stages(self, workflow: LoanWorkflow, stages: list[dict]) -> None:
        existing = await self.db.execute(
            select(LoanWorkflowStage).where(LoanWorkflowStage.workflow_id == workflow.id)
        )
        for stage in existing.scalars().all():
            await self.db.delete(stage)
        await self.db.flush()

        for index, item in enumerate(stages):
            role_id = item["approver_role_id"]
            role = await self.db.get(Role, role_id)
            if not role:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Role not found: {role_id}")

            self.db.add(
                LoanWorkflowStage(
                    workflow_id=workflow.id,
                    sort_order=index + 1,
                    name=item["name"].strip(),
                    slug=item.get("slug") or self._slugify(item["name"]),
                    description=item.get("description"),
                    approver_role_id=role_id,
                )
            )
        await self.db.flush()

    async def _get_stage(self, stage_id: str) -> LoanWorkflowStage:
        result = await self.db.execute(
            select(LoanWorkflowStage)
            .options(selectinload(LoanWorkflowStage.approver_role))
            .where(LoanWorkflowStage.id == stage_id)
        )
        stage = result.scalar_one_or_none()
        if not stage:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow stage not found")
        return stage

    async def _next_stage(self, workflow_id: str, current_order: int) -> LoanWorkflowStage | None:
        result = await self.db.execute(
            select(LoanWorkflowStage)
            .where(LoanWorkflowStage.workflow_id == workflow_id, LoanWorkflowStage.sort_order > current_order)
            .order_by(LoanWorkflowStage.sort_order.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _ensure_staff_can_approve(staff: Staff, stage: LoanWorkflowStage) -> None:
        if staff.is_super_admin:
            return
        role_id = stage.approver_role_id
        role_name = stage.approver_role.name if stage.approver_role else "assigned role"
        if not staff.role_id or staff.role_id != role_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only {role_name} can act on stage: {stage.name}",
            )

    @staticmethod
    def _slugify(name: str) -> str:
        return name.lower().strip().replace(" ", "_").replace("-", "_")[:80]
