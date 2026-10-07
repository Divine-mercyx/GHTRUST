from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse

from app.core.deps import DbSession
from app.core.rate_limit import get_client_ip
from app.modules.admin.deps import CurrentStaff, require_permission
from app.modules.admin.models import Staff
from app.modules.admin.permissions import (
    LOAN_CONFIGURE_WORKFLOW,
    LOAN_DISBURSE,
    LOAN_READ,
    LOAN_RECORD_REPAYMENT,
    LOAN_REVIEW,
    LOAN_VERIFY_DOCS,
)
from app.modules.loans.schemas import (
    ApplicationStatus,
    ApplicationStatusUpdate,
    LoanDetailResponse,
    LoanRepaymentResponse,
    LoanResponse,
    LoanStatus,
    ManualDisbursementRequest,
    Page,
    RecordRepaymentRequest,
    LoanApplicationDetailResponse,
    LoanApplicationSummaryResponse,
    LoanProductResponse,
    CreateLoanProductRequest,
    LoanProductToggleRequest,
    VerifyDocumentRequest,
)
from app.core.errors import AppError
from app.modules.legal.router import LoanOfferResponse, _offer
from app.modules.legal.service import build_offer
from app.modules.loans.service import LoanService
from app.modules.loans.servicing import (
    LoanServicingService,
    list_loans,
    loan_detail,
    loan_responses,
)
from app.modules.loans.workflow_schemas import (
    ApplicationWorkflowStateResponse,
    AuditLogResponse,
    CreateWorkflowRequest,
    DisburseApplicationRequest,
    StageActionRequest,
    UpdateWorkflowStagesRequest,
    WorkflowResponse,
)

router = APIRouter(prefix="/admin/loans", tags=["Admin — Loans"])


@router.get("/products", response_model=list[LoanProductResponse])
async def admin_list_products(
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_READ)),
):
    return await LoanService(db).list_products(active_only=False)


@router.post(
    "/products",
    response_model=LoanProductResponse,
    status_code=201,
    summary="Create loan product",
    description="Created switched off. Publish an approval workflow for it, then switch it on.",
)
async def admin_create_product(
    payload: CreateLoanProductRequest,
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_CONFIGURE_WORKFLOW)),
):
    return await LoanService(db).create_product(payload)


@router.patch("/products/{product_code}", response_model=LoanProductResponse, summary="Toggle loan product")
async def admin_toggle_product(
    product_code: str,
    payload: LoanProductToggleRequest,
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_CONFIGURE_WORKFLOW)),
):
    return await LoanService(db).set_product_active(product_code, is_active=payload.is_active)


@router.get(
    "/applications",
    response_model=list[LoanApplicationSummaryResponse],
    description="Newest first. Total count is returned in the `X-Total-Count` header.",
)
async def admin_list_applications(
    response: Response,
    db: DbSession,
    status_filter: ApplicationStatus | None = Query(default=None, alias="status"),
    product_code: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100, description="Applicant name, phone, account or exact BVN"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: Staff = Depends(require_permission(LOAN_READ)),
):
    items, total = await LoanService(db).list_applications_page(
        status=status_filter, product_code=product_code, search=search, limit=limit, offset=offset
    )
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get("/applications/{application_id}", response_model=LoanApplicationDetailResponse)
async def admin_get_application(
    application_id: str,
    request: Request,
    db: DbSession,
    staff: CurrentStaff,
    _: Staff = Depends(require_permission(LOAN_READ)),
):
    ip = get_client_ip(request)
    return await LoanService(db).get_application_for_admin(application_id, staff=staff, ip=ip)


@router.get("/applications/{application_id}/workflow", response_model=ApplicationWorkflowStateResponse)
async def admin_get_application_workflow(
    application_id: str,
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_READ)),
):
    return await LoanService(db).get_application_workflow_state(application_id)


@router.get("/applications/{application_id}/audit-log", response_model=list[AuditLogResponse])
async def admin_get_application_audit_log(
    application_id: str,
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_READ)),
):
    logs = await LoanService(db).list_audit_log(application_id)
    return [AuditLogResponse.model_validate(log) for log in logs]


@router.get(
    "/applications/{application_id}/offer-preview",
    response_model=LoanOfferResponse,
    summary="Repayment schedule the customer would see (estimated from today)",
)
async def admin_offer_preview(
    application_id: str,
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_READ)),
    approved_amount: Decimal | None = Query(default=None, gt=0),
    tenure_months: int | None = Query(default=None, ge=1, le=60),
    repayment_cadence: str | None = Query(default=None),
):
    """Same math as the mobile offer; optional query params preview unsaved term edits."""
    from sqlalchemy.orm.attributes import set_committed_value

    application = await LoanService(db)._get_application(application_id)
    # set_committed_value changes the loaded object without marking it dirty: the request
    # session commits at the end, and a preview must never save the edited terms.
    if approved_amount is not None:
        set_committed_value(application, "approved_amount", approved_amount)
    if tenure_months is not None:
        set_committed_value(application, "approved_tenure_months", tenure_months)
    if repayment_cadence:
        set_committed_value(application, "repayment_cadence", repayment_cadence)
    try:
        return _offer(build_offer(application))
    except AppError:
        raise
    except ValueError as exc:
        raise AppError(status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", str(exc)) from exc


@router.post("/applications/{application_id}/stage-action", response_model=LoanApplicationDetailResponse)
async def admin_stage_action(
    application_id: str,
    payload: StageActionRequest,
    request: Request,
    db: DbSession,
    staff: CurrentStaff,
    _: Staff = Depends(require_permission(LOAN_REVIEW)),
):
    ip = get_client_ip(request)
    return await LoanService(db).act_on_stage(application_id, staff, payload, ip=ip)


@router.post("/applications/{application_id}/disburse", response_model=LoanApplicationDetailResponse)
async def admin_disburse_application(
    application_id: str,
    payload: DisburseApplicationRequest,
    request: Request,
    db: DbSession,
    staff: CurrentStaff,
    _: Staff = Depends(require_permission(LOAN_DISBURSE)),
):
    ip = get_client_ip(request)
    return await LoanService(db).disburse_application(application_id, staff, payload, ip=ip)


@router.post(
    "/applications/{application_id}/disbursements/manual",
    response_model=LoanApplicationDetailResponse,
    summary="Record a manual disbursement",
    description=(
        "For funds sent outside the integrated payment rail (bank app, branch). "
        "Marks the application disbursed, posts the ledger and books the loan with "
        "its repayment schedule."
    ),
)
async def admin_record_manual_disbursement(
    application_id: str,
    payload: ManualDisbursementRequest,
    request: Request,
    db: DbSession,
    staff: CurrentStaff,
    _: Staff = Depends(require_permission(LOAN_DISBURSE)),
):
    return await LoanService(db).record_manual_disbursement(
        application_id, staff, payload, ip=get_client_ip(request)
    )


# ── Loan book ──


@router.get("/loans", response_model=Page[LoanResponse], summary="Loan book")
async def admin_list_loans(
    db: DbSession,
    status_filter: LoanStatus | None = Query(default=None, alias="status"),
    customer_id: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100, description="Borrower name, phone, account or exact BVN"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Staff = Depends(require_permission(LOAN_READ)),
):
    rows, total = await list_loans(
        db, customer_id=customer_id, status_filter=status_filter, search=search, limit=limit, offset=offset
    )
    return Page[LoanResponse](
        items=await loan_responses(db, rows), total=total, limit=limit, offset=offset
    )


@router.get("/loans/{loan_id}", response_model=LoanDetailResponse, summary="Loan with schedule")
async def admin_get_loan(
    loan_id: str,
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_READ)),
):
    return await loan_detail(db, loan_id)


@router.post(
    "/loans/{loan_id}/repayments",
    response_model=LoanRepaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a repayment received outside the app",
    description="Re-sending the same `reference` returns the original repayment instead of posting twice.",
)
async def admin_record_repayment(
    loan_id: str,
    payload: RecordRepaymentRequest,
    db: DbSession,
    staff: CurrentStaff,
    _: Staff = Depends(require_permission(LOAN_RECORD_REPAYMENT)),
):
    repayment = await LoanServicingService(db).record_repayment(
        loan_id,
        amount=payload.amount,
        channel=payload.channel,
        reference=f"staff_{payload.reference.strip()}",
        paid_at=payload.paid_at,
        staff_id=staff.id,
        note=payload.note,
    )
    return LoanRepaymentResponse.model_validate(repayment)


@router.patch("/applications/{application_id}/status", response_model=LoanApplicationDetailResponse)
async def admin_update_application_status(
    application_id: str,
    payload: ApplicationStatusUpdate,
    request: Request,
    db: DbSession,
    staff: CurrentStaff,
    __: Staff = Depends(require_permission(LOAN_REVIEW)),
):
    return await LoanService(db).update_application_status(
        application_id, payload, staff=staff, ip=get_client_ip(request)
    )


@router.patch(
    "/applications/{application_id}/documents/{document_id}/verify",
    response_model=LoanApplicationDetailResponse,
)
async def admin_verify_document(
    application_id: str,
    document_id: str,
    payload: VerifyDocumentRequest,
    request: Request,
    db: DbSession,
    staff: CurrentStaff,
    __: Staff = Depends(require_permission(LOAN_VERIFY_DOCS)),
):
    ip = get_client_ip(request)
    return await LoanService(db).verify_document(
        application_id, document_id, payload, staff_id=staff.id, staff=staff, ip=ip
    )


@router.get("/applications/{application_id}/documents/{document_id}/download")
async def admin_download_document(
    application_id: str,
    document_id: str,
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_READ)),
):
    path, file_name, mime_type = await LoanService(db).get_document_for_download(
        application_id, document_id
    )
    return FileResponse(path, media_type=mime_type, filename=file_name)


# ── Workflow configuration ──


@router.get("/products/{product_code}/workflows", response_model=list[WorkflowResponse])
async def list_product_workflows(
    product_code: str,
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_CONFIGURE_WORKFLOW)),
):
    return await LoanService(db).list_product_workflows(product_code)


@router.get("/products/{product_code}/workflow/active", response_model=WorkflowResponse | None)
async def get_active_product_workflow(
    product_code: str,
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_READ)),
):
    workflow = await LoanService(db).get_active_product_workflow(product_code)
    return workflow


@router.post("/products/{product_code}/workflows", response_model=WorkflowResponse, status_code=201)
async def create_product_workflow(
    product_code: str,
    payload: CreateWorkflowRequest,
    db: DbSession,
    staff: CurrentStaff,
    _: Staff = Depends(require_permission(LOAN_CONFIGURE_WORKFLOW)),
):
    workflow = await LoanService(db).create_product_workflow(
        product_code, payload.stages, staff_id=staff.id
    )
    return workflow


@router.put("/workflows/{workflow_id}/stages", response_model=WorkflowResponse)
async def update_workflow_stages(
    workflow_id: str,
    payload: UpdateWorkflowStagesRequest,
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_CONFIGURE_WORKFLOW)),
):
    workflow = await LoanService(db).update_workflow_stages(workflow_id, payload.stages)
    return workflow


@router.post("/workflows/{workflow_id}/publish", response_model=WorkflowResponse)
async def publish_workflow(
    workflow_id: str,
    db: DbSession,
    _: Staff = Depends(require_permission(LOAN_CONFIGURE_WORKFLOW)),
):
    workflow = await LoanService(db).publish_workflow(workflow_id)
    return workflow
