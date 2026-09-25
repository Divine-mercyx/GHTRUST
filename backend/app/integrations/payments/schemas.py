from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.retry import TransientError


class PaymentRailError(Exception):
    def __init__(self, message: str, status_code: int = 502, provider_code: str | None = None):
        self.message = message
        self.status_code = status_code
        self.provider_code = provider_code
        super().__init__(message)

    @property
    def outcome_unknown(self) -> bool:
        """True when a state-changing call may have succeeded provider-side."""
        return isinstance(self, TransientError)


class TransientRailError(PaymentRailError, TransientError):
    """Transport failure or provider 5xx — retried, and outcome unknown."""


class ReservedAccountResult(BaseModel):
    account_reference: str
    account_number: str
    account_name: str
    bank_name: str
    bank_code: str | None = None
    currency: str = "NGN"
    reservation_reference: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ResolvedAccount(BaseModel):
    account_number: str
    account_name: str
    bank_code: str


class DisbursementResult(BaseModel):
    reference: str
    status: str
    amount: Decimal
    currency: str = "NGN"
    transaction_id: str | None = None
    narration: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class TransactionVerification(BaseModel):
    model_config = ConfigDict(extra="allow")

    transaction_reference: str
    payment_reference: str | None = None
    amount: Decimal
    currency: str = "NGN"
    status: str
    payment_method: str | None = None
    account_reference: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class WalletBalanceResult(BaseModel):
    available_balance: Decimal
    ledger_balance: Decimal | None = None
    currency: str = "NGN"


class Bank(BaseModel):
    """A destination bank for transfers; `code` is whatever the active rail expects."""

    code: str
    name: str


# Served by every rail in mock mode (CBN codes, as Paystack/Monnify use).
MOCK_BANKS: tuple[Bank, ...] = tuple(
    Bank(code=code, name=name)
    for code, name in (
        ("044", "Access Bank"),
        ("023", "Citibank Nigeria"),
        ("050", "Ecobank Nigeria"),
        ("070", "Fidelity Bank"),
        ("011", "First Bank of Nigeria"),
        ("214", "First City Monument Bank"),
        ("058", "Guaranty Trust Bank"),
        ("030", "Heritage Bank"),
        ("082", "Keystone Bank"),
        ("50211", "Kuda Bank"),
        ("50515", "Moniepoint MFB"),
        ("999992", "OPay"),
        ("999991", "PalmPay"),
        ("076", "Polaris Bank"),
        ("221", "Stanbic IBTC Bank"),
        ("068", "Standard Chartered Bank"),
        ("232", "Sterling Bank"),
        ("032", "Union Bank of Nigeria"),
        ("033", "United Bank for Africa"),
        ("215", "Unity Bank"),
        ("035", "Wema Bank"),
        ("057", "Zenith Bank"),
    )
)
