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
from app.integrations.monnify.constants import (
    DISBURSEMENT_STATUS_COMPLETED,
    DISBURSEMENT_STATUS_FAILED,
    DISBURSEMENT_STATUS_PENDING,
    DISBURSEMENT_STATUS_REVERSED,
    DISBURSEMENT_STATUS_SUCCESS,
)
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
from app.integrations.payments.mock_accounts import mock_account_number

logger = structlog.get_logger()

MOCK_ACCOUNT_REFERENCE = "GHTRUST_MOCK_REF_001"
MOCK_ACCOUNT_PREFIX = "50"  # mock NUBANs look like 50xxxxxxxx
MOCK_BANK_NAME = "Monnify Sandbox Bank"
MOCK_BANK_CODE = "035"


class MonnifyClient:
    """
    Monnify payment rail client for GH Trust MFB.

    Docs: https://developers.monnify.com/api

    Inbound: Reserved (static) account → SUCCESSFUL_TRANSACTION webhook
    Outbound: Single disbursement → SUCCESSFUL/FAILED/REVERSED_DISBURSEMENT webhooks
    """

    _access_token: str | None = None
    _token_expires_at: float = 0.0

    def __init__(self) -> None:
        self.base_url = settings.monnify_base_url.rstrip("/")
        self.api_key = settings.monnify_api_key
        self.secret_key = settings.monnify_secret_key
        self.contract_code = settings.monnify_contract_code
        self.wallet_account_number = settings.monnify_wallet_account_number

    @property
    def _use_mock(self) -> bool:
        return settings.monnify_mock or not settings.monnify_enabled

    @staticmethod
    def _unwrap(payload: dict[str, Any]) -> Any:
        if not payload.get("requestSuccessful"):
            raise PaymentRailError(
                str(payload.get("responseMessage") or "Monnify request failed"),
                status_code=502,
                provider_code=str(payload.get("responseCode") or ""),
            )
        return payload.get("responseBody")

    @classmethod
    def clear_token_cache(cls) -> None:
        cls._access_token = None
        cls._token_expires_at = 0.0

    async def _authenticate(self) -> str:
        if (
            self._access_token
            and time.time() < self._token_expires_at - 60
        ):
            return self._access_token

        if self._use_mock:
            self._access_token = "mock_monnify_token"
            self._token_expires_at = time.time() + 3600
            return self._access_token

        url = f"{self.base_url}/api/v1/auth/login"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json={"apiKey": self.api_key, "secretKey": self.secret_key},
            )

        if response.status_code >= 500:
            raise PaymentRailError("Monnify authentication unavailable", status_code=502)

        try:
            payload = response.json()
        except ValueError as exc:
            raise PaymentRailError("Invalid Monnify auth response", status_code=502) from exc

        body = self._unwrap(payload)
        token = str(body.get("accessToken") or "")
        if not token:
            raise PaymentRailError("Monnify auth token missing", status_code=502)

        expires_in = int(body.get("expiresIn") or 3600)
        self._access_token = token
        self._token_expires_at = time.time() + expires_in
        return token

    async def _headers(self) -> dict[str, str]:
        token = await self._authenticate()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @transient_retry()
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        if self._use_mock:
            raise PaymentRailError("Mock mode — use explicit mock handlers", status_code=502)

        url = f"{self.base_url}{path}"
        headers = await self._headers()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                )
        except httpx.HTTPError as exc:
            logger.warning("monnify_transport_error", method=method, path=path, error=str(exc))
            raise TransientRailError("Monnify unreachable. Please try again.", status_code=502) from exc

        if response.status_code >= 500:
            logger.error(
                "monnify_api_error",
                method=method,
                path=path,
                status=response.status_code,
                body=response.text[:300],
            )
            raise TransientRailError("Monnify service unavailable. Please try again.", status_code=502)

        try:
            payload = response.json()
        except ValueError as exc:
            raise PaymentRailError("Invalid Monnify response", status_code=502) from exc

        if response.status_code >= 400:
            message = str(payload.get("responseMessage") or "Monnify request failed")
            raise PaymentRailError(
                message,
                status_code=response.status_code,
                provider_code=str(payload.get("responseCode") or ""),
            )

        return self._unwrap(payload)

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
        """
        Verify Monnify webhook HMAC-SHA512 signature.

        https://developers.monnify.com/docs/webhooks
        """
        if not signature or not settings.monnify_secret_key:
            return False
        expected = hmac.new(
            settings.monnify_secret_key.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def _decimal_amount(value: Any) -> Decimal:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))

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
        if self._use_mock:
            return ReservedAccountResult(
                account_reference=account_reference,
                account_number=mock_account_number(account_reference, MOCK_ACCOUNT_PREFIX),
                account_name=account_name,
                bank_name=MOCK_BANK_NAME,
                bank_code=MOCK_BANK_CODE,
                currency=currency,
                reservation_reference=f"RSV_{uuid4().hex[:12]}",
                raw={"mock": True},
            )

        payload: dict[str, Any] = {
            "accountReference": account_reference,
            "accountName": account_name,
            "currencyCode": currency,
            "contractCode": self.contract_code,
            "customerEmail": customer_email,
            "customerName": customer_name,
            "getAllAvailableBanks": False,
        }
        if bvn:
            payload["bvn"] = bvn

        body = await self._request("POST", "/api/v1/bank-transfer/reserved-accounts", json=payload)
        accounts = body.get("accounts") or []
        if not accounts:
            raise PaymentRailError("Monnify reserved account response missing accounts", status_code=502)

        primary = accounts[0]
        return ReservedAccountResult(
            account_reference=str(body.get("accountReference") or account_reference),
            account_number=str(primary.get("accountNumber") or ""),
            account_name=str(primary.get("accountName") or account_name),
            bank_name=str(primary.get("bankName") or ""),
            bank_code=str(primary.get("bankCode") or "") or None,
            currency=currency,
            reservation_reference=str(primary.get("reservationReference") or "") or None,
            raw=body,
        )

    async def deactivate_reserved_account(self, account_reference: str) -> bool:
        """
        Deallocate a customer's reserved account so it stops receiving transfers (used when
        the customer deletes their account). Monnify: "Deallocating a reserved account".
        """
        if self._use_mock:
            return True
        await self._request("DELETE", f"/api/v1/bank-transfer/reserved-accounts/reference/{account_reference}")
        return True

    async def get_reserved_account(self, account_reference: str) -> ReservedAccountResult:
        if self._use_mock:
            return ReservedAccountResult(
                account_reference=account_reference,
                account_number=mock_account_number(account_reference, MOCK_ACCOUNT_PREFIX),
                account_name="Mock Customer",
                bank_name=MOCK_BANK_NAME,
                bank_code=MOCK_BANK_CODE,
                raw={"mock": True},
            )

        body = await self._request(
            "GET",
            f"/api/v1/bank-transfer/reserved-accounts/{account_reference}",
        )
        accounts = body.get("accounts") or []
        primary = accounts[0] if accounts else {}
        return ReservedAccountResult(
            account_reference=str(body.get("accountReference") or account_reference),
            account_number=str(primary.get("accountNumber") or ""),
            account_name=str(primary.get("accountName") or ""),
            bank_name=str(primary.get("bankName") or ""),
            bank_code=str(primary.get("bankCode") or "") or None,
            reservation_reference=str(primary.get("reservationReference") or "") or None,
            raw=body,
        )

    async def supported_banks(self) -> list[Bank]:
        if self._use_mock:
            return list(MOCK_BANKS)
        body = await self._request("GET", "/api/v1/banks")
        return [Bank(code=str(b["code"]), name=str(b["name"])) for b in body or [] if b.get("code") and b.get("name")]

    async def validate_bank_account(self, account_number: str, bank_code: str) -> ResolvedAccount:
        if self._use_mock:
            return ResolvedAccount(
                account_number=account_number,
                account_name="Mock Account Holder",
                bank_code=bank_code,
            )

        body = await self._request(
            "GET",
            "/api/v2/disbursements/account/validate",
            params={"accountNumber": account_number, "bankCode": bank_code},
        )
        return ResolvedAccount(
            account_number=str(body.get("accountNumber") or account_number),
            account_name=str(body.get("accountName") or ""),
            bank_code=str(body.get("bankCode") or bank_code),
        )

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
                status=DISBURSEMENT_STATUS_SUCCESS,
                amount=amount,
                currency=currency,
                transaction_id=f"MNFY_MOCK_{uuid4().hex[:10]}",
                narration=narration,
                raw={"mock": True, "status": DISBURSEMENT_STATUS_SUCCESS},
            )

        if not self.wallet_account_number:
            raise PaymentRailError("Monnify wallet account number not configured", status_code=503)

        body = await self._request(
            "POST",
            "/api/v2/disbursements/single",
            json={
                "amount": float(amount),
                "reference": reference,
                "narration": narration,
                "destinationBankCode": bank_code,
                "destinationAccountNumber": account_number,
                "destinationAccountName": account_name,
                "currency": currency,
                "sourceAccountNumber": self.wallet_account_number,
            },
        )
        return DisbursementResult(
            reference=str(body.get("reference") or reference),
            status=str(body.get("status") or DISBURSEMENT_STATUS_PENDING),
            amount=self._decimal_amount(body.get("amount") or amount),
            currency=str(body.get("currency") or currency),
            transaction_id=str(body.get("transactionId") or body.get("transactionReference") or "") or None,
            narration=narration,
            raw=body,
        )

    async def verify_disbursement(self, reference: str) -> DisbursementResult:
        if self._use_mock:
            return DisbursementResult(
                reference=reference,
                status=DISBURSEMENT_STATUS_SUCCESS,
                amount=Decimal("0"),
                raw={"mock": True},
            )

        body = await self._request(
            "GET",
            "/api/v2/disbursements/single/summary",
            params={"reference": reference},
        )
        return DisbursementResult(
            reference=str(body.get("reference") or reference),
            status=str(body.get("status") or ""),
            amount=self._decimal_amount(body.get("amount")),
            currency=str(body.get("currency") or "NGN"),
            transaction_id=str(body.get("transactionReference") or "") or None,
            narration=str(body.get("narration") or "") or None,
            raw=body,
        )

    async def verify_transaction(self, transaction_reference: str) -> TransactionVerification:
        if self._use_mock:
            return TransactionVerification(
                transaction_reference=transaction_reference,
                amount=Decimal("0"),
                status="PAID",
                raw={"mock": True},
            )

        body = await self._request(
            "GET",
            f"/api/v2/transactions/{transaction_reference}",
        )
        product = body.get("product") or {}
        return TransactionVerification(
            transaction_reference=str(body.get("transactionReference") or transaction_reference),
            payment_reference=str(body.get("paymentReference") or "") or None,
            amount=self._decimal_amount(body.get("amountPaid") or body.get("amount")),
            currency=str(body.get("currency") or "NGN"),
            status=str(body.get("paymentStatus") or body.get("status") or ""),
            payment_method=str(body.get("paymentMethod") or "") or None,
            account_reference=str(product.get("reference") or "") or None,
            raw=body,
        )

    async def get_wallet_balance(self) -> WalletBalanceResult:
        if self._use_mock:
            return WalletBalanceResult(
                available_balance=Decimal("1000000"),
                ledger_balance=Decimal("1000000"),
            )

        if not self.wallet_account_number:
            raise PaymentRailError("Monnify wallet account number not configured", status_code=503)

        body = await self._request(
            "GET",
            "/api/v2/disbursements/wallet-balance",
            params={"accountNumber": self.wallet_account_number},
        )
        return WalletBalanceResult(
            available_balance=self._decimal_amount(body.get("availableBalance")),
            ledger_balance=self._decimal_amount(body.get("ledgerBalance")),
            currency=str(body.get("currency") or "NGN"),
        )

    @staticmethod
    def is_disbursement_success(status: str) -> bool:
        normalized = (status or "").upper()
        return normalized in {DISBURSEMENT_STATUS_SUCCESS, DISBURSEMENT_STATUS_COMPLETED}

    @staticmethod
    def is_disbursement_failed(status: str) -> bool:
        normalized = (status or "").upper()
        return normalized in {DISBURSEMENT_STATUS_FAILED, DISBURSEMENT_STATUS_REVERSED}
