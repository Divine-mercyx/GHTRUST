"""
Stanbic Credit Check API (spec: credit-check_2.0.0.json).

Use from the loan credit stage to pull outstanding loans / bureau checks when
``STANBIC_CREDIT_CHECK_ENABLED`` is on.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.integrations.stanbic.constants import (
    PATH_CREDIT_CBN_CHECK,
    PATH_CREDIT_OUTSTANDING_LOAN,
    PATH_CREDIT_PRIVATE_CHECK,
)
from app.integrations.stanbic.portal_sandbox import _portal_request


async def outstanding_loans_by_bvn(bvn: str) -> dict[str, Any]:
    base = settings.stanbic_credit_check_base_url.rstrip("/")
    url = f"{base}{PATH_CREDIT_OUTSTANDING_LOAN}"
    return await _portal_request("GET", url, params={"bvn": bvn})


async def cbn_credit_check(body: dict[str, Any]) -> dict[str, Any]:
    base = settings.stanbic_credit_check_base_url.rstrip("/")
    url = f"{base}{PATH_CREDIT_CBN_CHECK}"
    return await _portal_request("POST", url, json=body)


async def private_credit_check(body: dict[str, Any]) -> dict[str, Any]:
    base = settings.stanbic_credit_check_base_url.rstrip("/")
    url = f"{base}{PATH_CREDIT_PRIVATE_CHECK}"
    return await _portal_request("POST", url, json=body)
