"""
Stanbic sandbox Account Opening API (OpenAPI 2.0.0 + status 1.0.0).

Specs: ``backend/app/integrations/stanbic/specs/account-opening_*.json``

This provisions a CASA account (not a wallet collection virtual account). Use it
when partner onboarding requires a full account before NIP / collections products.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import structlog

from app.core.config import settings
from app.integrations.payments.schemas import PaymentRailError
from app.integrations.stanbic.constants import (
    PATH_ACCOUNT_OPENING_CREATE,
    PATH_ACCOUNT_OPENING_STATUS,
    ACCOUNT_OPENING_SUCCESS_CODES,
    ACCOUNT_OPENING_STATUS_SUCCESS,
)

logger = structlog.get_logger()


@dataclass(frozen=True)
class AccountOpeningSubmitResult:
    reference: str
    response_code: str
    message: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class AccountOpeningStatusResult:
    reference: str
    response_code: str
    message: str
    account_number: str | None
    cif_id: str | None
    pending: bool
    raw: dict[str, Any]


class StanbicAccountOpeningClient:
    """Client-Id / Client-Secret headers per the account-opening OpenAPI specs."""

    def __init__(self) -> None:
        self.create_base = settings.stanbic_account_opening_base_url.rstrip("/")
        self.status_base = settings.stanbic_account_opening_status_base_url.rstrip("/")
        self.client_id = settings.stanbic_client_id
        self.client_secret = settings.stanbic_client_secret

    @property
    def _use_mock(self) -> bool:
        return settings.stanbic_mock or not settings.stanbic_enabled

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Client-Id": self.client_id,
            "Client-Secret": self.client_secret,
        }

    @staticmethod
    def request_date_for(dt: datetime) -> str:
        """Status API expects DD-MON-YY (e.g. 04-AUG-26)."""
        return dt.strftime("%d-%b-%y").upper()

    async def create_account(self, payload: dict[str, Any]) -> AccountOpeningSubmitResult:
        ref = str(payload.get("accountOpeningRefId") or "")
        if self._use_mock:
            return AccountOpeningSubmitResult(
                reference=ref,
                response_code="00",
                message="SUCCESS",
                raw={"mock": True, "responseCode": "00", "responseMsg": "SUCCESS"},
            )

        url = f"{self.create_base}{PATH_ACCOUNT_OPENING_CREATE}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=self._headers(), json=payload)

        try:
            body = response.json()
        except ValueError as exc:
            raise PaymentRailError("Invalid Stanbic account-opening response", status_code=502) from exc

        if response.status_code == 401:
            raise PaymentRailError("Stanbic account-opening authentication rejected", status_code=502)

        code = str(body.get("responseCode") or body.get("responsecode") or "").strip()
        msg = str(body.get("responseMsg") or body.get("responseDesc") or "")
        if response.status_code >= 400 or (code and code not in ACCOUNT_OPENING_SUCCESS_CODES):
            raise PaymentRailError(msg or "Account opening request failed", status_code=502, provider_code=code)

        return AccountOpeningSubmitResult(reference=ref, response_code=code or "00", message=msg, raw=body)

    async def get_status(
        self,
        *,
        account_opening_ref_id: str,
        request_date: str | None = None,
    ) -> AccountOpeningStatusResult:
        req_date = request_date or self.request_date_for(datetime.now())
        if self._use_mock:
            return AccountOpeningStatusResult(
                reference=account_opening_ref_id,
                response_code=ACCOUNT_OPENING_STATUS_SUCCESS,
                message="Account Creation is Successful",
                account_number="9901234567",
                cif_id="MOCK-CIF",
                pending=False,
                raw={"mock": True},
            )

        url = f"{self.status_base}{PATH_ACCOUNT_OPENING_STATUS}"
        params = {"accountOpeningRefID": account_opening_ref_id, "requestDate": req_date}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self._headers(), params=params)

        try:
            body = response.json()
        except ValueError as exc:
            raise PaymentRailError("Invalid Stanbic account-opening status response", status_code=502) from exc

        rbx = str(body.get("rbxResponseCode") or "").strip()
        rbx_msg = str(body.get("rbxResponseMsg") or "")
        details = body.get("responseDetails") if isinstance(body.get("responseDetails"), dict) else {}
        account = str(details.get("account") or "").strip() or None
        cif = str(details.get("cifId") or "").strip() or None
        pending = rbx not in ACCOUNT_OPENING_SUCCESS_CODES or not account

        if response.status_code >= 400 and rbx not in ACCOUNT_OPENING_SUCCESS_CODES:
            desc = str(body.get("responseDesc") or rbx_msg or "Status lookup failed")
            raise PaymentRailError(desc, status_code=502, provider_code=rbx or str(response.status_code))

        return AccountOpeningStatusResult(
            reference=account_opening_ref_id,
            response_code=rbx,
            message=rbx_msg,
            account_number=account,
            cif_id=cif,
            pending=pending,
            raw=body,
        )
