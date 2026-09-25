import hashlib
import hmac
from typing import Any
from uuid import uuid4

import httpx
import structlog
from app.integrations.retry import transient_retry

from app.core.config import settings
from app.integrations.payments.schemas import MOCK_BANKS, Bank
from app.integrations.payments.schemas import ResolvedAccount as RailResolvedAccount
from app.integrations.paystack.constants import (
    TRANSACTION_STATUS_SUCCESS,
    TRANSFER_STATUS_SUCCESS,
)
from app.integrations.paystack.schemas import (
    AssignDedicatedAccountRequest,
    CreateCustomerRequest,
    CreateDedicatedAccountRequest,
    CreateTransferRecipientRequest,
    FinalizeTransferRequest,
    InitializeTransactionRequest,
    InitializeTransactionResponse,
    InitiateTransferRequest,
    PaystackBalance,
    PaystackBank,
    PaystackCustomer,
    PaystackDedicatedAccount,
    PaystackEnvelope,
    PaystackError,
    TransientPaystackError,
    PaystackTransaction,
    PaystackTransfer,
    PaystackTransferRecipient,
    ResolvedAccount,
    ValidateCustomerRequest,
)

logger = structlog.get_logger()

MOCK_CUSTOMER_CODE = "CUS_mock_ghtrust001"
MOCK_RECIPIENT_CODE = "RCP_mock_ghtrust001"
MOCK_DVA_ACCOUNT = "9930000901"
MOCK_DVA_BANK = "test-bank"


class PaystackClient:
    """
    Paystack payment rail client for GH Trust MFB.

    Docs: https://paystack.com/docs/api/

    Inbound (fund wallet): Customer → DVA → charge.success webhook
    Outbound (withdraw/disburse): Transfer recipient → Transfer → transfer.* webhooks
    """

    def __init__(self) -> None:
        self.base_url = settings.paystack_base_url.rstrip("/")
        self.secret_key = settings.paystack_secret_key

    @property
    def _use_mock(self) -> bool:
        return settings.paystack_mock or not settings.paystack_enabled

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _unwrap(envelope: PaystackEnvelope) -> Any:
        if not envelope.status:
            raise PaystackError(
                envelope.message or "Paystack request failed",
                status_code=502,
                paystack_message=envelope.message,
            )
        return envelope.data

    @transient_retry()
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
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
            logger.warning("paystack_transport_error", method=method, path=path, error=str(exc))
            raise TransientPaystackError("Paystack unreachable. Please try again.", status_code=502) from exc

        if response.status_code >= 500:
            logger.error(
                "paystack_api_error",
                method=method,
                path=path,
                status=response.status_code,
                body=response.text[:300],
            )
            raise TransientPaystackError("Paystack service unavailable. Please try again.", status_code=502)

        try:
            payload = response.json()
        except ValueError as exc:
            raise PaystackError("Invalid Paystack response", status_code=502) from exc

        envelope = PaystackEnvelope.model_validate(payload)
        if response.status_code >= 400 or not envelope.status:
            raise PaystackError(
                envelope.message or "Paystack request failed",
                status_code=response.status_code if response.status_code >= 400 else 502,
                paystack_message=envelope.message,
            )
        return envelope.data

    # --- Customers ---

    async def create_customer(self, payload: CreateCustomerRequest) -> PaystackCustomer:
        if self._use_mock:
            logger.info("paystack_mock_create_customer", email=payload.email)
            return PaystackCustomer(
                id=1,
                customer_code=MOCK_CUSTOMER_CODE,
                email=payload.email,
                first_name=payload.first_name,
                last_name=payload.last_name,
                phone=payload.phone,
            )
        data = await self._request("POST", "/customer", json=payload.model_dump(exclude_none=True))
        return PaystackCustomer.model_validate(data)

    async def fetch_customer(self, customer_code_or_email: str) -> PaystackCustomer:
        if self._use_mock:
            return PaystackCustomer(
                id=1,
                customer_code=MOCK_CUSTOMER_CODE,
                email=f"{customer_code_or_email}@mock.ghtrust.test",
                first_name="ADAEZE",
                last_name="OKAFOR",
                phone="+2348035794364",
            )
        data = await self._request("GET", f"/customer/{customer_code_or_email}")
        return PaystackCustomer.model_validate(data)

    async def validate_customer(
        self, customer_code: str, payload: ValidateCustomerRequest
    ) -> dict[str, Any]:
        if self._use_mock:
            logger.info("paystack_mock_validate_customer", customer_code=customer_code)
            return {"status": "pending"}
        return await self._request(
            "POST",
            f"/customer/{customer_code}/identification",
            json=payload.model_dump(exclude_none=True),
        )

    # --- Dedicated virtual accounts (wallet funding) ---

    async def assign_dedicated_account(
        self, payload: AssignDedicatedAccountRequest
    ) -> dict[str, Any]:
        """Single-step DVA assignment (required for financial services MFB category)."""
        if self._use_mock:
            logger.info("paystack_mock_assign_dva", email=payload.email)
            return {"status": True, "message": "Assign dedicated account in progress"}
        return await self._request(
            "POST",
            "/dedicated_account/assign",
            json=payload.model_dump(exclude_none=True),
        )

    async def create_dedicated_account(
        self, payload: CreateDedicatedAccountRequest
    ) -> PaystackDedicatedAccount:
        if self._use_mock:
            logger.info("paystack_mock_create_dva", customer=payload.customer)
            return PaystackDedicatedAccount(
                id=1,
                account_name="GH Trust / ADAEZE OKAFOR",
                account_number=MOCK_DVA_ACCOUNT,
                assigned=True,
                currency="NGN",
                active=True,
                customer=PaystackCustomer(
                    id=1,
                    customer_code=payload.customer,
                    email="adaeze.okafor@email.com",
                    first_name="ADAEZE",
                    last_name="OKAFOR",
                    phone="+2348035794364",
                ),
                bank=PaystackBank(name="Test Bank", slug=MOCK_DVA_BANK, code="999992"),
            )
        data = await self._request(
            "POST",
            "/dedicated_account",
            json=payload.model_dump(exclude_none=True),
        )
        return PaystackDedicatedAccount.model_validate(data)

    async def fetch_dedicated_account(self, dedicated_account_id: int) -> PaystackDedicatedAccount:
        if self._use_mock:
            return await self.create_dedicated_account(
                CreateDedicatedAccountRequest(
                    customer=MOCK_CUSTOMER_CODE,
                    preferred_bank=settings.paystack_preferred_bank,
                )
            )
        data = await self._request("GET", f"/dedicated_account/{dedicated_account_id}")
        return PaystackDedicatedAccount.model_validate(data)

    async def list_dedicated_accounts(
        self, *, customer: str | None = None, active: bool | None = None
    ) -> list[PaystackDedicatedAccount]:
        if self._use_mock:
            account = await self.create_dedicated_account(
                CreateDedicatedAccountRequest(
                    customer=customer or MOCK_CUSTOMER_CODE,
                    preferred_bank=settings.paystack_preferred_bank,
                )
            )
            return [account]
        params: dict[str, Any] = {}
        if customer:
            params["customer"] = customer
        if active is not None:
            params["active"] = str(active).lower()
        data = await self._request("GET", "/dedicated_account", params=params)
        return [PaystackDedicatedAccount.model_validate(item) for item in data or []]

    async def requery_dedicated_account(self, account_number: str) -> dict[str, Any]:
        """Recover missed inbound transfers for a DVA."""
        if self._use_mock:
            logger.info("paystack_mock_requery_dva", account_number=account_number[-4:])
            return {"status": True, "message": "Requery in progress"}
        return await self._request(
            "GET",
            "/dedicated_account/requery",
            params={"account_number": account_number},
        )

    async def list_dva_providers(self) -> list[PaystackBank]:
        if self._use_mock:
            return [
                PaystackBank(name="Test Bank", slug=MOCK_DVA_BANK, code="999992", active=True)
            ]
        data = await self._request("GET", "/dedicated_account/available_providers")
        return [PaystackBank.model_validate(item) for item in data or []]

    # --- Transactions (optional card/USSD top-up) ---

    async def initialize_transaction(
        self, payload: InitializeTransactionRequest
    ) -> InitializeTransactionResponse:
        reference = payload.reference or f"ghtrust_{uuid4().hex[:16]}"
        if self._use_mock:
            logger.info("paystack_mock_initialize_tx", reference=reference, amount=payload.amount)
            return InitializeTransactionResponse(
                authorization_url=f"https://checkout.paystack.com/mock/{reference}",
                access_code=f"mock_access_{reference}",
                reference=reference,
            )
        body = payload.model_copy(update={"reference": reference}).model_dump(exclude_none=True)
        data = await self._request("POST", "/transaction/initialize", json=body)
        return InitializeTransactionResponse.model_validate(data)

    async def verify_transaction(self, reference: str) -> PaystackTransaction:
        if self._use_mock:
            return PaystackTransaction(
                id=1,
                reference=reference,
                amount=100_000,
                currency="NGN",
                status=TRANSACTION_STATUS_SUCCESS,
                channel="card",
            )
        data = await self._request("GET", f"/transaction/verify/{reference}")
        return PaystackTransaction.model_validate(data)

    # --- Transfer recipients (withdraw / loan disburse destination) ---

    async def create_transfer_recipient(
        self, payload: CreateTransferRecipientRequest
    ) -> PaystackTransferRecipient:
        if self._use_mock:
            logger.info(
                "paystack_mock_create_recipient",
                account=payload.account_number[-4:],
                bank_code=payload.bank_code,
            )
            return PaystackTransferRecipient(
                recipient_code=MOCK_RECIPIENT_CODE,
                name=payload.name,
                type=payload.type,
                currency=payload.currency,
                details={
                    "account_number": payload.account_number,
                    "bank_code": payload.bank_code,
                },
            )
        data = await self._request(
            "POST",
            "/transferrecipient",
            json=payload.model_dump(exclude_none=True),
        )
        return PaystackTransferRecipient.model_validate(data)

    async def fetch_transfer_recipient(self, recipient_code: str) -> PaystackTransferRecipient:
        if self._use_mock:
            return PaystackTransferRecipient(
                recipient_code=recipient_code,
                name="ADAEZE OKAFOR",
                type="nuban",
                currency="NGN",
            )
        data = await self._request("GET", f"/transferrecipient/{recipient_code}")
        return PaystackTransferRecipient.model_validate(data)

    # --- Transfers (payouts) ---

    async def initiate_transfer(self, payload: InitiateTransferRequest) -> PaystackTransfer:
        reference = payload.reference or f"ghtrust_trf_{uuid4().hex[:16]}"
        if self._use_mock:
            logger.info("paystack_mock_initiate_transfer", reference=reference, amount=payload.amount)
            return PaystackTransfer(
                id=1,
                reference=reference,
                transfer_code=f"TRF_mock_{reference[-8:]}",
                amount=payload.amount,
                currency=payload.currency,
                status=TRANSFER_STATUS_SUCCESS,
                reason=payload.reason,
            )
        body = payload.model_copy(update={"reference": reference}).model_dump(exclude_none=True)
        data = await self._request("POST", "/transfer", json=body)
        return PaystackTransfer.model_validate(data)

    async def finalize_transfer(self, payload: FinalizeTransferRequest) -> PaystackTransfer:
        if self._use_mock:
            return PaystackTransfer(
                id=1,
                reference=f"ghtrust_trf_{uuid4().hex[:8]}",
                transfer_code=payload.transfer_code,
                amount=0,
                currency="NGN",
                status=TRANSFER_STATUS_SUCCESS,
            )
        data = await self._request("POST", "/transfer/finalize_transfer", json=payload.model_dump())
        return PaystackTransfer.model_validate(data)

    async def verify_transfer(self, reference: str) -> PaystackTransfer:
        if self._use_mock:
            return PaystackTransfer(
                id=1,
                reference=reference,
                transfer_code=f"TRF_mock_{reference[-8:]}",
                amount=100_000,
                currency="NGN",
                status=TRANSFER_STATUS_SUCCESS,
            )
        data = await self._request("GET", f"/transfer/verify/{reference}")
        return PaystackTransfer.model_validate(data)

    # --- Miscellaneous ---

    async def list_banks(self, *, country: str = "nigeria") -> list[PaystackBank]:
        if self._use_mock:
            return [
                PaystackBank(name="Guaranty Trust Bank", slug="gtb", code="058", active=True),
                PaystackBank(name="Access Bank", slug="access", code="044", active=True),
            ]
        data = await self._request("GET", "/bank", params={"country": country})
        return [PaystackBank.model_validate(item) for item in data or []]

    async def supported_banks(self) -> list[Bank]:
        if self._use_mock:
            return list(MOCK_BANKS)
        return [Bank(code=b.code, name=b.name) for b in await self.list_banks() if b.active]

    async def validate_bank_account(self, account_number: str, bank_code: str) -> RailResolvedAccount:
        """Rail-interface name enquiry (disbursement + the app's account check)."""
        resolved = await self.resolve_account(account_number, bank_code)
        return RailResolvedAccount(
            account_number=resolved.account_number, account_name=resolved.account_name, bank_code=bank_code
        )

    async def resolve_account(self, account_number: str, bank_code: str) -> ResolvedAccount:
        if self._use_mock:
            return ResolvedAccount(
                account_number=account_number,
                account_name="ADAEZE CHINWE OKAFOR",
            )
        data = await self._request(
            "GET",
            "/bank/resolve",
            params={"account_number": account_number, "bank_code": bank_code},
        )
        return ResolvedAccount.model_validate(data)

    async def get_balance(self) -> list[PaystackBalance]:
        if self._use_mock:
            return [PaystackBalance(currency="NGN", balance=50_000_000)]
        data = await self._request("GET", "/balance")
        if isinstance(data, list):
            return [PaystackBalance.model_validate(item) for item in data]
        return [PaystackBalance.model_validate(data)]

    # --- Webhook signature ---

    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str | None) -> bool:
        """
        Verify x-paystack-signature using HMAC SHA512 and secret key.
        https://paystack.com/docs/payments/webhooks/#verify-event-origin
        """
        if not signature or not settings.paystack_secret_key:
            return False
        digest = hmac.new(
            settings.paystack_secret_key.encode("utf-8"),
            payload,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(digest, signature)
