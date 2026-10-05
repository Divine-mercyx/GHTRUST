from decimal import Decimal
from typing import Any

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.models import (
    CustomerWallet,
    JournalType,
    LedgerAccountCode,
    LedgerDirection,
    LedgerEntry,
    LedgerJournal,
    PaymentTransaction,
)

logger = structlog.get_logger()


class LedgerError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class LedgerService:
    """Double-entry ledger with wallet balance enforcement."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_wallet(self, customer_id: str) -> CustomerWallet:
        result = await self.db.execute(
            select(CustomerWallet).where(CustomerWallet.customer_id == customer_id)
        )
        wallet = result.scalar_one_or_none()
        if wallet:
            return wallet
        wallet = CustomerWallet(customer_id=customer_id)
        self.db.add(wallet)
        await self.db.flush()
        return wallet

    async def _lock_wallet(self, customer_id: str) -> CustomerWallet:
        wallet = await self.get_or_create_wallet(customer_id)
        result = await self.db.execute(
            select(CustomerWallet)
            .where(CustomerWallet.id == wallet.id)
            .with_for_update()
        )
        locked = result.scalar_one()
        return locked

    @staticmethod
    def _validate_entries(entries: list[tuple[LedgerAccountCode, LedgerDirection, Decimal]]) -> None:
        debits = sum(amount for _, direction, amount in entries if direction == LedgerDirection.DEBIT)
        credits = sum(amount for _, direction, amount in entries if direction == LedgerDirection.CREDIT)
        if debits != credits:
            raise LedgerError(f"Unbalanced journal: debits={debits} credits={credits}", status_code=500)
        if debits <= 0:
            raise LedgerError("Journal amount must be positive", status_code=400)

    async def _get_journal_by_idempotency(self, idempotency_key: str) -> LedgerJournal | None:
        result = await self.db.execute(
            select(LedgerJournal).where(LedgerJournal.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def post_journal(
        self,
        *,
        idempotency_key: str,
        journal_type: JournalType,
        entries: list[tuple[LedgerAccountCode, LedgerDirection, Decimal]],
        customer_id: str | None = None,
        reference: str | None = None,
        description: str | None = None,
        payment_transaction_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[LedgerJournal, bool]:
        existing = await self._get_journal_by_idempotency(idempotency_key)
        if existing:
            return existing, False

        self._validate_entries(entries)
        journal = LedgerJournal(
            idempotency_key=idempotency_key,
            journal_type=journal_type,
            reference=reference,
            description=description,
            customer_id=customer_id,
            payment_transaction_id=payment_transaction_id,
            metadata_json=metadata or {},
        )
        # Savepoint: if a concurrent request posts the same idempotency key
        # between our check and this insert, the unique constraint fires. Roll
        # back only the savepoint and return the winner's journal, instead of
        # failing the whole transaction.
        try:
            async with self.db.begin_nested():
                self.db.add(journal)
                await self.db.flush()
        except IntegrityError:
            winner = await self._get_journal_by_idempotency(idempotency_key)
            if winner is None:
                raise
            logger.info("ledger_journal_race_resolved", idempotency_key=idempotency_key)
            return winner, False

        for account_code, direction, amount in entries:
            self.db.add(
                LedgerEntry(
                    journal_id=journal.id,
                    account_code=account_code,
                    direction=direction,
                    amount=amount,
                    customer_id=customer_id,
                )
            )
        await self.db.flush()
        logger.info(
            "ledger_journal_posted",
            journal_id=journal.id,
            journal_type=journal_type.value,
            idempotency_key=idempotency_key,
        )
        return journal, True

    async def credit_wallet_from_paystack(
        self,
        *,
        customer_id: str,
        amount: Decimal,
        idempotency_key: str,
        reference: str,
        payment_transaction: PaymentTransaction,
        description: str | None = None,
    ) -> LedgerJournal:
        if amount <= 0:
            raise LedgerError("Credit amount must be positive")

        wallet = await self._lock_wallet(customer_id)
        journal, created = await self.post_journal(
            idempotency_key=idempotency_key,
            journal_type=JournalType.WALLET_FUNDING,
            customer_id=customer_id,
            reference=reference,
            description=description or "Wallet funded via Paystack",
            payment_transaction_id=payment_transaction.id,
            entries=[
                (LedgerAccountCode.PAYSTACK_SETTLEMENT, LedgerDirection.DEBIT, amount),
                (LedgerAccountCode.CUSTOMER_WALLET, LedgerDirection.CREDIT, amount),
            ],
            metadata={"provider_reference": reference},
        )
        if created:
            wallet.available_balance += amount
            from app.modules.notifications import events as notify

            await notify.wallet_funded(self.db, customer_id=customer_id, amount=amount, journal_id=journal.id)
        return journal

    async def hold_wallet_for_withdrawal(
        self,
        *,
        customer_id: str,
        amount: Decimal,
        idempotency_key: str,
        reference: str,
    ) -> LedgerJournal:
        if amount <= 0:
            raise LedgerError("Hold amount must be positive")

        wallet = await self._lock_wallet(customer_id)
        if wallet.available_balance < amount:
            raise LedgerError("Insufficient wallet balance", status_code=409)

        journal, created = await self.post_journal(
            idempotency_key=idempotency_key,
            journal_type=JournalType.WALLET_WITHDRAWAL_HOLD,
            customer_id=customer_id,
            reference=reference,
            description="Withdrawal hold",
            entries=[
                (LedgerAccountCode.CUSTOMER_WALLET, LedgerDirection.DEBIT, amount),
                (LedgerAccountCode.CUSTOMER_WALLET_LOCKED, LedgerDirection.CREDIT, amount),
            ],
        )
        if created:
            wallet.available_balance -= amount
            wallet.locked_balance += amount
        return journal

    async def settle_withdrawal_hold(
        self,
        *,
        customer_id: str,
        amount: Decimal,
        idempotency_key: str,
        reference: str,
        payment_transaction_id: str | None = None,
    ) -> LedgerJournal:
        wallet = await self._lock_wallet(customer_id)
        if wallet.locked_balance < amount:
            raise LedgerError("Locked balance insufficient for settlement", status_code=409)

        journal, created = await self.post_journal(
            idempotency_key=idempotency_key,
            journal_type=JournalType.WALLET_WITHDRAWAL,
            customer_id=customer_id,
            reference=reference,
            description="Withdrawal settled via Paystack",
            payment_transaction_id=payment_transaction_id,
            entries=[
                (LedgerAccountCode.CUSTOMER_WALLET_LOCKED, LedgerDirection.DEBIT, amount),
                (LedgerAccountCode.PAYSTACK_SETTLEMENT, LedgerDirection.CREDIT, amount),
            ],
        )
        if created:
            wallet.locked_balance -= amount
        return journal

    async def release_withdrawal_hold(
        self,
        *,
        customer_id: str,
        amount: Decimal,
        idempotency_key: str,
        reference: str,
    ) -> LedgerJournal:
        wallet = await self._lock_wallet(customer_id)
        if wallet.locked_balance < amount:
            raise LedgerError("Locked balance insufficient for release", status_code=409)

        journal, created = await self.post_journal(
            idempotency_key=idempotency_key,
            journal_type=JournalType.WALLET_WITHDRAWAL_RELEASE,
            customer_id=customer_id,
            reference=reference,
            description="Withdrawal hold released",
            entries=[
                (LedgerAccountCode.CUSTOMER_WALLET_LOCKED, LedgerDirection.DEBIT, amount),
                (LedgerAccountCode.CUSTOMER_WALLET, LedgerDirection.CREDIT, amount),
            ],
        )
        if created:
            wallet.locked_balance -= amount
            wallet.available_balance += amount
        return journal

    async def debit_wallet(
        self,
        *,
        customer_id: str,
        amount: Decimal,
        journal_type: JournalType,
        idempotency_key: str,
        reference: str,
        credits: list[tuple[LedgerAccountCode, LedgerDirection, Decimal]],
        description: str | None = None,
    ) -> LedgerJournal:
        """Debit the customer's available wallet balance against the given credits."""
        if amount <= 0:
            raise LedgerError("Debit amount must be positive")

        wallet = await self._lock_wallet(customer_id)
        existing = await self._get_journal_by_idempotency(idempotency_key)
        if existing:
            return existing
        if wallet.available_balance < amount:
            raise LedgerError("Insufficient wallet balance", status_code=409)

        journal, created = await self.post_journal(
            idempotency_key=idempotency_key,
            journal_type=journal_type,
            customer_id=customer_id,
            reference=reference,
            description=description,
            entries=[(LedgerAccountCode.CUSTOMER_WALLET, LedgerDirection.DEBIT, amount), *credits],
        )
        if created:
            wallet.available_balance -= amount
        return journal

    async def refund_settled_withdrawal(
        self,
        *,
        customer_id: str,
        amount: Decimal,
        idempotency_key: str,
        reference: str,
        payment_transaction_id: str | None = None,
    ) -> LedgerJournal:
        """Bank reversed a completed withdrawal: money is back in settlement, credit the wallet."""
        wallet = await self._lock_wallet(customer_id)
        journal, created = await self.post_journal(
            idempotency_key=idempotency_key,
            journal_type=JournalType.WALLET_WITHDRAWAL_RELEASE,
            customer_id=customer_id,
            reference=reference,
            description="Withdrawal reversed by bank; funds returned to wallet",
            payment_transaction_id=payment_transaction_id,
            entries=[
                (LedgerAccountCode.PAYSTACK_SETTLEMENT, LedgerDirection.DEBIT, amount),
                (LedgerAccountCode.CUSTOMER_WALLET, LedgerDirection.CREDIT, amount),
            ],
        )
        if created:
            wallet.available_balance += amount
        return journal

    async def post_loan_disbursement(
        self,
        *,
        customer_id: str,
        amount: Decimal,
        idempotency_key: str,
        reference: str,
        payment_transaction_id: str | None = None,
        to_wallet: bool = False,
    ) -> LedgerJournal:
        """Book the loan receivable against the money paid out: the bank transfer, or with
        ``to_wallet`` the customer's GH Trust wallet (they withdraw it to any bank)."""
        if amount <= 0:
            raise LedgerError("Disbursement amount must be positive")

        wallet = await self._lock_wallet(customer_id) if to_wallet else None
        paid_from = LedgerAccountCode.CUSTOMER_WALLET if to_wallet else LedgerAccountCode.PAYSTACK_SETTLEMENT
        journal, created = await self.post_journal(
            idempotency_key=idempotency_key,
            journal_type=JournalType.LOAN_DISBURSEMENT,
            customer_id=customer_id,
            reference=reference,
            description="Loan paid into wallet" if to_wallet else "Loan disbursed via bank transfer",
            payment_transaction_id=payment_transaction_id,
            entries=[
                (LedgerAccountCode.LOAN_RECEIVABLE, LedgerDirection.DEBIT, amount),
                (paid_from, LedgerDirection.CREDIT, amount),
            ],
            metadata={"reference": reference, "to_wallet": to_wallet},
        )
        if created and wallet is not None:
            wallet.available_balance += amount
        return journal


    async def invest_from_wallet(
        self, *, customer_id: str, amount: Decimal, idempotency_key: str, reference: str
    ) -> LedgerJournal:
        """Move money from the wallet into an investment (held until maturity)."""
        return await self.debit_wallet(
            customer_id=customer_id,
            amount=amount,
            journal_type=JournalType.INVESTMENT_PURCHASE,
            idempotency_key=idempotency_key,
            reference=reference,
            credits=[(LedgerAccountCode.INVESTMENT_PRINCIPAL, LedgerDirection.CREDIT, amount)],
            description="Investment",
        )

    async def pay_out_investment(
        self, *, customer_id: str, principal: Decimal, returns: Decimal, idempotency_key: str, reference: str
    ) -> LedgerJournal:
        """At maturity: the principal and its returns go back into the wallet. Idempotent."""
        wallet = await self._lock_wallet(customer_id)
        total = principal + returns
        entries = [(LedgerAccountCode.INVESTMENT_PRINCIPAL, LedgerDirection.DEBIT, principal)]
        if returns > 0:
            entries.append((LedgerAccountCode.INVESTMENT_RETURN_EXPENSE, LedgerDirection.DEBIT, returns))
        entries.append((LedgerAccountCode.CUSTOMER_WALLET, LedgerDirection.CREDIT, total))
        journal, created = await self.post_journal(
            idempotency_key=idempotency_key,
            journal_type=JournalType.INVESTMENT_PAYOUT,
            customer_id=customer_id,
            reference=reference,
            description="Investment matured",
            entries=entries,
            metadata={"principal": str(principal), "returns": str(returns)},
        )
        if created:
            wallet.available_balance += total
        return journal


def raise_ledger_http(err: LedgerError) -> None:
    raise HTTPException(status_code=err.status_code, detail=err.message) from err
