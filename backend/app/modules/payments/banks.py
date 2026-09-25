"""
Bank directory for the customer app: the bank picker and account-name check.

Bank codes are rail-specific (Paystack/Monnify use CBN codes, Stanbic NIP
codes), so the list always comes from the active payment rail — never a list
hard-coded in the app — and is cached for a day per provider.

Name enquiry reveals an account holder's name, so it is authenticated and
rate-limited per customer to stop it being used to enumerate accounts.
"""

import json

import structlog
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.deps import CurrentCustomer, RedisClient
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import RateLimiter
from app.integrations.payments.factory import get_payment_client
from app.integrations.payments.schemas import Bank, PaymentRailError

logger = structlog.get_logger()

BANKS_TTL_SECONDS = 24 * 3600
RESOLVE_PER_MINUTE = 10
RESOLVE_PER_DAY = 100

router = APIRouter(prefix="/banks", tags=["Banks"])


class BankResponse(BaseModel):
    code: str
    name: str


class ResolveAccountRequest(BaseModel):
    bank_code: str = Field(..., min_length=3, max_length=10, pattern=r"^\d+$")
    account_number: str = Field(..., min_length=10, max_length=10, pattern=r"^\d{10}$")


class ResolveAccountResponse(BaseModel):
    bank_code: str
    account_number: str
    account_name: str


def _unavailable(message: str) -> AppError:
    return AppError(
        status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.PAYMENT_PROVIDER_ERROR, message
    )


@router.get("", response_model=list[BankResponse])
async def list_banks(
    _customer: CurrentCustomer, redis: RedisClient
) -> list[BankResponse]:
    """Banks the active payment rail can pay into, sorted by name."""
    key = f"banks:{get_settings().active_payment_provider}"
    try:
        cached = await redis.get(key)
        if cached:
            return [BankResponse(**b) for b in json.loads(cached)]
    except Exception:
        logger.warning("banks_cache_unavailable", exc_info=True)

    try:
        banks: list[Bank] = await get_payment_client().supported_banks()
    except PaymentRailError as exc:
        logger.error("banks_list_failed", error=exc.message)
        raise _unavailable(
            "The bank list is unavailable right now. Please try again shortly."
        ) from exc

    unique = {b.code: b for b in banks}
    result = sorted(
        (BankResponse(code=b.code, name=b.name) for b in unique.values()),
        key=lambda b: b.name.lower(),
    )
    if result:
        try:
            await redis.set(
                key, json.dumps([b.model_dump() for b in result]), ex=BANKS_TTL_SECONDS
            )
        except Exception:
            logger.warning("banks_cache_write_failed", exc_info=True)
    return result


@router.post("/resolve", response_model=ResolveAccountResponse)
async def resolve_account(
    payload: ResolveAccountRequest, customer: CurrentCustomer, redis: RedisClient
) -> ResolveAccountResponse:
    """Look up the name on a bank account so the customer can confirm it's theirs."""
    limiter = RateLimiter(redis)
    await limiter.hit(f"bank-resolve:min:{customer.id}", RESOLVE_PER_MINUTE, 60)
    await limiter.hit(f"bank-resolve:day:{customer.id}", RESOLVE_PER_DAY, 86400)

    try:
        resolved = await get_payment_client().validate_bank_account(
            payload.account_number, payload.bank_code
        )
    except PaymentRailError as exc:
        if exc.status_code == 501:
            raise _unavailable(
                "Account verification isn't available right now."
            ) from exc
        # Rails report "no such account" and outages alike; the likely cause is a typo.
        logger.info(
            "bank_resolve_failed",
            customer_id=customer.id,
            bank_code=payload.bank_code,
            error=exc.message,
        )
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ErrorCode.BANK_ACCOUNT_UNVERIFIED,
            "We couldn't verify this account. Check the bank and account number and try again.",
        ) from exc

    if not resolved.account_name.strip():
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ErrorCode.BANK_ACCOUNT_UNVERIFIED,
            "We couldn't verify this account. Check the bank and account number and try again.",
        )
    return ResolveAccountResponse(
        bank_code=payload.bank_code,
        account_number=payload.account_number,
        account_name=resolved.account_name.strip(),
    )
