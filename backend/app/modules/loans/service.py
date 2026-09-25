from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from collections import Counter

import structlog
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.modules.loans.audit_service import ApplicationAuditService
from app.modules.loans.constants import DOCUMENT_LABELS, LOAN_PRODUCT_SEED
from app.modules.loans.models import (
    ApplicationCollateral,
    ApplicationDocument,
    ApplicationGuarantor,
    ApplicationStatusLog,
    Loan,
    LoanApplication,
    LoanProduct,
)
from app.modules.loans.workflow_models import (
    ApplicationStageDecision,
    AuditEventType,
    LoanWorkflow,
    LoanWorkflowStage,
    StageDecisionAction,
)
from app.modules.loans.workflow_schemas import (
    ApplicationWorkflowStateResponse,
    DisburseApplicationRequest,
    PipelineStageSummary,
    StageActionRequest,
    StageDecisionResponse,
    WorkflowResponse,
    WorkflowStageInput,
    WorkflowStageResponse,
)
from app.modules.users.models import Customer
from app.modules.loans.workflow_service import WorkflowService
from app.modules.admin.models import Role, Staff
from app.modules.admin.schemas import (
    AdminDashboardResponse,
    DashboardDailySubmission,
    DashboardDemographics,
    DashboardProductMix,
    DashboardStatusCount,
    DemographicBucket,
)
from app.modules.loans.schemas import (
    ApplicationDocumentResponse,
    ApplicationStatus,
    ApplicationStatusUpdate,
    LoanStatus,
    CollateralInput,
    CreateApplicationRequest,
    DocumentChecklistItem,
    DocumentStatus,
    GuarantorInput,
    LoanApplicationDetailResponse,
    LoanApplicationSummaryResponse,
    CollateralResponse,
    GuarantorResponse,
    LoanProductResponse,
    LoanResponse,
    PipelineStageBrief,
    UniversalFormData,
    UpdateApplicationStepRequest,
    VerifyDocumentRequest,
)
from app.modules.loans.servicing import resolve_tenure_months
from app.modules.loans.storage import DocumentStorage

logger = structlog.get_logger()

UNIVERSAL_REQUIRED_FIELDS = (
    "full_name",
    "residential_address",
    "phone",
    "bvn",
    "bank_name",
    "bank_code",
    "bank_account_name",
    "bank_account_number",
    "next_of_kin_name",
    "next_of_kin_phone",
    "next_of_kin_relationship",
    "requested_amount",
    "purpose",
    "monthly_income",
    "repayment_period",
    "source_of_repayment",
)


async def seed_loan_products(db: AsyncSession) -> None:
    for item in LOAN_PRODUCT_SEED:
        result = await db.execute(select(LoanProduct).where(LoanProduct.code == item["code"]))
        existing = result.scalar_one_or_none()
        if existing:
            continue
        db.add(LoanProduct(**item))
    await db.flush()


# Repeat views of an application by the same staff member inside this window aren't re-logged.
VIEW_AUDIT_WINDOW = timedelta(minutes=15)

class LoanService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.storage = DocumentStorage()

    async def list_products(self, *, active_only: bool = True) -> list[LoanProductResponse]:
        query = select(LoanProduct).order_by(LoanProduct.name)
        if active_only:
            query = query.where(LoanProduct.is_active.is_(True))
        result = await self.db.execute(query)
        return [LoanProductResponse.model_validate(p) for p in result.scalars().all()]

    async def set_product_active(self, product_code: str, *, is_active: bool) -> LoanProductResponse:
        product = await self._get_product_by_code(product_code)
        product.is_active = is_active
        await self.db.flush()
        return LoanProductResponse.model_validate(product)

    async def list_customer_loans(self, customer_id: str) -> list[LoanResponse]:
        result = await self.db.execute(select(Loan).where(Loan.customer_id == customer_id))
        return [LoanResponse.model_validate(row) for row in result.scalars().all()]

    async def list_applications(
        self,
        *,
        customer_id: str | None = None,
        status: ApplicationStatus | None = None,
        product_code: str | None = None,
    ) -> list[LoanApplicationSummaryResponse]:
        query = select(LoanApplication).options(
            selectinload(LoanApplication.product),
            selectinload(LoanApplication.workflow).selectinload(LoanWorkflow.stages).selectinload(
                LoanWorkflowStage.approver_role
            ),
            selectinload(LoanApplication.current_stage).selectinload(LoanWorkflowStage.approver_role),
            selectinload(LoanApplication.stage_decisions),
        )
        if customer_id:
            query = query.where(LoanApplication.customer_id == customer_id)
        if status:
            query = query.where(LoanApplication.status == status)
        if product_code:
            query = query.join(LoanProduct).where(LoanProduct.code == product_code)
        result = await self.db.execute(query.order_by(LoanApplication.created_at.desc()))
        return [self._summary(app) for app in result.scalars().all()]

    async def list_applications_page(
        self,
        *,
        customer_id: str | None = None,
        status: ApplicationStatus | None = None,
        statuses: tuple[ApplicationStatus, ...] | None = None,
        product_code: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LoanApplicationSummaryResponse], int]:
        conditions = []
        if search and search.strip():
            from app.modules.users.models import Customer
            from app.modules.users.search import customer_search_clause

            conditions.append(
                LoanApplication.customer_id.in_(select(Customer.id).where(customer_search_clause(search)))
            )
        if customer_id:
            conditions.append(LoanApplication.customer_id == customer_id)
        if status:
            conditions.append(LoanApplication.status == status)
        if statuses:
            conditions.append(LoanApplication.status.in_(statuses))
        count_query = select(func.count()).select_from(LoanApplication).where(*conditions)
        query = select(LoanApplication).options(
            selectinload(LoanApplication.product),
            selectinload(LoanApplication.workflow).selectinload(LoanWorkflow.stages).selectinload(
                LoanWorkflowStage.approver_role
            ),
            selectinload(LoanApplication.current_stage).selectinload(LoanWorkflowStage.approver_role),
            selectinload(LoanApplication.stage_decisions),
        ).where(*conditions)
        if product_code:
            count_query = count_query.join(LoanProduct).where(LoanProduct.code == product_code)
            query = query.join(LoanProduct).where(LoanProduct.code == product_code)
        total = await self.db.scalar(count_query)
        result = await self.db.execute(
            query.order_by(LoanApplication.created_at.desc()).limit(limit).offset(offset)
        )
        return [self._summary(app) for app in result.scalars().all()], int(total or 0)

    async def get_dashboard(self) -> AdminDashboardResponse:
        status_rows = await self.db.execute(
            select(LoanApplication.status, func.count()).group_by(LoanApplication.status)
        )
        status_map: dict[ApplicationStatus, int] = {}
        for status_val, count in status_rows.all():
            key = status_val if isinstance(status_val, ApplicationStatus) else ApplicationStatus(status_val)
            status_map[key] = count

        status_counts = [
            DashboardStatusCount(status=s.value, count=c) for s, c in sorted(status_map.items(), key=lambda x: x[0].value)
        ]
        total_applications = sum(status_map.values())

        pending_review_count = status_map.get(ApplicationStatus.UNDER_REVIEW, 0) + status_map.get(
            ApplicationStatus.SUBMITTED, 0
        )

        # Money figures come from the loan book, not application fields. The old
        # query summed approved_amount, which is null when a loan is disbursed at
        # the requested amount — so "total disbursed" read ₦0 — and "loan book"
        # was just disbursed principal again, ignoring repayments.
        total_disbursed = await self.db.scalar(
            select(func.coalesce(func.sum(Loan.disbursed_amount), 0))
        ) or Decimal("0")
        loan_book = await self.db.scalar(
            select(func.coalesce(func.sum(Loan.principal_outstanding), 0)).where(
                Loan.status.in_((LoanStatus.ACTIVE, LoanStatus.OVERDUE))
            )
        ) or Decimal("0")

        # Bounded queries. This used to load EVERY application (with four
        # relationship loads each) just to show 10, plus 7 separate count queries.
        recent_applications, _ = await self.list_applications_page(limit=10)
        pending_queue, _ = await self.list_applications_page(
            statuses=(ApplicationStatus.UNDER_REVIEW, ApplicationStatus.SUBMITTED), limit=5
        )

        today = datetime.now(timezone.utc).date()
        window_start = datetime.combine(today - timedelta(days=6), datetime.min.time(), tzinfo=timezone.utc)
        activity_at = func.coalesce(LoanApplication.submitted_at, LoanApplication.created_at)
        stamps = (
            await self.db.execute(select(activity_at).where(activity_at >= window_start))
        ).scalars().all()
        per_day = Counter(
            (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date()
            for stamp in stamps
        )
        daily_submissions = [
            DashboardDailySubmission(
                date=(today - timedelta(days=offset)).isoformat(),
                count=per_day.get(today - timedelta(days=offset), 0),
            )
            for offset in range(6, -1, -1)
        ]

        product_rows = await self.db.execute(
            select(LoanProduct.code, LoanProduct.name, func.count())
            .join(LoanApplication, LoanApplication.product_id == LoanProduct.id)
            .group_by(LoanProduct.code, LoanProduct.name)
            .order_by(func.count().desc())
        )
        product_data = product_rows.all()
        product_total = sum(row[2] for row in product_data) or 1
        product_mix = [
            DashboardProductMix(
                product_code=code,
                product_name=name,
                count=count,
                percentage=round(count / product_total * 100, 1),
            )
            for code, name, count in product_data
        ]

        demographics = await self._compute_demographics()

        return AdminDashboardResponse(
            total_applications=total_applications,
            status_counts=status_counts,
            pending_review_count=pending_review_count,
            total_disbursed_amount=float(total_disbursed),
            loan_book_amount=float(loan_book),
            recent_applications=recent_applications,
            pending_queue=pending_queue,
            daily_submissions=daily_submissions,
            product_mix=product_mix,
            demographics=demographics,
        )

    async def get_demographics(self) -> DashboardDemographics:
        return await self._compute_demographics()

    @staticmethod
    def demographics_to_csv(demo: DashboardDemographics) -> str:
        lines = ["Section,Label,Count,Percentage"]
        for section, buckets in (
            ("Gender", demo.gender),
            ("Age", demo.age_buckets),
            ("State of residence", demo.state_of_residence),
            ("State of origin", demo.state_of_origin),
        ):
            for bucket in buckets:
                label = bucket.label.replace(",", " ")
                lines.append(f"{section},{label},{bucket.count},{bucket.percentage}")
        lines.append("")
        lines.append(f"Total applicants,{demo.total_applicants},,")
        return "\n".join(lines)

    async def get_document_for_download(
        self, application_id: str, document_id: str
    ) -> tuple[Path, str, str]:
        result = await self.db.execute(
            select(ApplicationDocument).where(
                ApplicationDocument.id == document_id,
                ApplicationDocument.application_id == application_id,
            )
        )
        document = result.scalar_one_or_none()
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        path = self.storage.resolve_path(application_id, document.file_key)
        return path, document.file_name, document.mime_type

    async def create_application(
        self,
        customer: Customer,
        payload: CreateApplicationRequest,
    ) -> LoanApplicationDetailResponse:
        product = await self._get_active_product(payload.product_code.value)
        universal = self._default_universal_form(customer)

        application = LoanApplication(
            customer_id=customer.id,
            product_id=product.id,
            status=ApplicationStatus.DRAFT,
            channel=payload.channel,
            step=1,
            total_steps=len(product.workflow_steps) or 6,
            branch=customer.branch or settings.default_branch,
            universal_form=universal,
            product_data={},
        )
        self.db.add(application)
        await self.db.flush()
        await self._log_status(application, None, ApplicationStatus.DRAFT.value, note="Application created")
        await ApplicationAuditService(self.db).log_customer(
            application.id,
            AuditEventType.APPLICATION_CREATED,
            customer,
            message="Customer started loan application",
            metadata={"product_code": product.code},
        )
        await self.db.refresh(application, attribute_names=["product"])
        return await self.get_application(application.id, customer_id=customer.id)

    async def update_application_step(
        self,
        application_id: str,
        customer_id: str,
        payload: UpdateApplicationStepRequest,
    ) -> LoanApplicationDetailResponse:
        application = await self._get_application_for_customer(application_id, customer_id)
        self._ensure_editable(application)

        application.step = payload.step
        application.total_steps = payload.total_steps

        if payload.universal_form:
            merged = {
                **application.universal_form,
                **payload.universal_form.model_dump(mode="json", exclude_none=True),
            }
            application.universal_form = merged
            if merged.get("requested_amount") is not None:
                application.requested_amount = Decimal(str(merged["requested_amount"]))

        if payload.product_data is not None:
            application.product_data = {
                **application.product_data,
                **{k: v for k, v in payload.product_data.items() if v is not None},
            }

        if payload.guarantors is not None:
            await self._replace_guarantors(application, payload.guarantors)
        if payload.collaterals is not None:
            await self._replace_collaterals(application, payload.collaterals)

        await self.db.flush()
        await self.db.refresh(application, attribute_names=["guarantors", "collaterals", "product"])
        return await self.get_application(application.id, customer_id=customer_id)

    async def upload_document(
        self,
        application_id: str,
        customer_id: str,
        document_type: str,
        upload: UploadFile,
    ) -> LoanApplicationDetailResponse:
        application = await self._get_application_for_customer(application_id, customer_id)
        replacing_rejected = application.status != ApplicationStatus.DRAFT
        if replacing_rejected:
            self._ensure_reupload_allowed(application, document_type)

        if document_type not in application.product.required_document_types:
            raise AppError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ErrorCode.DOCUMENT_TYPE_NOT_ALLOWED,
                f"Document type '{document_type}' is not required for this product",
            )

        file_key, file_name, mime_type, size_bytes = await self.storage.save(
            application_id=application_id,
            document_type=document_type,
            upload=upload,
        )

        existing = await self.db.execute(
            select(ApplicationDocument).where(
                ApplicationDocument.application_id == application_id,
                ApplicationDocument.document_type == document_type,
            )
        )
        for doc in existing.scalars().all():
            await self.db.delete(doc)

        self.db.add(
            ApplicationDocument(
                application_id=application_id,
                document_type=document_type,
                file_key=file_key,
                file_name=file_name,
                mime_type=mime_type,
                size_bytes=size_bytes,
                status=DocumentStatus.PENDING,
                uploaded_by="customer",
            )
        )
        await self.db.flush()
        await self.db.refresh(application, attribute_names=["documents", "guarantors", "collaterals", "product"])
        if replacing_rejected:
            await self._after_reupload(application, customer_id, document_type)
        return await self.get_application(application_id, customer_id=customer_id)

    # After submission a customer may replace only what staff rejected, while it is still in review.
    _REUPLOAD_STATUSES = frozenset(
        {ApplicationStatus.SUBMITTED, ApplicationStatus.UNDER_REVIEW, ApplicationStatus.DOCUMENTS_INCOMPLETE}
    )

    def _ensure_reupload_allowed(self, application: LoanApplication, document_type: str) -> None:
        rejected = any(
            d.document_type == document_type and d.status == DocumentStatus.REJECTED for d in application.documents
        )
        if application.status not in self._REUPLOAD_STATUSES or not rejected:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.APPLICATION_NOT_EDITABLE,
                "Only documents we've asked you to replace can be uploaded now.",
            )

    async def _after_reupload(self, application: LoanApplication, customer_id: str, document_type: str) -> None:
        customer = await self.db.get(Customer, customer_id)
        if customer:
            await ApplicationAuditService(self.db).log_customer(
                application.id,
                AuditEventType.DOCUMENT_UPLOADED,
                customer,
                message=f"Customer replaced {DOCUMENT_LABELS.get(document_type, document_type)}",
                metadata={"document_type": document_type},
            )
        still_rejected = any(d.status == DocumentStatus.REJECTED for d in application.documents)
        if application.status == ApplicationStatus.DOCUMENTS_INCOMPLETE and not still_rejected:
            application.status = ApplicationStatus.UNDER_REVIEW
            await self._log_status(
                application,
                ApplicationStatus.DOCUMENTS_INCOMPLETE.value,
                ApplicationStatus.UNDER_REVIEW.value,
                note="Customer replaced the rejected documents",
                customer_id=customer_id,
            )
        await self.db.flush()

    async def submit_application(
        self,
        application_id: str,
        customer_id: str,
    ) -> LoanApplicationDetailResponse:
        application = await self._get_application_for_customer(application_id, customer_id)
        if application.status != ApplicationStatus.DRAFT:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Application already submitted")

        errors = self._validate_for_submission(application)
        if errors:
            raise AppError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ErrorCode.APPLICATION_INCOMPLETE,
                "Application incomplete",
                errors=errors,
            )

        application.status = ApplicationStatus.SUBMITTED
        application.submitted_at = datetime.now(timezone.utc)
        application.applicant_signed_at = datetime.now(timezone.utc)
        await self._log_status(
            application,
            ApplicationStatus.DRAFT.value,
            ApplicationStatus.SUBMITTED.value,
            note="Customer submitted application",
            customer_id=customer_id,
        )
        customer = await self.db.get(Customer, customer_id)
        if customer:
            await ApplicationAuditService(self.db).log_customer(
                application.id,
                AuditEventType.APPLICATION_SUBMITTED,
                customer,
                message="Customer submitted loan application",
            )
        await WorkflowService(self.db).assign_workflow_to_application(application)
        await self.db.flush()
        logger.info("loan_application_submitted", application_id=application_id, customer_id=customer_id)
        return await self.get_application(application_id, customer_id=customer_id)

    async def get_application_for_admin(
        self,
        application_id: str,
        *,
        staff: Staff,
        ip: str | None = None,
    ) -> LoanApplicationDetailResponse:
        application = await self._get_application(application_id)
        audit = ApplicationAuditService(self.db)
        # One view record per staff member per application per window: re-fetches after
        # each action on the page would otherwise flood the audit trail. Decisions and
        # changes are always logged separately.
        if await audit.logged_recently(
            application.id, AuditEventType.APPLICATION_VIEWED, staff.id, within=VIEW_AUDIT_WINDOW
        ):
            return self._detail(application)
        await audit.log_staff(
            application.id,
            AuditEventType.APPLICATION_VIEWED,
            staff,
            message="Staff opened application",
            ip_address=ip,
        )
        if (application.universal_form or {}).get("bvn"):
            await audit.log_staff(
                application.id,
                AuditEventType.BVN_VIEWED,
                staff,
                message="Staff viewed applicant BVN",
                metadata={"bvn_masked": Customer.mask_bvn(application.universal_form["bvn"])},
                ip_address=ip,
            )
        return self._detail(application)

    async def get_application_workflow_state(self, application_id: str) -> ApplicationWorkflowStateResponse:
        application = await self._get_application(application_id, load_workflow=True)
        workflow_svc = WorkflowService(self.db)
        current_stage = None
        if application.current_stage_id:
            stage = await self.db.get(LoanWorkflowStage, application.current_stage_id)
            if stage:
                role = await self.db.get(Role, stage.approver_role_id)
                current_stage = WorkflowStageResponse(
                    id=stage.id,
                    sort_order=stage.sort_order,
                    name=stage.name,
                    slug=stage.slug,
                    description=stage.description,
                    approver_role_id=stage.approver_role_id,
                    approver_role_name=role.name if role else None,
                )
        decisions = sorted(application.stage_decisions, key=lambda d: d.decided_at)
        decision_rows: list[StageDecisionResponse] = []
        for decision in decisions:
            # Loaded by _get_application(load_workflow=True); previously two
            # extra queries per decision.
            stage = decision.stage
            staff = decision.staff
            decision_rows.append(
                StageDecisionResponse(
                    id=decision.id,
                    stage_id=decision.stage_id,
                    stage_name=stage.name if stage else None,
                    staff_id=decision.staff_id,
                    staff_name=staff.full_name if staff else None,
                    action=decision.action,
                    note=decision.note,
                    entered_at=decision.entered_at,
                    decided_at=decision.decided_at,
                    duration_seconds=decision.duration_seconds,
                )
            )
        workflow_version = None
        if application.workflow_id:
            wf = await self.db.get(LoanWorkflow, application.workflow_id)
            workflow_version = wf.version if wf else None

        return ApplicationWorkflowStateResponse(
            workflow_id=application.workflow_id,
            workflow_version=workflow_version,
            current_stage=current_stage,
            current_stage_entered_at=application.current_stage_entered_at,
            pipeline_stages=self._build_pipeline_stages(application),
            stage_decisions=decision_rows,
            processing_duration_seconds=workflow_svc.compute_processing_seconds(application),
            submitted_at=application.submitted_at,
            approved_at=application.approved_at,
            rejected_at=application.rejected_at,
            disbursed_at=application.disbursed_at,
        )

    async def act_on_stage(
        self,
        application_id: str,
        staff: Staff,
        payload: StageActionRequest,
        *,
        ip: str | None = None,
    ) -> LoanApplicationDetailResponse:
        application = await self._get_application(application_id)
        await WorkflowService(self.db).act_on_current_stage(
            application, staff, action=payload.action, note=payload.note, ip=ip
        )
        await self.db.flush()
        return self._detail(application)

    async def disburse_application(
        self,
        application_id: str,
        staff: Staff,
        payload: DisburseApplicationRequest,
        *,
        ip: str | None = None,
    ) -> LoanApplicationDetailResponse:
        application = await self._get_application(application_id)
        await WorkflowService(self.db).disburse_application(application, staff, note=payload.note, ip=ip)
        await self.db.flush()
        return self._detail(application)

    async def record_manual_disbursement(
        self,
        application_id: str,
        staff: Staff,
        payload,
        *,
        ip: str | None = None,
    ) -> LoanApplicationDetailResponse:
        from datetime import date as _date

        from app.modules.payments.disbursement_service import DisbursementService

        application = await self._get_application(application_id)
        await DisbursementService(self.db).record_manual(
            application,
            staff,
            external_reference=payload.external_reference,
            disbursed_on=payload.disbursed_on or _date.today(),
            note=payload.note,
            ip=ip,
        )
        await self.db.flush()
        return self._detail(application)

    async def get_active_product_workflow(self, product_code: str):
        product = await self._get_product_by_code(product_code)
        workflow = await WorkflowService(self.db).get_active_workflow(product.id)
        if not workflow:
            return None
        return await WorkflowService(self.db).to_response(workflow)

    async def list_product_workflows(self, product_code: str) -> list[WorkflowResponse]:
        product = await self._get_product_by_code(product_code)
        workflows = await WorkflowService(self.db).list_workflows_for_product(product.id)
        svc = WorkflowService(self.db)
        return [await svc.to_response(w) for w in workflows]

    async def create_product_workflow(
        self,
        product_code: str,
        stages: list[WorkflowStageInput],
        *,
        staff_id: str,
    ):
        product = await self._get_product_by_code(product_code)
        stage_dicts = [s.model_dump() for s in stages]
        workflow = await WorkflowService(self.db).create_draft_workflow(
            product, stages=stage_dicts, staff_id=staff_id
        )
        return await WorkflowService(self.db).to_response(workflow)

    async def update_workflow_stages(self, workflow_id: str, stages: list[WorkflowStageInput]):
        stage_dicts = [s.model_dump() for s in stages]
        workflow = await WorkflowService(self.db).update_draft_stages(workflow_id, stage_dicts)
        return await WorkflowService(self.db).to_response(workflow)

    async def publish_workflow(self, workflow_id: str):
        workflow = await WorkflowService(self.db).publish_workflow(workflow_id)
        return await WorkflowService(self.db).to_response(workflow)

    async def list_audit_log(self, application_id: str):
        await self._get_application(application_id)
        return await ApplicationAuditService(self.db).list_for_application(application_id)

    async def get_application(
        self,
        application_id: str,
        *,
        customer_id: str | None = None,
    ) -> LoanApplicationDetailResponse:
        application = await self._get_application(application_id, customer_id=customer_id)
        return self._detail(application)

    # Statuses in which staff may still adjust terms or reject manually.
    _MANUALLY_ADJUSTABLE = frozenset(
        {
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.UNDER_REVIEW,
            ApplicationStatus.DOCUMENTS_INCOMPLETE,
            ApplicationStatus.APPROVED,
        }
    )

    async def update_application_status(
        self,
        application_id: str,
        payload: ApplicationStatusUpdate,
        *,
        staff: Staff,
        ip: str | None = None,
    ) -> LoanApplicationDetailResponse:
        application = await self._get_application(application_id)
        current = application.status

        if current not in self._MANUALLY_ADJUSTABLE:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.INVALID_STATUS_TRANSITION,
                f"Application is {current.value}; it can no longer be changed manually.",
            )
        target = payload.status
        if target is not None and target not in (current, ApplicationStatus.REJECTED):
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.INVALID_STATUS_TRANSITION,
                "Only rejection can be applied manually. Approve through the workflow "
                "stages and disburse through the disburse action.",
            )
        if target == ApplicationStatus.REJECTED and not (payload.note or "").strip():
            raise AppError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ErrorCode.INVALID_STATUS_TRANSITION,
                "A rejection reason (note) is required.",
            )
        if (
            target is None
            and payload.approved_amount is None
            and payload.repayment_cadence is None
            and payload.tenure_months is None
        ):
            raise AppError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "VALIDATION_ERROR",
                "Nothing to update.",
            )

        changes: dict = {}
        if payload.approved_amount is not None:
            changes["approved_amount"] = {
                "from": str(application.approved_amount) if application.approved_amount else None,
                "to": str(payload.approved_amount),
            }
            application.approved_amount = payload.approved_amount
        if payload.repayment_cadence is not None:
            changes["repayment_cadence"] = {
                "from": application.repayment_cadence,
                "to": payload.repayment_cadence.value,
            }
            application.repayment_cadence = payload.repayment_cadence.value
        if payload.tenure_months is not None:
            changes["tenure_months"] = {
                "from": application.approved_tenure_months,
                "to": payload.tenure_months,
            }
            application.approved_tenure_months = payload.tenure_months

        if target == ApplicationStatus.REJECTED and current != ApplicationStatus.REJECTED:
            now = datetime.now(timezone.utc)
            application.status = ApplicationStatus.REJECTED
            application.rejected_at = now
            application.rejection_reason = payload.note
            application.current_stage_id = None
            application.current_stage_entered_at = None
            changes["status"] = {"from": current.value, "to": ApplicationStatus.REJECTED.value}
            await self._log_status(
                application,
                current.value,
                ApplicationStatus.REJECTED.value,
                note=payload.note,
                staff_id=staff.id,
            )

        await ApplicationAuditService(self.db).log_staff(
            application.id,
            AuditEventType.STATUS_CHANGED,
            staff,
            message=payload.note or "Loan terms updated",
            metadata={"changes": changes},
            ip_address=ip,
        )
        await self.db.flush()
        return self._detail(application)

    async def verify_document(
        self,
        application_id: str,
        document_id: str,
        payload: VerifyDocumentRequest,
        *,
        staff_id: str,
        staff: Staff | None = None,
        ip: str | None = None,
    ) -> LoanApplicationDetailResponse:
        application = await self._get_application(application_id)
        result = await self.db.execute(
            select(ApplicationDocument).where(
                ApplicationDocument.id == document_id,
                ApplicationDocument.application_id == application_id,
            )
        )
        document = result.scalar_one_or_none()
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        document.status = payload.status
        document.verified_by = staff_id
        document.verified_at = datetime.now(timezone.utc)
        document.rejection_note = payload.rejection_note if payload.status == DocumentStatus.REJECTED else None

        if staff:
            event = (
                AuditEventType.DOCUMENT_VERIFIED
                if payload.status == DocumentStatus.VERIFIED
                else AuditEventType.DOCUMENT_REJECTED
            )
            await ApplicationAuditService(self.db).log_staff(
                application.id,
                event,
                staff,
                message=f"Document {document.document_type} marked {payload.status.value}",
                metadata={"document_id": document.id, "document_type": document.document_type},
                ip_address=ip,
            )

        await self.db.flush()
        return self._detail(application)

    async def _get_active_product(self, code: str) -> LoanProduct:
        result = await self.db.execute(
            select(LoanProduct).where(LoanProduct.code == code, LoanProduct.is_active.is_(True))
        )
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan product not found")
        return product

    async def _get_product_by_code(self, code: str) -> LoanProduct:
        result = await self.db.execute(select(LoanProduct).where(LoanProduct.code == code))
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan product not found")
        return product

    async def _get_application(
        self,
        application_id: str,
        *,
        customer_id: str | None = None,
        load_workflow: bool = False,
    ) -> LoanApplication:
        query = (
            select(LoanApplication)
            .options(
                selectinload(LoanApplication.product),
                selectinload(LoanApplication.documents),
                selectinload(LoanApplication.guarantors),
                selectinload(LoanApplication.collaterals),
            )
            .where(LoanApplication.id == application_id)
        )
        if load_workflow:
            query = query.options(
                selectinload(LoanApplication.workflow).selectinload(LoanWorkflow.stages).selectinload(
                    LoanWorkflowStage.approver_role
                ),
                selectinload(LoanApplication.current_stage).selectinload(LoanWorkflowStage.approver_role),
                selectinload(LoanApplication.stage_decisions).selectinload(
                    ApplicationStageDecision.stage
                ),
                selectinload(LoanApplication.stage_decisions).selectinload(
                    ApplicationStageDecision.staff
                ),
            )
        if customer_id:
            query = query.where(LoanApplication.customer_id == customer_id)
        result = await self.db.execute(query)
        application = result.scalar_one_or_none()
        if not application:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
        return application

    async def _get_application_for_customer(self, application_id: str, customer_id: str) -> LoanApplication:
        return await self._get_application(application_id, customer_id=customer_id)

    @staticmethod
    def _ensure_editable(application: LoanApplication) -> None:
        if application.status != ApplicationStatus.DRAFT:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.APPLICATION_NOT_EDITABLE,
                "Only draft applications can be edited",
            )

    @staticmethod
    def _default_universal_form(customer: Customer) -> dict:
        return UniversalFormData(
            full_name=customer.full_name,
            residential_address=customer.residential_address,
            phone=customer.phone_primary,
            gender=customer.gender,
            date_of_birth=customer.date_of_birth,
            state_of_origin=customer.state_of_origin,
            email=customer.email,
            bvn=customer.bvn,
            nature_of_business=None,
            marital_status=customer.marital_status,
        ).model_dump(mode="json")

    async def _replace_guarantors(self, application: LoanApplication, items: list[GuarantorInput]) -> None:
        for g in list(application.guarantors):
            await self.db.delete(g)
        for item in items:
            self.db.add(
                ApplicationGuarantor(
                    application_id=application.id,
                    full_name=item.full_name,
                    phone=item.phone,
                    bvn=item.bvn,
                    id_type=item.id_type,
                    id_number=item.id_number,
                    relationship_to_borrower=item.relationship,
                    address=item.address,
                )
            )

    async def _replace_collaterals(self, application: LoanApplication, items: list[CollateralInput]) -> None:
        for c in list(application.collaterals):
            await self.db.delete(c)
        for item in items:
            self.db.add(
                ApplicationCollateral(
                    application_id=application.id,
                    collateral_type=item.collateral_type,
                    description=item.description,
                    estimated_value=item.estimated_value,
                    affidavit_reference=item.affidavit_reference,
                )
            )

    async def _log_status(
        self,
        application: LoanApplication,
        from_status: str | None,
        to_status: str,
        *,
        note: str | None = None,
        staff_id: str | None = None,
        customer_id: str | None = None,
    ) -> None:
        self.db.add(
            ApplicationStatusLog(
                application_id=application.id,
                from_status=from_status,
                to_status=to_status,
                note=note,
                changed_by_staff_id=staff_id,
                changed_by_customer_id=customer_id,
            )
        )

    def _validate_for_submission(self, application: LoanApplication) -> list[str]:
        errors: list[str] = []
        form = application.universal_form or {}

        for field in UNIVERSAL_REQUIRED_FIELDS:
            if not form.get(field):
                errors.append(f"Missing universal form field: {field}")

        if not application.guarantors:
            errors.append("At least one guarantor is required")

        uploaded_types = {d.document_type for d in application.documents}
        for doc_type in application.product.required_document_types:
            if doc_type not in uploaded_types:
                label = DOCUMENT_LABELS.get(doc_type, doc_type)
                errors.append(f"Missing document: {label}")

        code = application.product.code
        data = application.product_data or {}

        if code == "business_loan":
            if not data.get("years_in_operation") or int(data["years_in_operation"]) < 3:
                errors.append("Business must be operating for at least 3 years")
            if not data.get("trade_type"):
                errors.append("Trade type is required for business loan")
        elif code == "payday_loan":
            if not data.get("employer_name"):
                errors.append("Employer name is required for payday loan")
            if not data.get("salary_pay_day"):
                errors.append("Salary pay day is required for payday loan")
        elif code == "study_loan":
            if not data.get("student_full_name") or not data.get("school_name"):
                errors.append("Student and school details are required for study loan")
        elif code == "asset_loan":
            if not data.get("asset_description") or not data.get("asset_value"):
                errors.append("Asset description and value are required for asset loan")

        return errors

    def _document_checklist(self, application: LoanApplication) -> list[DocumentChecklistItem]:
        uploaded = {d.document_type: d for d in application.documents}
        checklist: list[DocumentChecklistItem] = []
        for doc_type in application.product.required_document_types:
            doc = uploaded.get(doc_type)
            checklist.append(
                DocumentChecklistItem(
                    document_type=doc_type,
                    label=DOCUMENT_LABELS.get(doc_type, doc_type),
                    required=True,
                    uploaded=doc is not None,
                    status=doc.status if doc else None,
                    document_id=doc.id if doc else None,
                )
            )
        return checklist

    def _summary(self, application: LoanApplication) -> LoanApplicationSummaryResponse:
        universal = application.universal_form or {}
        applicant_name = universal.get("full_name") if isinstance(universal, dict) else None
        account_number = universal.get("bank_account_number") if isinstance(universal, dict) else None
        stage_name, stage_pct, role_name = self._queue_stage_fields(application)
        pipeline = self._build_pipeline_stages(application)
        return LoanApplicationSummaryResponse(
            id=application.id,
            customer_id=application.customer_id,
            applicant_name=applicant_name,
            product_code=application.product.code,
            product_name=application.product.name,
            status=application.status,
            channel=application.channel,
            branch=application.branch,
            account_number=str(account_number) if account_number else None,
            current_stage_name=stage_name,
            stage_progress_pct=stage_pct,
            approver_role_name=role_name,
            pipeline_stages=[
                PipelineStageBrief(name=s.name, status=s.status) for s in pipeline
            ],
            requested_amount=application.requested_amount,
            approved_amount=application.approved_amount,
            submitted_at=application.submitted_at,
            created_at=application.created_at,
        )

    @staticmethod
    def _queue_stage_fields(application: LoanApplication) -> tuple[str | None, int | None, str | None]:
        stage_count = len(application.workflow.stages) if application.workflow else 0
        current = application.current_stage
        role_name = current.approver_role.name if current and current.approver_role else None
        stage_name = current.name if current else None

        if application.status == ApplicationStatus.DISBURSED:
            return stage_name or "Disbursed", 100, role_name
        if application.status == ApplicationStatus.APPROVED:
            return stage_name or "Approved", 95, role_name
        if application.status == ApplicationStatus.REJECTED:
            return stage_name or "Rejected", 100, role_name
        if current and stage_count > 0:
            pct = min(100, max(5, int((current.sort_order / stage_count) * 100)))
            return stage_name, pct, role_name
        if application.total_steps:
            pct = min(100, max(5, int((application.step / application.total_steps) * 100)))
            return "Application", pct, None
        return stage_name, None, role_name

    async def _compute_demographics(self) -> DashboardDemographics:
        rows = await self.db.execute(
            select(
                Customer.gender,
                Customer.date_of_birth,
                Customer.state_of_residence,
                Customer.state_of_origin,
            ).join(LoanApplication, LoanApplication.customer_id == Customer.id)
        )

        gender_counts: Counter[str] = Counter()
        age_counts: Counter[str] = Counter()
        residence_counts: Counter[str] = Counter()
        origin_counts: Counter[str] = Counter()
        total = 0

        for gender, dob, state_res, state_origin in rows.all():
            total += 1
            gender_counts[self._normalize_gender(gender)] += 1
            age_counts[self._age_bucket(dob)] += 1
            residence_counts[self._normalize_state(state_res)] += 1
            origin_counts[self._normalize_state(state_origin)] += 1

        return DashboardDemographics(
            total_applicants=total,
            gender=self._demographic_buckets(gender_counts, total),
            age_buckets=self._demographic_buckets(age_counts, total),
            state_of_residence=self._demographic_buckets(residence_counts, total),
            state_of_origin=self._demographic_buckets(origin_counts, total),
        )

    @staticmethod
    def _normalize_gender(raw: str | None) -> str:
        if not raw:
            return "Unknown"
        value = raw.strip().lower()
        if value in ("m", "male"):
            return "Male"
        if value in ("f", "female"):
            return "Female"
        return raw.strip().title()

    @staticmethod
    def _normalize_state(raw: str | None) -> str:
        if not raw:
            return "Unknown"
        return raw.strip().title()

    @staticmethod
    def _age_bucket(dob: date | None) -> str:
        if not dob:
            return "Unknown"
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < 18:
            return "Under 18"
        if age <= 25:
            return "18–25"
        if age <= 35:
            return "26–35"
        if age <= 45:
            return "36–45"
        if age <= 55:
            return "46–55"
        return "56+"

    @staticmethod
    def _demographic_buckets(counter: Counter[str], total: int) -> list[DemographicBucket]:
        if total == 0:
            return []
        return [
            DemographicBucket(
                label=label,
                count=count,
                percentage=round(count / total * 100, 1),
            )
            for label, count in counter.most_common()
        ]

    @staticmethod
    def _build_pipeline_stages(application: LoanApplication) -> list[PipelineStageSummary]:
        if not application.workflow or not application.workflow.stages:
            return []

        stages = sorted(application.workflow.stages, key=lambda s: s.sort_order)
        decisions = {d.stage_id: d for d in (application.stage_decisions or [])}
        rejected = next(
            (d for d in (application.stage_decisions or []) if d.action == StageDecisionAction.REJECTED),
            None,
        )

        if application.status == ApplicationStatus.APPROVED or application.status == ApplicationStatus.DISBURSED:
            return [
                PipelineStageSummary(
                    id=s.id,
                    sort_order=s.sort_order,
                    name=s.name,
                    approver_role_name=s.approver_role.name if s.approver_role else None,
                    status="completed",
                )
                for s in stages
            ]

        if application.status == ApplicationStatus.REJECTED and rejected:
            rejected_order = next(s.sort_order for s in stages if s.id == rejected.stage_id)
            result: list[PipelineStageSummary] = []
            for stage in stages:
                if stage.id == rejected.stage_id:
                    status = "rejected"
                elif stage.sort_order < rejected_order:
                    status = "completed"
                else:
                    status = "upcoming"
                result.append(
                    PipelineStageSummary(
                        id=stage.id,
                        sort_order=stage.sort_order,
                        name=stage.name,
                        approver_role_name=stage.approver_role.name if stage.approver_role else None,
                        status=status,
                    )
                )
            return result

        current_id = application.current_stage_id
        result = []
        for stage in stages:
            decision = decisions.get(stage.id)
            if decision and decision.action == StageDecisionAction.APPROVED:
                status = "completed"
            elif stage.id == current_id:
                status = "current"
            else:
                status = "upcoming"
            result.append(
                PipelineStageSummary(
                    id=stage.id,
                    sort_order=stage.sort_order,
                    name=stage.name,
                    approver_role_name=stage.approver_role.name if stage.approver_role else None,
                    status=status,
                )
            )
        return result

    def _detail(self, application: LoanApplication) -> LoanApplicationDetailResponse:
        return LoanApplicationDetailResponse(
            id=application.id,
            customer_id=application.customer_id,
            product_code=application.product.code,
            product_name=application.product.name,
            status=application.status,
            channel=application.channel,
            step=application.step,
            total_steps=application.total_steps,
            branch=application.branch,
            requested_amount=application.requested_amount,
            approved_amount=application.approved_amount,
            repayment_cadence=application.repayment_cadence,
            approved_tenure_months=application.approved_tenure_months,
            tenure_months=resolve_tenure_months(application),
            universal_form=application.universal_form or {},
            product_data=application.product_data or {},
            submitted_at=application.submitted_at,
            assigned_officer_id=application.assigned_officer_id,
            rejection_reason=application.rejection_reason,
            guarantors=[GuarantorResponse.model_validate(g) for g in application.guarantors],
            collaterals=[CollateralResponse.model_validate(c) for c in application.collaterals],
            documents=[ApplicationDocumentResponse.model_validate(d) for d in application.documents],
            document_checklist=self._document_checklist(application),
        )
