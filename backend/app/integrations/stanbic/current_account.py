"""
Current Account Opening (spec: current-account-opening_1.0.0.json).

Opens a **current account** for an **existing CIF** after Account Opening 2.0.
This is not a wallet collection virtual account — see docs/stanbic-api-checklist.md.

Auth: OAuth2 client credentials (Bearer), separate from Client-Id products.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.integrations.payments.schemas import PaymentRailError
from app.integrations.stanbic.constants import ACCOUNT_OPENING_SUCCESS_CODES, PATH_CURRENT_ACCOUNT_OPENING
from app.integrations.stanbic.portal_sandbox import _check_response_code


async def _oauth_token() -> str:
    if settings.stanbic_mock or not settings.stanbic_enabled:
        return "mock_current_account_token"
    url = settings.stanbic_oauth_token_url.strip()
    if not url:
        raise PaymentRailError("STANBIC_OAUTH_TOKEN_URL not configured for current-account opening", status_code=503)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.stanbic_client_id,
                "client_secret": settings.stanbic_client_secret,
                "scope": "access",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    payload = response.json()
    token = str(payload.get("access_token") or "")
    if not token:
        raise PaymentRailError("Stanbic OAuth token missing", status_code=502)
    return token


async def open_current_account(body: dict[str, Any]) -> dict[str, Any]:
    if settings.stanbic_mock or not settings.stanbic_enabled:
        return {
            "responseCode": "00",
            "responseMsg": "SUCCESS",
            "responseDetails": {"accountNumber": "9901234567", "cifID": body.get("cifID", "MOCK")},
        }

    base = settings.stanbic_current_account_base_url.rstrip("/")
    url = f"{base}{PATH_CURRENT_ACCOUNT_OPENING}"
    token = await _oauth_token()
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            json=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise PaymentRailError("Invalid current-account opening response", status_code=502) from exc
    if response.status_code >= 400:
        _check_response_code(payload)
        raise PaymentRailError(str(payload.get("responseMsg") or "Current account opening failed"), status_code=502)
    _check_response_code(payload)
    return payload
