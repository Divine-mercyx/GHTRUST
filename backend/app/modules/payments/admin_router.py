"""Staff view of payment-rail transactions (funding, withdrawals, disbursements)."""

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.deps import DbSession
from app.models.base import TransactionStatus
from app.modules.admin.deps import require_permission
from app.modules.admin.models import Staff
from app.modules.admin.permissions import PAYMENT_READ
from app.modules.loans.schemas import Page
from app.modules.payments.models import (
    PaymentChannel,
    PaymentDirection,
    PaymentProvider,
    PaymentTransaction,
    WithdrawalRequest,
)
from app.modules.users.models import Customer

router = APIRouter(prefix="/admin/payments", tags=["Admin — Payments"])


class AdminTransactionResponse(BaseModel):
    id: str
    provider: PaymentProvider
    provider_reference: str
    direction: PaymentDirection
    channel: PaymentChannel
    amount: Decimal
    currency: str
    status: TransactionStatus
    customer_id: str | None
    customer_name: str | None
    application_id: str | None
    withdrawal_id: str | None
    # The customer's note on a withdrawal, as sent to the recipient's bank.
    narration: str | None = None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class TransactionSummaryResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    completed_inbound_amount: Decimal
    completed_outbound_amount: Decimal


def _filters(status, direction, customer_id):
    conditions = []
    if status:
        conditions.append(PaymentTransaction.status == status)
    if direction:
        conditions.append(PaymentTransaction.direction == direction)
    if customer_id:
        conditions.append(PaymentTransaction.customer_id == customer_id)
    return conditions


@router.get("/transactions", response_model=Page[AdminTransactionResponse], summary="Payment transactions")
async def list_transactions(
    db: DbSession,
    status: TransactionStatus | None = Query(default=None),
    direction: PaymentDirection | None = Query(default=None),
    customer_id: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Staff = Depends(require_permission(PAYMENT_READ)),
):
    conditions = _filters(status, direction, customer_id)
    total = await db.scalar(select(func.count()).select_from(PaymentTransaction).where(*conditions))
    rows = (
        await db.execute(
            select(PaymentTransaction, Customer.first_name, Customer.last_name, WithdrawalRequest.narration)
            .outerjoin(Customer, Customer.id == PaymentTransaction.customer_id)
            .outerjoin(WithdrawalRequest, WithdrawalRequest.id == PaymentTransaction.withdrawal_id)
            .where(*conditions)
            .order_by(PaymentTransaction.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        AdminTransactionResponse(
            id=tx.id,
            provider=tx.provider,
            provider_reference=tx.provider_reference,
            direction=tx.direction,
            channel=tx.channel,
            amount=tx.amount,
            currency=tx.currency,
            status=tx.status,
            customer_id=tx.customer_id,
            customer_name=" ".join(p for p in (first, last) if p) or None,
            application_id=tx.application_id,
            withdrawal_id=tx.withdrawal_id,
            narration=narration,
            failure_reason=tx.failure_reason,
            created_at=tx.created_at,
            updated_at=tx.updated_at,
        )
        for tx, first, last, narration in rows
    ]
    return Page[AdminTransactionResponse](items=items, total=int(total or 0), limit=limit, offset=offset)


@router.get("/transactions/summary", response_model=TransactionSummaryResponse, summary="Transaction totals")
async def transaction_summary(
    db: DbSession,
    _: Staff = Depends(require_permission(PAYMENT_READ)),
):
    counts = dict(
        (await db.execute(
            select(PaymentTransaction.status, func.count()).group_by(PaymentTransaction.status)
        )).all()
    )
    volumes = dict(
        (await db.execute(
            select(PaymentTransaction.direction, func.coalesce(func.sum(PaymentTransaction.amount), 0))
            .where(PaymentTransaction.status == TransactionStatus.COMPLETED)
            .group_by(PaymentTransaction.direction)
        )).all()
    )
    return TransactionSummaryResponse(
        total=sum(counts.values()),
        by_status={(k.value if hasattr(k, "value") else str(k)): v for k, v in counts.items()},
        completed_inbound_amount=Decimal(str(volumes.get(PaymentDirection.INBOUND, 0))),
        completed_outbound_amount=Decimal(str(volumes.get(PaymentDirection.OUTBOUND, 0))),
    )
