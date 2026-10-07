"""
What the customer is told, and when. Each helper queues one notification in the
caller's transaction; the wording lives here so it stays consistent.

Routes are Expo Router paths in the mobile app; tapping the push opens them.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.loans.constants import DOCUMENT_LABELS
from app.modules.loans.models import Loan, LoanApplication, LoanProduct
from app.modules.loans.schemas import InstallmentStatus, LoanStatus
from app.modules.notifications.service import NotificationService

# Reminder cadence: before the due date, on it, and while overdue.
DUE_SOON_DAYS = 3
OVERDUE_REMINDER_DAYS = (1, 3, 7)  # then every 7 days


def naira(amount: Decimal | float | int) -> str:
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    return f"₦{value:,.2f}" if value % 1 else f"₦{value:,.0f}"


def _day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


async def _product_name(db: AsyncSession, *, code: str | None = None, product_id: str | None = None) -> str:
    query = select(LoanProduct.name)
    query = query.where(LoanProduct.code == code) if code else query.where(LoanProduct.id == product_id)
    name = await db.scalar(query)
    return name or "loan"


# ── Wallet ───────────────────────────────────────────────────────────────────


async def wallet_funded(db: AsyncSession, *, customer_id: str, amount: Decimal, journal_id: str) -> None:
    await NotificationService(db).notify(
        customer_id,
        "wallet_funded",
        "Money received",
        f"{naira(amount)} has been added to your wallet.",
        route=f"/transactions/j_{journal_id}",
        dedupe_key=f"wallet_funded:{journal_id}",
    )


async def withdrawal_completed(db: AsyncSession, withdrawal) -> None:
    bank = withdrawal.bank_name or "bank"
    await NotificationService(db).notify(
        withdrawal.customer_id,
        "withdrawal_completed",
        "Withdrawal sent",
        f"{naira(withdrawal.amount)} has been paid into your {bank} account ending {withdrawal.account_number[-4:]}.",
        route=f"/transactions/w_{withdrawal.id}",
        dedupe_key=f"withdrawal_completed:{withdrawal.id}",
    )


async def withdrawal_failed(db: AsyncSession, withdrawal) -> None:
    await NotificationService(db).notify(
        withdrawal.customer_id,
        "withdrawal_failed",
        "Withdrawal didn't go through",
        f"Your withdrawal of {naira(withdrawal.amount)} couldn't be completed. The money is back in your wallet.",
        route=f"/transactions/w_{withdrawal.id}",
        dedupe_key=f"withdrawal_failed:{withdrawal.id}",
    )


# ── Applications and loans ───────────────────────────────────────────────────


async def offer_sent_to_customer(db: AsyncSession, application: LoanApplication) -> None:
    product = await _product_name(db, product_id=application.product_id)
    await NotificationService(db).notify(
        application.customer_id,
        "offer_sent",
        "Your loan offer is ready",
        f"Your {product} offer is ready. Review the amount and terms in the app and accept or decline.",
        route=f"/applications/{application.id}/offer",
        dedupe_key=f"offer_sent:{application.id}",
    )


async def application_approved(db: AsyncSession, application: LoanApplication) -> None:
    product = await _product_name(db, product_id=application.product_id)
    await NotificationService(db).notify(
        application.customer_id,
        "application_approved",
        "Your loan is approved",
        f"Good news: your {product} application has been approved. Review and accept your offer so we can "
        "pay it out.",
        route=f"/applications/{application.id}/offer",
        dedupe_key=f"application_approved:{application.id}",
    )


async def application_fully_approved(db: AsyncSession, application: LoanApplication) -> None:
    product = await _product_name(db, product_id=application.product_id)
    await NotificationService(db).notify(
        application.customer_id,
        "application_fully_approved",
        "Application approved",
        f"Your {product} application passed final approval. We'll prepare your payout shortly.",
        route=f"/applications/{application.id}",
        dedupe_key=f"application_fully_approved:{application.id}",
    )


async def application_rejected(db: AsyncSession, application: LoanApplication) -> None:
    product = await _product_name(db, product_id=application.product_id)
    await NotificationService(db).notify(
        application.customer_id,
        "application_rejected",
        "Update on your application",
        f"We couldn't approve your {product} application this time. Tap to see the details.",
        route=f"/applications/{application.id}",
        dedupe_key=f"application_rejected:{application.id}",
    )


async def document_rejected(db: AsyncSession, application: LoanApplication, document) -> None:
    label = DOCUMENT_LABELS.get(document.document_type, "A document")
    stamp = (document.verified_at or datetime.now(timezone.utc)).isoformat()
    await NotificationService(db).notify(
        application.customer_id,
        "document_rejected",
        "A document needs attention",
        f"{label} for your loan application needs to be uploaded again. Tap to see why.",
        route=f"/applications/{application.id}",
        dedupe_key=f"document_rejected:{document.id}:{stamp}",
    )


async def loan_disbursed(db: AsyncSession, loan: Loan, *, to_wallet: bool = False) -> None:
    product = await _product_name(db, code=loan.product_type)
    where = "paid into your GH Trust wallet" if to_wallet else "sent to your bank account"
    await NotificationService(db).notify(
        loan.customer_id,
        "loan_disbursed",
        "Your loan has been paid out",
        f"{naira(loan.principal)} from your {product} has been {where}.",
        route=f"/loans/{loan.id}",
        dedupe_key=f"loan_disbursed:{loan.id}",
    )


async def repayment_received(db: AsyncSession, loan: Loan, *, amount: Decimal, repayment_id: str) -> None:
    product = await _product_name(db, code=loan.product_type)
    await NotificationService(db).notify(
        loan.customer_id,
        "repayment_received",
        "Payment received",
        f"{naira(amount)} was applied to your {product}. Thank you.",
        route=f"/loans/{loan.id}",
        dedupe_key=f"repayment_received:{repayment_id}",
    )


# ── Security ─────────────────────────────────────────────────────────────────


async def sign_in_approval_requested(db: AsyncSession, approval) -> None:
    device = approval.device_name or "a new phone"
    await NotificationService(db).notify(
        approval.customer_id,
        "sign_in_request",
        "New sign-in request",
        f"Someone is trying to sign in to your account on {device}. If it's you, open GH Trust to approve it.",
        route=f"/approve-device/{approval.id}",
        dedupe_key=f"sign_in_request:{approval.id}",
    )


# ── Daily repayment reminders ────────────────────────────────────────────────


async def send_repayment_reminders(db: AsyncSession, today: date) -> int:
    """Queue due-soon, due-today and overdue reminders for open loans. Idempotent per day."""
    loans = (
        (
            await db.execute(
                select(Loan)
                .where(Loan.status.in_([LoanStatus.ACTIVE, LoanStatus.OVERDUE]))
                .options(selectinload(Loan.schedule))
            )
        )
        .scalars()
        .all()
    )
    names: dict[str, str] = {}
    queued = 0
    service = NotificationService(db)
    for loan in loans:
        unpaid = sorted(
            (line for line in loan.schedule if line.status != InstallmentStatus.PAID and line.amount_due > 0),
            key=lambda line: line.due_date,
        )
        if not unpaid:
            continue
        if loan.product_type not in names:
            names[loan.product_type] = await _product_name(db, code=loan.product_type)
        product = names[loan.product_type]

        overdue = [line for line in unpaid if line.due_date < today]
        if overdue:
            days_late = (today - overdue[0].due_date).days
            if days_late in OVERDUE_REMINDER_DAYS or (days_late > 7 and days_late % 7 == 0):
                owed = sum((line.amount_due for line in overdue), Decimal("0"))
                created = await service.notify(
                    loan.customer_id,
                    "repayment_overdue",
                    "Repayment overdue",
                    f"{naira(owed)} on your {product} was due on {_day(overdue[0].due_date)}. "
                    "Please pay as soon as you can.",
                    route=f"/loans/{loan.id}",
                    dedupe_key=f"overdue:{loan.id}:{today.isoformat()}",
                )
                queued += created is not None
            continue

        nxt = unpaid[0]
        days_left = (nxt.due_date - today).days
        if days_left == DUE_SOON_DAYS:
            title, when = f"Repayment due in {DUE_SOON_DAYS} days", f"is due on {_day(nxt.due_date)}"
        elif days_left == 0:
            title, when = "Repayment due today", "is due today"
        else:
            continue
        created = await service.notify(
            loan.customer_id,
            "repayment_due",
            title,
            f"{naira(nxt.amount_due)} on your {product} {when}. Add money to your wallet and tap Repay.",
            route=f"/loans/{loan.id}",
            dedupe_key=f"due:{loan.id}:{nxt.due_date.isoformat()}:{days_left}",
        )
        queued += created is not None
    return queued


async def investment_started(db: AsyncSession, investment, plan_name: str) -> None:
    await NotificationService(db).notify(
        investment.customer_id,
        "investment_started",
        "Your investment has started",
        f"{naira(investment.amount)} in {plan_name}. It matures on {investment.maturity_date:%d %b %Y} "
        f"and pays {naira(investment.amount + investment.projected_return)} into your wallet.",
        route="/investments",
        dedupe_key=f"investment_started:{investment.id}",
    )


async def investment_matured(db: AsyncSession, investment, plan_name: str) -> None:
    await NotificationService(db).notify(
        investment.customer_id,
        "investment_matured",
        "Your investment has matured",
        f"{naira(investment.payout_amount)} from {plan_name} has been paid into your wallet.",
        route="/investments",
        dedupe_key=f"investment_matured:{investment.id}",
    )
