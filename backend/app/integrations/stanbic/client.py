"""
Stanbic IBTC bank-partner rail client.

Implements the same port as MonnifyClient / PaystackClient / ZestClient so it
drops into ``app.integrations.payments.factory`` unchanged:

    create_reserved_account · get_reserved_account · validate_bank_account
    initiate_disbursement · verify_disbursement · verify_transaction
    get_wallet_balance · verify_webhook_signature
    is_disbursement_success / is_disbursement_failed

Auth supports both shapes Stanbic's gateway may present:
  * OAuth2 client-credentials  — when ``STANBIC_TOKEN_URL`` is set, we POST
    client_id/client_secret and cache the bearer token.
  * IBM API Connect key pair   — otherwise we send X-IBM-Client-Id /
    X-IBM-Client-Secret on every call (the developer portal is an IBM API
    Connect portal, so this is the likely default).

See constants.py: every path/field marked TODO(stanbic-spec) needs confirming
against the sandbox OpenAPI spec before production use.
"""

import hashlib
import hmac
import time
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import structlog
from app.integrations.retry import transient_retry

from app.core.config import settings
from app.integrations.payments.schemas import (
    MOCK_BANKS,
    Bank,
    DisbursementResult,
    PaymentRailError,
    ReservedAccountResult,
    ResolvedAccount,
    TransactionVerification,
    TransientRailError,
    WalletBalanceResult,
)
from app.integrations.stanbic.constants import (
    ACCOUNT_STATUS_ACTIVE,
    PATH_BANKS,
    PATH_CREATE_ACCOUNT,
    PATH_DEACTIVATE_ACCOUNT,
    PATH_GET_ACCOUNT,
    PATH_NAME_ENQUIRY,
    PATH_SETTLEMENT_BALANCE,
    PATH_TOKEN,
    PATH_TRANSACTION_STATUS,
    PATH_TRANSFER,
    PATH_TRANSFER_STATUS,
    PAYMENT_STATUS_PAID,
    TRANSFER_FAILED_STATUSES,
    TRANSFER_STATUS_PENDING,
    TRANSFER_STATUS_SUCCESS,
    TRANSFER_SUCCESS_STATUSES,
)

logger = structlog.get_logger()

MOCK_ACCOUNT_NUMBER = "9920011223"
MOCK_BANK_NAME = "Stanbic IBTC Bank"
MOCK_BANK_CODE = "221"  # NIP institution code for Stanbic IBTC
MOCK_ACCOUNT_HOLDER = "Mock Account Holder"


class StanbicRetryableError(TransientRailError):
    """
    Transient failure (transport error or 5xx) — safe to retry.

    Only this subclass is retried. A 4xx carries the bank's business error
    (bad BVN, limit breach, unknown bank code) and must surface immediately with
    its provider_code intact: retrying it wastes the window and, because
    tenacity raises ``RetryError`` once attempts are exhausted, would hide a
    ``PaymentRailError`` from the ``except PaymentRailError`` handlers in
    WalletService and DisbursementService.
    """


class StanbicClient:
    """Stanbic IBTC bank-partner API client (wallet NUBAN + NIP transfers)."""

    _access_token: str | None = None
    _token_expires_at: float = 0.0

    def __init__(self) -> None:
        self.base_url = settings.stanbic_base_url.rstrip("/")
        self.client_id = settings.stanbic_client_id
        self.client_secret = settings.stanbic_client_secret
        self.token_url = settings.stanbic_token_url.strip()
        self.merchant_id = settings.stanbic_merchant_id
        self.settlement_account_number = settings.stanbic_settlement_account_number

    # ── Mode & auth ─────────────────────────────────────────────────────────

    @property
    def _use_mock(self) -> bool:
        return settings.stanbic_mock or not settings.stanbic_enabled

    @property
    def _uses_oauth(self) -> bool:
        """Token URL configured → OAuth2 client credentials; else IBM key pair."""
        return bool(self.token_url)

    @classmethod
    def clear_token_cache(cls) -> None:
        cls._access_token = None
        cls._token_expires_at = 0.0

    async def _authenticate(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        if self._use_mock:
            StanbicClient._access_token = "mock_stanbic_token"
            StanbicClient._token_expires_at = time.time() + 3600
            return StanbicClient._access_token

        url = self.token_url if self.token_url.startswith("http") else f"{self.base_url}{PATH_TOKEN}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code >= 500:
            raise PaymentRailError("Stanbic authentication unavailable", status_code=502)

        try:
            payload = response.json()
        except ValueError as exc:
            raise PaymentRailError("Invalid Stanbic auth response", status_code=502) from exc

        token = str(payload.get("access_token") or "")
        if not token:
            raise PaymentRailError("Stanbic auth token missing", status_code=502)

        StanbicClient._access_token = token
        StanbicClient._token_expires_at = time.time() + int(payload.get("expires_in") or 3600)
        return token

    async def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._uses_oauth:
            headers["Authorization"] = f"Bearer {await self._authenticate()}"
        else:
            # IBM API Connect gateway key pair.
            headers["X-IBM-Client-Id"] = self.client_id
            headers["X-IBM-Client-Secret"] = self.client_secret
        if self.merchant_id:
            # TODO(stanbic-spec): confirm the merchant/contract header name (req A2).
            headers["X-Merchant-Id"] = self.merchant_id
        return headers

    # ── Transport ───────────────────────────────────────────────────────────

    @staticmethod
    def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
        """
        Normalise the response envelope.

        TODO(stanbic-spec): confirm the success discriminator. We accept an
        explicit ``responseCode``/``status`` of success, else assume the body is
        already the data object.
        """
        code = str(payload.get("responseCode") or payload.get("code") or "").strip()
        if code and code not in {"00", "000", "0", "200", "success", "SUCCESS"}:
            raise PaymentRailError(
                str(payload.get("responseMessage") or payload.get("message") or "Stanbic request failed"),
                status_code=502,
                provider_code=code,
            )
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        return payload

    @transient_retry()
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._use_mock:
            raise PaymentRailError("Mock mode — use explicit mock handlers", status_code=502)

        url = f"{self.base_url}{path}"
        headers = await self._headers()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method, url, headers=headers, params=params, json=json
                )
        except httpx.HTTPError as exc:
            logger.warning("stanbic_api_transport_error", path=path, error=str(exc))
            raise StanbicRetryableError("Stanbic service unreachable", status_code=502) from exc

        if response.status_code == 401:
            self.clear_token_cache()
            raise PaymentRailError("Stanbic authentication rejected", status_code=502)
        if response.status_code >= 500:
            logger.error("stanbic_api_unavailable", status=response.status_code, path=path)
            raise StanbicRetryableError("Stanbic service unavailable", status_code=502)

        try:
            payload = response.json()
        except ValueError as exc:
            raise PaymentRailError("Invalid Stanbic response payload", status_code=502) from exc

        if response.status_code >= 400:
            logger.error(
                "stanbic_api_error",
                status=response.status_code,
                path=path,
                body=str(payload)[:300],
            )
            raise PaymentRailError(
                str(payload.get("responseMessage") or payload.get("message") or "Stanbic request failed"),
                status_code=502,
                provider_code=str(payload.get("responseCode") or response.status_code),
            )

        return self._unwrap(payload)

    @staticmethod
    def _decimal_amount(value: Any) -> Decimal:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))

    # ── B1: create customer wallet NUBAN ────────────────────────────────────

    async def create_reserved_account(
        self,
        *,
        account_reference: str,
        account_name: str,
        customer_email: str,
        customer_name: str,
        bvn: str | None = None,
        currency: str = "NGN",
        phone: str | None = None,
    ) -> ReservedAccountResult:
        """
        Provision a permanent NUBAN for a customer (requirement B1).

        Called from WalletService.provision_payment_rail right after the
        customer's registration OTP is verified.
        """
        if self._use_mock:
            return ReservedAccountResult(
                account_reference=account_reference,
                account_number=MOCK_ACCOUNT_NUMBER,
                account_name=account_name,
                bank_name=MOCK_BANK_NAME,
                bank_code=MOCK_BANK_CODE,
                currency=currency,
                reservation_reference=f"STB_{uuid4().hex[:12]}",
                raw={"mock": True, "status": ACCOUNT_STATUS_ACTIVE},
            )

        # TODO(stanbic-spec): confirm field names against sandbox spec (req B1).
        payload: dict[str, Any] = {
            "accountReference": account_reference,
            "accountName": account_name,
            "customerName": customer_name,
            "customerEmail": customer_email,
            "currency": currency,
        }
        if phone:
            payload["customerPhone"] = phone
        if bvn:
            # Req H1 — CBN may require BVN-linked dedicated accounts.
            payload["bvn"] = bvn
        if self.merchant_id:
            payload["merchantId"] = self.merchant_id

        body = await self._request("POST", PATH_CREATE_ACCOUNT, json=payload)

        account_number = str(body.get("accountNumber") or body.get("nuban") or "")
        if not account_number:
            raise PaymentRailError(
                "Stanbic account creation response missing account number", status_code=502
            )

        return ReservedAccountResult(
            account_reference=str(body.get("accountReference") or account_reference),
            account_number=account_number,
            account_name=str(body.get("accountName") or account_name),
            bank_name=str(body.get("bankName") or MOCK_BANK_NAME),
            bank_code=str(body.get("bankCode") or MOCK_BANK_CODE) or None,
            currency=str(body.get("currency") or currency),
            reservation_reference=str(body.get("id") or body.get("reference") or "") or None,
            raw=body,
        )

    # ── B2: fetch wallet NUBAN ──────────────────────────────────────────────

    async def get_reserved_account(self, account_reference: str) -> ReservedAccountResult:
        if self._use_mock:
            return ReservedAccountResult(
                account_reference=account_reference,
                account_number=MOCK_ACCOUNT_NUMBER,
                account_name=MOCK_ACCOUNT_HOLDER,
                bank_name=MOCK_BANK_NAME,
                bank_code=MOCK_BANK_CODE,
                raw={"mock": True},
            )

        body = await self._request(
            "GET", PATH_GET_ACCOUNT.format(reference=account_reference)
        )
        return ReservedAccountResult(
            account_reference=str(body.get("accountReference") or account_reference),
            account_number=str(body.get("accountNumber") or body.get("nuban") or ""),
            account_name=str(body.get("accountName") or ""),
            bank_name=str(body.get("bankName") or MOCK_BANK_NAME),
            bank_code=str(body.get("bankCode") or MOCK_BANK_CODE) or None,
            raw=body,
        )

    # ── B4: deactivate wallet NUBAN ─────────────────────────────────────────

    async def deactivate_reserved_account(self, account_reference: str) -> bool:
        """Suspend a customer NUBAN (fraud / KYC failure / closure) — req B4."""
        if self._use_mock:
            return True
        await self._request(
            "POST", PATH_DEACTIVATE_ACCOUNT.format(reference=account_reference)
        )
        return True

    # ── D1: NIP name enquiry ────────────────────────────────────────────────

    # ── D2: bank picker ─────────────────────────────────────────────────────

    async def supported_banks(self) -> list[Bank]:
        if self._use_mock:
            return list(MOCK_BANKS)
        body = await self._request("GET", PATH_BANKS)
        items = body.get("banks", body) if isinstance(body, dict) else body
        banks = []
        for b in items or []:
            code = b.get("nipCode") or b.get("bankCode") or b.get("code")
            name = b.get("bankName") or b.get("name")
            if code and name:
                banks.append(Bank(code=str(code), name=str(name)))
        return banks

    async def validate_bank_account(self, account_number: str, bank_code: str) -> ResolvedAccount:
        if self._use_mock:
            return ResolvedAccount(
                account_number=account_number,
                account_name=MOCK_ACCOUNT_HOLDER,
                bank_code=bank_code,
            )

        body = await self._request(
            "POST",
            PATH_NAME_ENQUIRY,
            json={"accountNumber": account_number, "bankCode": bank_code},
        )
        account_name = str(body.get("accountName") or "")
        if not account_name:
            raise PaymentRailError("Stanbic name enquiry returned no account name", status_code=502)
        return ResolvedAccount(
            account_number=str(body.get("accountNumber") or account_number),
            account_name=account_name,
            bank_code=str(body.get("bankCode") or bank_code),
        )

    # ── D3: outbound transfer (withdrawal + loan disbursement) ──────────────

    async def initiate_disbursement(
        self,
        *,
        amount: Decimal,
        reference: str,
        bank_code: str,
        account_number: str,
        account_name: str,
        narration: str,
        currency: str = "NGN",
    ) -> DisbursementResult:
        if self._use_mock:
            return DisbursementResult(
                reference=reference,
                status=TRANSFER_STATUS_PENDING,
                amount=amount,
                currency=currency,
                transaction_id=f"STBTX_{uuid4().hex[:12]}",
                narration=narration,
                raw={"mock": True},
            )

        # TODO(stanbic-spec): confirm amount units. Requirements doc specifies
        # NGN to 2 decimal places (not kobo) — verify before go-live.
        payload: dict[str, Any] = {
            "reference": reference,
            "amount": str(amount),
            "currency": currency,
            "bankCode": bank_code,
            "accountNumber": account_number,
            "accountName": account_name,
            "narration": narration,
        }
        if self.settlement_account_number:
            payload["sourceAccountNumber"] = self.settlement_account_number
        if self.merchant_id:
            payload["merchantId"] = self.merchant_id

        body = await self._request("POST", PATH_TRANSFER, json=payload)
        return DisbursementResult(
            reference=str(body.get("reference") or reference),
            status=str(body.get("status") or TRANSFER_STATUS_PENDING).upper(),
            amount=self._decimal_amount(body.get("amount") or amount),
            currency=str(body.get("currency") or currency),
            transaction_id=str(body.get("transactionId") or body.get("sessionId") or "") or None,
            narration=str(body.get("narration") or narration) or None,
            raw=body,
        )

    # ── D4: outbound transfer status ────────────────────────────────────────

    async def verify_disbursement(self, reference: str) -> DisbursementResult:
        if self._use_mock:
            return DisbursementResult(
                reference=reference,
                status=TRANSFER_STATUS_SUCCESS,
                amount=Decimal("0"),
                raw={"mock": True},
            )

        body = await self._request(
            "GET", PATH_TRANSFER_STATUS.format(reference=reference)
        )
        return DisbursementResult(
            reference=str(body.get("reference") or reference),
            status=str(body.get("status") or "").upper(),
            amount=self._decimal_amount(body.get("amount")),
            currency=str(body.get("currency") or "NGN"),
            transaction_id=str(body.get("transactionId") or body.get("sessionId") or "") or None,
            narration=str(body.get("narration") or "") or None,
            raw=body,
        )

    # ── C2: inbound collection status ───────────────────────────────────────

    async def verify_transaction(self, transaction_reference: str) -> TransactionVerification:
        if self._use_mock:
            return TransactionVerification(
                transaction_reference=transaction_reference,
                amount=Decimal("0"),
                status=PAYMENT_STATUS_PAID,
                raw={"mock": True},
            )

        body = await self._request(
            "GET", PATH_TRANSACTION_STATUS.format(reference=transaction_reference)
        )
        return TransactionVerification(
            transaction_reference=str(
                body.get("transactionReference") or transaction_reference
            ),
            payment_reference=str(body.get("paymentReference") or "") or None,
            amount=self._decimal_amount(body.get("amount") or body.get("amountPaid")),
            currency=str(body.get("currency") or "NGN"),
            status=str(body.get("paymentStatus") or body.get("status") or "").upper(),
            payment_method=str(body.get("channel") or "") or None,
            account_reference=str(body.get("accountReference") or "") or None,
            raw=body,
        )

    # ── E1: settlement wallet balance ───────────────────────────────────────

    async def get_wallet_balance(self) -> WalletBalanceResult:
        if self._use_mock:
            return WalletBalanceResult(
                available_balance=Decimal("1000000"),
                ledger_balance=Decimal("1000000"),
            )

        if not self.settlement_account_number:
            raise PaymentRailError(
                "Stanbic settlement account number not configured", status_code=503
            )

        body = await self._request(
            "GET",
            PATH_SETTLEMENT_BALANCE,
            params={"accountNumber": self.settlement_account_number},
        )
        return WalletBalanceResult(
            available_balance=self._decimal_amount(body.get("availableBalance")),
            ledger_balance=self._decimal_amount(body.get("ledgerBalance")),
            currency=str(body.get("currency") or "NGN"),
        )

    # ── Webhook verification (req section 4) ────────────────────────────────

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
        """
        Verify the HMAC signature over the raw webhook body.

        TODO(stanbic-spec): confirm digest algorithm. Defaults to SHA-512 and
        falls back to SHA-256 so either bank choice passes once the header name
        is right. Narrow this to the single confirmed algorithm before go-live.
        """
        if not signature or not settings.stanbic_webhook_secret:
            return False
        secret = settings.stanbic_webhook_secret.encode("utf-8")
        for algorithm in (hashlib.sha512, hashlib.sha256):
            expected = hmac.new(secret, raw_body, algorithm).hexdigest()
            if hmac.compare_digest(expected, signature.strip().lower()):
                return True
        return False

    # ── Status helpers (mirror MonnifyClient) ───────────────────────────────

    @staticmethod
    def is_disbursement_success(status: str) -> bool:
        return (status or "").upper() in TRANSFER_SUCCESS_STATUSES

    @staticmethod
    def is_disbursement_failed(status: str) -> bool:
        return (status or "").upper() in TRANSFER_FAILED_STATUSES

    @staticmethod
    def is_payment_success(status: str) -> bool:
        return (status or "").upper() == PAYMENT_STATUS_PAID
