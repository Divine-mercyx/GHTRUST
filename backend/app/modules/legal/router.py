from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import CurrentCustomer, DbSession, request_meta
from app.core.errors import AppError
from app.modules.auth.models import AuthSession
from app.modules.auth.security_service import SecurityService
from app.modules.auth.session_service import RequestMeta
from app.modules.legal.documents import DOCUMENTS, DRAFT, LOAN_AGREEMENT_SECTIONS
from app.modules.legal.service import LegalService, LoanOffer

router = APIRouter(tags=["Legal"])


class SectionResponse(BaseModel):
    heading: str
    body: str


class DocumentSummary(BaseModel):
    slug: str
    title: str
    version: str
    effective_date: str
    summary: str
    draft: bool


class DocumentResponse(DocumentSummary):
    sections: list[SectionResponse]


class AcceptDocumentsRequest(BaseModel):
    # slug → the version the customer read, e.g. {"terms": "2026-09-30", "privacy": "2026-09-30"}
    documents: dict[str, str] = Field(..., min_length=1, max_length=5)


class LegalPendingResponse(BaseModel):
    legal_pending: list[str]


class OfferInstallment(BaseModel):
    installment: int
    due_date: date
    amount: Decimal


class LoanOfferResponse(BaseModel):
    application_id: str
    product_name: str
    principal: Decimal
    tenure_months: int
    cadence: str
    installments: int
    interest_rate_pct_monthly: Decimal
    interest_method: str
    total_interest: Decimal
    processing_fee_pct: Decimal
    processing_fee: Decimal
    total_repayable: Decimal
    total_cost_of_credit: Decimal
    late_charge_pct_daily: Decimal | None
    first_payment: Decimal
    schedule: list[OfferInstallment] = Field(
        description="Estimated from today; final dates are set from the day the loan is paid out."
    )
    payout_bank: str | None
    payout_account_masked: str | None
    payout_account_name: str | None
    agreement_version: str
    agreement: list[SectionResponse]
    terms_hash: str
    accepted_at: datetime | None
    draft: bool


class AcceptOfferRequest(BaseModel):
    terms_hash: str = Field(..., min_length=64, max_length=64, description="`terms_hash` from the offer shown")
    transaction_pin: str = Field(..., min_length=4, max_length=4, pattern=r"^\d+$")


def _summary(d) -> DocumentSummary:
    return DocumentSummary(
        slug=d.slug, title=d.title, version=d.version, effective_date=d.effective_date, summary=d.summary, draft=DRAFT
    )


def _offer(offer: LoanOffer) -> LoanOfferResponse:
    return LoanOfferResponse(
        **{k: v for k, v in offer.__dict__.items() if k != "schedule"},
        schedule=[OfferInstallment(**line.__dict__) for line in offer.schedule],
        agreement=[SectionResponse(heading=s.heading, body=s.body) for s in LOAN_AGREEMENT_SECTIONS],
        draft=DRAFT,
    )


async def _device_id(db, request: Request) -> str | None:
    session_id = getattr(request.state, "session_id", None)
    if not session_id:
        return None
    return await db.scalar(select(AuthSession.device_id).where(AuthSession.id == session_id))


@router.get("/legal", response_model=list[DocumentSummary], summary="Legal documents and their current versions")
async def list_documents() -> list[DocumentSummary]:
    return [_summary(d) for d in DOCUMENTS.values()]


@router.get("/legal/{slug}", response_model=DocumentResponse, summary="One legal document")
async def get_document(slug: str) -> DocumentResponse:
    d = DOCUMENTS.get(slug)
    if d is None:
        raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Document not found")
    return DocumentResponse(
        **_summary(d).model_dump(), sections=[SectionResponse(heading=s.heading, body=s.body) for s in d.sections]
    )


@router.post("/legal/accept", response_model=LegalPendingResponse, summary="Accept legal documents")
async def accept_documents(
    payload: AcceptDocumentsRequest,
    request: Request,
    customer: CurrentCustomer,
    db: DbSession,
    meta: RequestMeta = Depends(request_meta),
) -> LegalPendingResponse:
    pending = await LegalService(db).accept_documents(
        customer, payload.documents, meta, device_id=await _device_id(db, request)
    )
    return LegalPendingResponse(legal_pending=pending)


@router.get(
    "/loans/me/applications/{application_id}/offer",
    response_model=LoanOfferResponse,
    summary="The loan offer to review before payout",
)
async def get_offer(application_id: str, customer: CurrentCustomer, db: DbSession) -> LoanOfferResponse:
    return _offer(await LegalService(db).offer_for_customer(application_id, customer.id))


@router.post(
    "/loans/me/applications/{application_id}/offer/accept",
    response_model=LoanOfferResponse,
    summary="Accept the loan offer (e-signature with the transaction PIN)",
)
async def accept_offer(
    application_id: str,
    payload: AcceptOfferRequest,
    request: Request,
    customer: CurrentCustomer,
    db: DbSession,
    meta: RequestMeta = Depends(request_meta),
) -> LoanOfferResponse:
    # Signing a loan isn't money leaving the account, so a lost-phone hold doesn't block it.
    await SecurityService(db).authorize_transaction(customer, payload.transaction_pin, check_hold=False)
    offer = await LegalService(db).accept_offer(
        customer, application_id, terms_hash=payload.terms_hash, meta=meta, device_id=await _device_id(db, request)
    )
    return _offer(offer)


@router.post(
    "/loans/me/applications/{application_id}/offer/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Decline the loan offer (returns application to credit review)",
)
async def reject_offer(application_id: str, customer: CurrentCustomer, db: DbSession) -> None:
    await LegalService(db).reject_offer(customer, application_id)
