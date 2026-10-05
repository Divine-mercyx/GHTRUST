"""
The customer's wallet history: money in (funding) and out (loan repayments from
the wallet, withdrawals to the bank), newest first.

Funding and wallet repayments come from the ledger, the source of truth for the
balance. Withdrawals come from their requests rather than from the ledger's
hold / settle / release journals, so each shows as one row whose status follows
the transfer (pending, then completed or failed with the money back).

Pages use a keyset cursor on (created_at, id) across both sources, so a new transaction arriving
while the customer scrolls never shifts or repeats rows.
"""

import base64
from datetime import datetime, timezone

from sqlalchemy import and_, exists, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.loans.models import Loan, LoanRepayment
from app.modules.payments.models import (
    JournalType,
    LedgerAccountCode,
    LedgerEntry,
    LedgerJournal,
    LoanDisbursement,
    WithdrawalRequest,
    WithdrawalStatus,
)
from app.modules.payments.wallet_service import mask_account_number

MAX_PAGE = 50
_JOURNAL = "j_"
_WITHDRAWAL = "w_"

_WITHDRAWAL_STATUS = {
    WithdrawalStatus.PENDING: "pending",
    WithdrawalStatus.PROCESSING: "pending",
    WithdrawalStatus.COMPLETED: "completed",
    WithdrawalStatus.FAILED: "failed",
    WithdrawalStatus.CANCELLED: "failed",
}


class InvalidCursor(ValueError):
    pass


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def encode_cursor(row_id: str) -> str:
    return base64.urlsafe_b64encode(row_id.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> str:
    try:
        row_id = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursor("Invalid cursor") from exc
    if not row_id.startswith((_JOURNAL, _WITHDRAWAL)):
        raise InvalidCursor("Invalid cursor")
    return row_id


def _older_than(model, customer_id: str, cursor: str | None):
    """Rows after the cursor row in (created_at, id) descending order.

    The cursor names the last row shown; its timestamp is read back from the
    database, so the comparison is always stored value against stored value
    (SQLite keeps whole seconds, Postgres microseconds).
    """
    if cursor is None:
        return true()
    source = LedgerJournal if cursor.startswith(_JOURNAL) else WithdrawalRequest
    row_id = cursor[2:]
    stamp = (
        select(source.created_at)
        .where(source.id == row_id, source.customer_id == customer_id)
        .scalar_subquery()
    )
    return or_(model.created_at < stamp, and_(model.created_at == stamp, model.id < row_id))


_MONEY_IN = (JournalType.WALLET_FUNDING, JournalType.LOAN_DISBURSEMENT, JournalType.INVESTMENT_PAYOUT)
_MONEY_OUT = (JournalType.LOAN_REPAYMENT, JournalType.INVESTMENT_PURCHASE)
_KIND = {
    JournalType.WALLET_FUNDING: "funding",
    JournalType.LOAN_DISBURSEMENT: "loan_payout",
    JournalType.LOAN_REPAYMENT: "repayment",
    JournalType.INVESTMENT_PURCHASE: "investment",
    JournalType.INVESTMENT_PAYOUT: "investment_payout",
}
_TITLE = {
    "funding": "Money added",
    "loan_payout": "Loan paid out",
    "repayment": "Loan repayment",
    "investment": "Investment",
    "investment_payout": "Investment paid out",
}


class WalletTransactionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _journals(self, customer_id: str):
        touches_wallet = exists().where(
            LedgerEntry.journal_id == LedgerJournal.id,
            LedgerEntry.account_code == LedgerAccountCode.CUSTOMER_WALLET,
        )
        return (
            select(LedgerJournal)
            .where(
                LedgerJournal.customer_id == customer_id,
                LedgerJournal.journal_type.in_(
                    [
                        JournalType.WALLET_FUNDING,
                        JournalType.LOAN_REPAYMENT,
                        JournalType.LOAN_DISBURSEMENT,
                        JournalType.INVESTMENT_PURCHASE,
                        JournalType.INVESTMENT_PAYOUT,
                    ]
                ),
                touches_wallet,
            )
            .options(selectinload(LedgerJournal.entries))
        )

    async def page(
        self,
        customer_id: str,
        *,
        direction: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[dict], str | None]:
        limit = max(1, min(limit, MAX_PAGE))
        after = decode_cursor(cursor) if cursor else None

        withdrawals: list[WithdrawalRequest] = []
        query = self._journals(customer_id).where(_older_than(LedgerJournal, customer_id, after))
        if direction == "in":
            query = query.where(LedgerJournal.journal_type.in_(_MONEY_IN))
        elif direction == "out":
            query = query.where(LedgerJournal.journal_type.in_(_MONEY_OUT))
        journals = list(
            (
                await self.db.execute(
                    query.order_by(LedgerJournal.created_at.desc(), LedgerJournal.id.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        if direction != "in":
            withdrawals = list(
                (
                    await self.db.execute(
                        select(WithdrawalRequest)
                        .where(WithdrawalRequest.customer_id == customer_id, _older_than(WithdrawalRequest, customer_id, after))
                        .order_by(WithdrawalRequest.created_at.desc(), WithdrawalRequest.id.desc())
                        .limit(limit + 1)
                    )
                ).scalars()
            )

        rows: list[tuple[datetime, str, object]] = [(_utc(j.created_at), j.id, j) for j in journals]
        rows += [(_utc(w.created_at), w.id, w) for w in withdrawals]
        # Same order as the queries: newest first, id breaking ties.
        rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
        page, more = rows[:limit], len(rows) > limit

        journal_rows = [r[2] for r in page if isinstance(r[2], LedgerJournal)]
        repayments = {**await self._repayments(journal_rows), **await self._payouts(journal_rows)}
        items = [
            self._from_journal(r[2], repayments.get(r[2].id))
            if isinstance(r[2], LedgerJournal)
            else self._from_withdrawal(r[2])
            for r in page
        ]
        next_cursor = encode_cursor(items[-1]["id"]) if more and items else None
        return items, next_cursor

    async def get(self, customer_id: str, transaction_id: str) -> dict | None:
        if transaction_id.startswith(_JOURNAL):
            journal = (
                await self.db.execute(
                    self._journals(customer_id).where(LedgerJournal.id == transaction_id[len(_JOURNAL) :])
                )
            ).scalar_one_or_none()
            if journal is None:
                return None
            loans = {**await self._repayments([journal]), **await self._payouts([journal])}
            return self._from_journal(journal, loans.get(journal.id))
        if transaction_id.startswith(_WITHDRAWAL):
            withdrawal = (
                await self.db.execute(
                    select(WithdrawalRequest).where(
                        WithdrawalRequest.customer_id == customer_id,
                        WithdrawalRequest.id == transaction_id[len(_WITHDRAWAL) :],
                    )
                )
            ).scalar_one_or_none()
            return self._from_withdrawal(withdrawal) if withdrawal else None
        return None

    async def _repayments(self, journals: list[LedgerJournal]) -> dict[str, tuple[str, str]]:
        """journal id → (loan id, loan product code) for repayment journals."""
        ids = [j.id for j in journals if j.journal_type == JournalType.LOAN_REPAYMENT]
        if not ids:
            return {}
        result = await self.db.execute(
            select(LoanRepayment.journal_id, Loan.id, Loan.product_type)
            .join(Loan, Loan.id == LoanRepayment.loan_id)
            .where(LoanRepayment.journal_id.in_(ids))
        )
        return {journal_id: (loan_id, product) for journal_id, loan_id, product in result.all()}

    async def _payouts(self, journals: list[LedgerJournal]) -> dict[str, tuple[str, str]]:
        """journal id → (loan id, loan product code) for loans paid into the wallet."""
        refs = {j.reference: j.id for j in journals if j.journal_type == JournalType.LOAN_DISBURSEMENT and j.reference}
        if not refs:
            return {}
        result = await self.db.execute(
            select(LoanDisbursement.transfer_reference, Loan.id, Loan.product_type)
            .join(Loan, Loan.application_id == LoanDisbursement.application_id)
            .where(LoanDisbursement.transfer_reference.in_(list(refs)))
        )
        return {refs[ref]: (loan_id, product) for ref, loan_id, product in result.all()}

    @staticmethod
    def _wallet_amount(journal: LedgerJournal) -> float:
        return float(
            sum(e.amount for e in journal.entries if e.account_code == LedgerAccountCode.CUSTOMER_WALLET)
        )

    def _from_journal(self, journal: LedgerJournal, loan: tuple[str, str] | None) -> dict:
        kind = _KIND[journal.journal_type]
        funding = kind == "funding"
        return {
            "id": f"{_JOURNAL}{journal.id}",
            "kind": kind,
            "direction": "in" if journal.journal_type in _MONEY_IN else "out",
            "amount": self._wallet_amount(journal),
            "status": "completed",
            "title": _TITLE[kind],
            "detail": ("Debit card" if journal.description == "Wallet funded by card" else "Bank transfer") if funding else None,
            "reference": journal.reference,
            "loan_id": loan[0] if loan else None,
            "loan_product": loan[1] if loan else None,
            "note": None,
            "created_at": _utc(journal.created_at),
            "completed_at": _utc(journal.created_at),
        }

    @staticmethod
    def _from_withdrawal(w: WithdrawalRequest) -> dict:
        status = _WITHDRAWAL_STATUS.get(w.status, "pending")
        account = mask_account_number(w.account_number)
        note = None
        if status == "failed":
            note = "This withdrawal didn't go through. The money is back in your wallet."
        elif status == "pending":
            note = "Most transfers arrive within minutes. We'll update this when the bank confirms."
        return {
            "id": f"{_WITHDRAWAL}{w.id}",
            "kind": "withdrawal",
            "direction": "out",
            "amount": float(w.amount),
            "status": status,
            "title": "Withdrawal",
            "detail": f"{w.bank_name} · {account}" if w.bank_name else account,
            "reference": w.transfer_reference,
            "loan_id": None,
            "loan_product": None,
            "note": note,
            "created_at": _utc(w.created_at),
            "completed_at": _utc(w.processed_at) if w.processed_at else None,
        }
