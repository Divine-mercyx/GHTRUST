import hashlib
import hmac
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import structlog
from app.integrations.retry import transient_retry

from app.core.config import settings
from app.integrations.payments.schemas import (
    Bank,
    DisbursementResult,
    PaymentRailError,
    ReservedAccountResult,
    ResolvedAccount,
    TransactionVerification,
    TransientRailError,
    WalletBalanceResult,
)
from app.integrations.zest.constants import (
    DEFAULT_VA_EXPIRY_MINUTES,
    PATH_TRANSACTION_INIT,
    PATH_VIRTUAL_ACCOUNT,
    VAS_DYNAMIC,
    VAS_TRANSFER_STATUS,
    WEBENGINE_RESPONSE_COMPLETED,
)
from app.integrations.zest.crypto import default_encryption_key_from_secret, encrypt_auth_data

logger = structlog.get_logger()

MOCK_RESERVED_ACCOUNT = "0000052823"
MOCK_BANK_NAME = "Zest Sandbox Bank"


class ZestClient:
    """
    Zest Payments client (Dynamic Virtual Account API — merchant Notion docs).

    Base URL: https://api.dev.gateway.zestpayment.com/payment-engine
    Auth header: Api-Public-Key (PK_...)

    Virtual account calls wrap inner JSON in AES-encrypted ``authData``.
    Dynamic VAs expire ~5 minutes — not permanent wallet accounts.
    """

    def __init__(self) -> None:
        self.base_url = settings.zest_base_url.rstrip("/")
        self.public_key = settings.zest_public_key
        self.secret_key = settings.zest_secret_key

    @property
    def _use_mock(self) -> bool:
        return settings.zest_mock or not settings.zest_enabled

    def _encryption_key(self) -> str:
        if settings.zest_auth_encryption_key:
            return settings.zest_auth_encryption_key
        if self.secret_key:
            return default_encryption_key_from_secret(self.secret_key)
        raise PaymentRailError("Zest encryption key not configured", status_code=503)

    def _encryption_iv(self) -> str:
        iv = settings.zest_auth_encryption_iv.strip()
        if not iv:
            raise PaymentRailError(
                "ZEST_AUTH_ENCRYPTION_IV is required (16-char IV from Zest dashboard / Notion doc)",
                status_code=503,
            )
        return iv

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Api-Public-Key": self.public_key,
        }

    def _encrypt_vas_payload(self, inner: dict[str, Any]) -> dict[str, str]:
        encrypted = encrypt_auth_data(
            inner,
            key=self._encryption_key(),
            iv=self._encryption_iv(),
        )
        return {"authData": encrypted}

    @staticmethod
    def _pick(data: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        return None

    @classmethod
    def _find_nested(cls, payload: Any, *keys: str) -> Any:
        if isinstance(payload, dict):
            value = cls._pick(payload, *keys)
            if value is not None:
                return value
            for nested in payload.values():
                found = cls._find_nested(nested, *keys)
                if found is not None:
                    return found
        elif isinstance(payload, list):
            for item in payload:
                found = cls._find_nested(item, *keys)
                if found is not None:
                    return found
        return None

    @classmethod
    def _parse_virtual_account_response(
        cls,
        body: dict[str, Any],
        *,
        transaction_ref: str,
        account_name: str,
    ) -> ReservedAccountResult:
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        account_number = str(cls._find_nested(data, "accountNumber", "account_number") or "")
        if not account_number:
            raise PaymentRailError(
                str(cls._pick(body, "message") or "Zest virtual account response missing account number"),
                status_code=502,
                provider_code=str(cls._find_nested(data, "responseCode") or ""),
            )

        web_engine_code = str(cls._find_nested(data, "webEngineResponseCodes") or "")
        if web_engine_code and web_engine_code != WEBENGINE_RESPONSE_COMPLETED:
            raise PaymentRailError(
                str(cls._find_nested(data, "responseDescription", "narration") or "Virtual account not completed"),
                status_code=502,
                provider_code=web_engine_code,
            )

        return ReservedAccountResult(
            account_reference=transaction_ref,
            account_number=account_number,
            account_name=str(cls._find_nested(data, "accountName", "account_name") or account_name),
            bank_name=str(cls._find_nested(data, "bankName", "bank_name") or MOCK_BANK_NAME),
            bank_code=str(cls._find_nested(data, "bankCode", "bank_code") or "") or None,
            reservation_reference=transaction_ref,
            raw=body,
        )

    @staticmethod
    def _ensure_success(body: dict[str, Any]) -> None:
        if body.get("success") is False:
            raise PaymentRailError(
                str(body.get("message") or "Zest request failed"),
                status_code=502,
                provider_code=str(body.get("statusCode") or ""),
            )
        errors = body.get("errors") or []
        if errors:
            raise PaymentRailError(str(errors[0]), status_code=502)

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
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json,
                )
        except httpx.HTTPError as exc:
            logger.warning("zest_transport_error", method=method, path=path, error=str(exc))
            raise TransientRailError("Zest unreachable. Please try again.", status_code=502) from exc

        if response.status_code >= 500:
            logger.error(
                "zest_api_error",
                method=method,
                path=path,
                status=response.status_code,
                body=response.text[:300],
            )
            raise TransientRailError("Zest service unavailable. Please try again.", status_code=502)

        try:
            payload = response.json()
        except ValueError as exc:
            raise PaymentRailError("Invalid Zest response", status_code=502) from exc

        if response.status_code >= 400:
            message = str(self._pick(payload, "message", "responseMessage", "error") or "Zest request failed")
            raise PaymentRailError(message, status_code=response.status_code)

        if isinstance(payload, dict):
            self._ensure_success(payload)
        return payload if isinstance(payload, dict) else {"data": payload}

    async def _virtual_account_request(self, inner_payload: dict[str, Any]) -> dict[str, Any]:
        body = self._encrypt_vas_payload(inner_payload)
        return await self._request("POST", PATH_VIRTUAL_ACCOUNT, json=body)

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
        if not signature or not settings.zest_secret_key:
            return False
        expected = hmac.new(
            settings.zest_secret_key.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected.lower(), signature.lower())

    @staticmethod
    def generate_transaction_ref(prefix: str = "GHTRUST") -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{prefix}{stamp}{uuid4().hex[:6].upper()}"

    @classmethod
    def _extract_transaction_ref(cls, payload: dict[str, Any]) -> str | None:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        ref = cls._find_nested(data, "transactionRef", "transaction_ref", "TransactionRef", "reference")
        return str(ref) if ref else None

    async def initialize_transaction(
        self,
        *,
        amount: Decimal,
        currency: str,
        email: str,
    ) -> dict[str, Any]:
        if self._use_mock:
            ref = self.generate_transaction_ref()
            return {"mock": True, "transactionRef": ref, "amount": str(amount), "currency": currency, "email": email}

        return await self._request(
            "POST",
            PATH_TRANSACTION_INIT,
            json={
                "email": email,
                "amount": str(int(amount)) if amount == amount.to_integral_value() else str(amount),
                "currency": currency,
            },
        )

    async def create_dynamic_virtual_account(
        self,
        *,
        transaction_ref: str,
    ) -> ReservedAccountResult:
        """Generate temporary VA (expires ~5 min per Zest docs)."""
        if self._use_mock:
            return ReservedAccountResult(
                account_reference=transaction_ref,
                account_number=MOCK_RESERVED_ACCOUNT,
                account_name="GH Trust Customer",
                bank_name=MOCK_BANK_NAME,
                raw={"mock": True, "expires_in_minutes": settings.zest_va_expiry_minutes},
            )

        body = await self._virtual_account_request(
            {
                "vasRequestType": settings.zest_dynamic_vas_request_type or VAS_DYNAMIC,
                "transactionRef": transaction_ref,
            }
        )
        return self._parse_virtual_account_response(
            body,
            transaction_ref=transaction_ref,
            account_name="GH Trust Customer",
        )

    async def create_wallet_funding_session(
        self,
        *,
        amount: Decimal,
        email: str,
        currency: str = "NGN",
        transaction_ref: str | None = None,
    ) -> dict[str, Any]:
        """
        Full fund-wallet flow: initiate transaction → generate dynamic VA.

        Returns account details + expiry hint for the customer UI.
        """
        ref = transaction_ref or self.generate_transaction_ref()
        init_body = await self.initialize_transaction(amount=amount, currency=currency, email=email)
        ref = self._extract_transaction_ref(init_body) or ref
        account = await self.create_dynamic_virtual_account(transaction_ref=ref)
        return {
            "transaction_ref": ref,
            "account_number": account.account_number,
            "account_name": account.account_name,
            "bank_name": account.bank_name,
            "amount": float(amount),
            "currency": currency,
            "expires_in_minutes": settings.zest_va_expiry_minutes or DEFAULT_VA_EXPIRY_MINUTES,
            "raw": account.raw,
        }

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
        Zest Notion docs only cover *dynamic* VAs (short-lived).

        Permanent per-customer accounts are not supported by this API surface.
        Use ``create_wallet_funding_session`` when the customer wants to fund.
        """
        raise PaymentRailError(
            "Zest dynamic VA API does not support permanent wallet accounts. "
            "Use POST /wallet/fund to generate a session-scoped account.",
            status_code=501,
        )

    async def get_transfer_payment_status(self, transaction_ref: str) -> dict[str, Any]:
        if self._use_mock:
            return {"mock": True, "success": True, "data": {"responseCode": "00"}}

        return await self._virtual_account_request(
            {
                "vasRequestType": settings.zest_transfer_status_vas_request_type or VAS_TRANSFER_STATUS,
                "transactionRef": transaction_ref,
            }
        )

    async def verify_transaction(self, transaction_reference: str) -> TransactionVerification:
        if self._use_mock:
            return TransactionVerification(
                transaction_reference=transaction_reference,
                amount=Decimal("0"),
                status="00",
                raw={"mock": True},
            )

        body = await self.get_transfer_payment_status(transaction_reference)
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        amount_raw = self._find_nested(data, "amount", "AmountPaid", "amountPaid") or 0
        status = str(self._find_nested(data, "responseCode", "status", "paymentStatus") or "")
        return TransactionVerification(
            transaction_reference=transaction_reference,
            payment_reference=str(self._find_nested(data, "paymentReference", "TrackingRef") or "") or None,
            amount=Decimal(str(amount_raw)),
            currency=str(self._find_nested(data, "currency") or "NGN"),
            status=status,
            account_reference=transaction_reference,
            raw=body,
        )

    async def supported_banks(self) -> list[Bank]:
        raise PaymentRailError("Zest bank list is not available on the VA API", status_code=501)

    async def validate_bank_account(self, account_number: str, bank_code: str) -> ResolvedAccount:
        raise PaymentRailError("Zest bank account validation is not available on the VA API", status_code=501)

    async def initiate_disbursement(self, **_kwargs: Any) -> DisbursementResult:
        raise PaymentRailError("Zest outbound disbursements are not configured", status_code=501)

    async def verify_disbursement(self, reference: str) -> DisbursementResult:
        raise PaymentRailError("Zest disbursement verification is not configured", status_code=501)

    async def get_wallet_balance(self) -> WalletBalanceResult:
        raise PaymentRailError("Zest wallet balance API is not configured", status_code=501)

    @staticmethod
    def is_payment_success(status: str | None) -> bool:
        from app.integrations.zest.constants import PAYMENT_STATUS_SUCCESS

        return (status or "").lower() in PAYMENT_STATUS_SUCCESS
