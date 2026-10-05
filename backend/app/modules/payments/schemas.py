from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PayoutAccountSummary(BaseModel):
    """Where withdrawals go. The account number is masked to its last four digits."""

    bank_code: str
    bank_name: str | None = None
    account_name: str | None = None
    account_number_masked: str


class WalletSummaryResponse(BaseModel):
    available_balance: float
    locked_balance: float
    currency: str
    dva_status: str
    dva_account_number: str | None = None
    dva_bank_name: str | None = None
    paystack_customer_code: str | None = None
    payment_provider: str | None = None
    funding_mode: str | None = None  # permanent_dva | on_demand_dynamic
    payout_account: PayoutAccountSummary | None = None
    # Money can't leave the account before this (after signing in without the old phone).
    withdrawals_blocked_until: datetime | None = None


class WalletFundRequest(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)


class CardFundRequest(BaseModel):
    amount: Decimal = Field(ge=100, le=1_000_000, decimal_places=2)


class CardFundResponse(BaseModel):
    reference: str
    amount: Decimal
    status: Literal["pending", "completed", "failed", "reversed"]
    # Open this page for the customer to pay. None when the top-up was credited at once (demo server).
    checkout_url: str | None = None
    # The checkout page sends the customer here when they finish; close the browser on it.
    return_url: str | None = None


class WalletFundSessionResponse(BaseModel):
    transaction_ref: str
    account_number: str
    account_name: str
    bank_name: str
    amount: float
    currency: str
    expires_in_minutes: int
    message: str = "Transfer to this account within the expiry window"


class UpdatePayoutAccountRequest(BaseModel):
    bank_code: str = Field(min_length=3, max_length=10)
    account_number: str = Field(min_length=10, max_length=10)
    account_name: str | None = Field(default=None, max_length=200)
    bank_name: str | None = Field(None, max_length=100)
    transaction_pin: str = Field(
        ..., min_length=4, max_length=4, pattern=r"^\d+$", description="Customer's 4-digit transaction PIN"
    )

    @field_validator("account_number")
    @classmethod
    def validate_account(cls, value: str) -> str:
        digits = value.strip()
        if not digits.isdigit() or len(digits) != 10:
            raise ValueError("Account number must be 10 digits")
        return digits


class PayoutAccountSavedResponse(BaseModel):
    message: str
    account_name: str | None = None
    account_number: str
    payout_account: PayoutAccountSummary


class WithdrawRequest(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)
    transaction_pin: str = Field(
        ..., min_length=4, max_length=4, pattern=r"^\d+$", description="Customer's 4-digit transaction PIN"
    )

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        if value.as_tuple().exponent < -2:
            raise ValueError("Amount supports at most 2 decimal places")
        return value


class WithdrawalResponse(BaseModel):
    id: str
    amount: float
    status: str
    transfer_reference: str
    message: str = "Withdrawal queued for processing"

    model_config = {"from_attributes": True}


class WalletTransactionResponse(BaseModel):
    """One movement of money in or out of the wallet, as the customer sees it."""

    id: str
    kind: Literal["funding", "loan_payout", "repayment", "withdrawal", "investment", "investment_payout"]
    direction: Literal["in", "out"]
    amount: float
    status: Literal["completed", "pending", "failed"]
    title: str
    # Bank account for withdrawals, loan product code for repayments.
    detail: str | None = None
    reference: str | None = None
    loan_id: str | None = None
    loan_product: str | None = None
    # Customer-facing explanation, e.g. why a withdrawal failed and where the money is.
    note: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class WalletTransactionPage(BaseModel):
    items: list[WalletTransactionResponse]
    # Pass as ``cursor`` to get the next (older) page; null on the last page.
    next_cursor: str | None = None


class WebhookAckResponse(BaseModel):
    received: bool = True
