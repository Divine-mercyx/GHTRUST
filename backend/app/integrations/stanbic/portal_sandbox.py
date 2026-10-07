"""
Stanbic developer-portal sandbox APIs (testapi.stanbicibtc.com).

OpenAPI sources live under ``specs/``: NPS name enquiry + single transfer,
transaction history, credit check. Auth is ``Client-Id`` / ``Client-Secret`` on
each product base URL (same subscription keys as Account Opening).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from app.core.config import settings
from app.integrations.payments.schemas import PaymentRailError, TransientRailError
from app.integrations.retry import transient_retry
from app.integrations.stanbic.constants import (
    ACCOUNT_OPENING_SUCCESS_CODES,
    PATH_NPS_NAME_ENQUIRY,
    PATH_NPS_SINGLE_TRANSFER,
    PATH_NPS_TRANSFER_STATUS,
    PATH_TRANSACTION_HISTORY,
    TRANSFER_STATUS_FAILED,
    TRANSFER_STATUS_PENDING,
    TRANSFER_STATUS_SUCCESS,
)

logger = structlog.get_logger()


class StanbicPortalRetryable(TransientRailError):
    pass


def portal_tran_date(dt: datetime | None = None) -> str:
    """NPS status queries use DD-MON-YY (e.g. 05-OCT-26)."""
    when = dt or datetime.now(timezone.utc)
    return when.strftime("%d-%b-%y").upper()


def _portal_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Client-Id": settings.stanbic_client_id,
        "Client-Secret": settings.stanbic_client_secret,
    }


def _check_response_code(payload: dict[str, Any]) -> None:
    code = str(
        payload.get("responseCode") or payload.get("responsecode") or payload.get("rbxResponseCode") or ""
    ).strip()
    if code and code not in ACCOUNT_OPENING_SUCCESS_CODES:
        raise PaymentRailError(
            str(payload.get("responseMsg") or payload.get("responseDesc") or "Stanbic request failed"),
            status_code=502,
            provider_code=code,
        )


@transient_retry()  # StanbicPortalRetryable is a TransientRailError, so it is retried
async def _portal_request(
    method: str,
    url: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.request(method, url, headers=_portal_headers(), json=json, params=params)
    except httpx.HTTPError as exc:
        logger.warning("stanbic_portal_transport_error", url=url, error=str(exc))
        raise StanbicPortalRetryable("Stanbic portal API unreachable", status_code=502) from exc

    if response.status_code >= 500:
        raise StanbicPortalRetryable("Stanbic portal API unavailable", status_code=502)

    try:
        payload = response.json()
    except ValueError as exc:
        raise PaymentRailError("Invalid Stanbic portal response", status_code=502) from exc

    if response.status_code == 401:
        raise PaymentRailError("Stanbic portal authentication rejected", status_code=502)

    if response.status_code >= 400:
        _check_response_code(payload if isinstance(payload, dict) else {})
        raise PaymentRailError(
            str((payload or {}).get("responseMsg") or "Stanbic portal request failed"),
            status_code=502,
        )

    if isinstance(payload, dict):
        _check_response_code(payload)
    return payload if isinstance(payload, dict) else {"raw": payload}


def map_nps_transfer_status(payload: dict[str, Any]) -> str:
    code = str(payload.get("responseCode") or "").strip()
    msg = str(payload.get("responseMsg") or "").upper()
    credited = str(payload.get("destAcctCredited") or "").upper()
    if not code:
        # No verdict: never treat as failed, or the customer is refunded for money that left.
        return TRANSFER_STATUS_PENDING
    if code != "00":
        return TRANSFER_STATUS_FAILED
    if "PROCESS" in msg or credited in ("N", "NO", "FALSE"):
        return TRANSFER_STATUS_PENDING
    if credited in ("Y", "YES", "TRUE") or "SUCCESS" in msg:
        return TRANSFER_STATUS_SUCCESS
    return TRANSFER_STATUS_PENDING


async def name_enquiry(account_number: str, bank_code: str) -> dict[str, Any]:
    base = settings.stanbic_name_enquiry_base_url.rstrip("/")
    url = f"{base}{PATH_NPS_NAME_ENQUIRY}"
    return await _portal_request(
        "POST",
        url,
        json={"accountNumber": account_number, "bankCode": bank_code},
    )


async def single_transfer(payload: dict[str, Any]) -> dict[str, Any]:
    base = settings.stanbic_nps_base_url.rstrip("/")
    url = f"{base}{PATH_NPS_SINGLE_TRANSFER}"
    return await _portal_request("POST", url, json=payload)


async def transfer_status(payload: dict[str, Any]) -> dict[str, Any]:
    base = settings.stanbic_nps_base_url.rstrip("/")
    url = f"{base}{PATH_NPS_TRANSFER_STATUS}"
    return await _portal_request("POST", url, json=payload)


async def transaction_history(
    *,
    account_number: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    base = settings.stanbic_transaction_history_base_url.rstrip("/")
    url = f"{base}{PATH_TRANSACTION_HISTORY}"
    return await _portal_request(
        "POST",
        url,
        json={"accountNumber": account_number, "startDate": start_date, "endDate": end_date},
    )
