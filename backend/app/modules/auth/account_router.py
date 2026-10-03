"""
The customer's own account: profile photo, and deleting the account.

Deletion works two ways, both proving it's the account holder:
- in the app: signed in, plus the sign-in PIN and typing DELETE;
- on the web (for people without the app, a Google Play requirement): an SMS code to the
  account's phone, plus the sign-in PIN and typing DELETE.
Neither takes an account or customer id from the request: the account is the one signed
in, or the one the phone number and code belong to.
"""

import base64
import binascii
from datetime import datetime, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import CurrentCustomer, DbSession, RedisClient
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import OtpService, RateLimiter, get_client_ip
from app.modules.auth.account_deletion import AccountDeletionService
from app.modules.auth.schemas import CustomerProfileResponse, OtpSentResponse
from app.modules.auth.security_service import SecurityService
from app.modules.users.models import Customer, CustomerStatus

logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["Account"])

MAX_PHOTO_BYTES = 5 * 1024 * 1024
DELETE_WORD = "DELETE"
OTP_PURPOSE = "account_deletion"

WILL_DELETE = [
    "Your sign-in on every phone, saved phones and notifications",
    "Your PINs, profile photo and BVN photo",
    "Your contact details, address and payout bank account",
    "Unfinished loan applications and the documents in them",
    "The text of your support messages",
]
WILL_KEEP = [
    "Loans, repayments, wallet and payment records, and signed loan agreements: financial records we "
    "must keep for at least 5 years after you leave",
    "With those records, only what links them to you: your BVN, name, date of birth and account number",
    "Applications you submitted and their documents, for the same reason",
]


# ── Photo ────────────────────────────────────────────────────────────────────


class ProfilePhotoResponse(BaseModel):
    image: str | None = Field(None, description="Base64 JPEG or PNG; null when there's no photo")
    content_type: str | None = None
    source: Literal["custom", "bvn"] | None = Field(
        None, description="'custom' if the customer chose it, 'bvn' if it's from their BVN record"
    )


class UpdatePhotoRequest(BaseModel):
    image: str = Field(..., description="Base64 JPEG or PNG, up to 5 MB")


def _decode_photo(image: str) -> tuple[str, bytes] | None:
    """(content type, bytes) for a base64 JPEG/PNG, else None."""
    image = (image or "").strip()
    if image.startswith("data:"):
        image = image.split(",", 1)[-1]
    try:
        raw = base64.b64decode(image, validate=True)
    except (binascii.Error, ValueError):
        return None
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", raw
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", raw
    return None


@router.get("/me/photo", response_model=ProfilePhotoResponse, summary="Profile photo")
async def get_profile_photo(customer: CurrentCustomer, db: DbSession) -> ProfilePhotoResponse:
    """The photo the customer chose, else the photo on their BVN record."""
    custom, bvn = (
        await db.execute(
            select(Customer.profile_photo_base64, Customer.bvn_photo_base64).where(Customer.id == customer.id)
        )
    ).one()
    for source, value in (("custom", custom), ("bvn", bvn)):
        decoded = _decode_photo(value) if value else None
        if decoded:
            return ProfilePhotoResponse(
                image=base64.b64encode(decoded[1]).decode(), content_type=decoded[0], source=source
            )
    return ProfilePhotoResponse()


@router.put("/me/photo", response_model=CustomerProfileResponse, summary="Change profile photo")
async def update_profile_photo(
    payload: UpdatePhotoRequest, customer: CurrentCustomer, db: DbSession, redis: RedisClient
) -> CustomerProfileResponse:
    await RateLimiter(redis).hit(f"profile-photo:hour:{customer.id}", 20, 3600)
    decoded = _decode_photo(payload.image)
    if decoded is None or not 1_000 <= len(decoded[1]) <= MAX_PHOTO_BYTES:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ErrorCode.PHOTO_INVALID,
            "Choose a JPG or PNG photo under 5 MB.",
        )
    customer.profile_photo_base64 = base64.b64encode(decoded[1]).decode()
    customer.profile_photo_updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("profile_photo_updated", customer_id=customer.id)
    return CustomerProfileResponse.from_customer(customer)


@router.delete("/me/photo", response_model=CustomerProfileResponse, summary="Remove chosen photo")
async def remove_profile_photo(customer: CurrentCustomer, db: DbSession) -> CustomerProfileResponse:
    """Go back to the BVN photo."""
    customer.profile_photo_base64 = None
    customer.profile_photo_updated_at = None
    await db.flush()
    return CustomerProfileResponse.from_customer(customer)


# ── Deletion ─────────────────────────────────────────────────────────────────


class DeletionBlocker(BaseModel):
    code: str
    message: str


class DeletionCheckResponse(BaseModel):
    can_delete: bool
    blockers: list[DeletionBlocker]
    will_delete: list[str]
    will_keep: list[str]


class DeleteAccountRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=8, description="The 6-digit sign-in PIN")
    confirmation: str = Field(..., description=f"Must be '{DELETE_WORD}'")


class WebDeletionCodeRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=20)


class WebDeleteAccountRequest(DeleteAccountRequest):
    phone: str = Field(..., min_length=10, max_length=20)
    otp: str = Field(..., min_length=4, max_length=8)


class AccountDeletedResponse(BaseModel):
    status: Literal["deleted"] = "deleted"
    deleted_at: datetime


def _check_word(confirmation: str) -> None:
    if confirmation.strip().upper() != DELETE_WORD:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ErrorCode.DELETE_CONFIRMATION_REQUIRED,
            f"Type {DELETE_WORD} to confirm.",
        )


@router.get(
    "/me/account-deletion",
    response_model=DeletionCheckResponse,
    summary="Can this account be deleted, and what happens",
)
async def deletion_check(customer: CurrentCustomer, db: DbSession) -> DeletionCheckResponse:
    blockers = await AccountDeletionService(db).blockers(customer)
    return DeletionCheckResponse(
        can_delete=not blockers,
        blockers=[DeletionBlocker(code=b.code, message=b.message) for b in blockers],
        will_delete=WILL_DELETE,
        will_keep=WILL_KEEP,
    )


@router.delete(
    "/me",
    response_model=AccountDeletedResponse,
    summary="Delete my account",
    responses={409: {"description": "A loan, application, wallet balance or withdrawal is still open"}},
)
async def delete_my_account(
    payload: DeleteAccountRequest, request: Request, customer: CurrentCustomer, db: DbSession, redis: RedisClient
) -> AccountDeletedResponse:
    """
    Permanently delete the signed-in customer's account. Needs the sign-in PIN and the word
    DELETE. Every session ends at once. Refused (409) while anything is still open.
    """
    _check_word(payload.confirmation)
    await RateLimiter(redis).hit(f"account-delete:hour:{customer.id}", 10, 3600)
    deletion = AccountDeletionService(db)
    await deletion.ensure_deletable(customer)  # before the PIN, so a blocked customer isn't asked twice
    await SecurityService(db).verify_login_pin(customer, payload.pin, session_id=request.state.session_id)
    result = await deletion.delete(customer)
    return AccountDeletedResponse(deleted_at=result.deleted_at)


@router.post(
    "/account-deletion/request-otp",
    response_model=OtpSentResponse,
    summary="Web account deletion: send a code",
)
async def web_deletion_code(
    payload: WebDeletionCodeRequest, request: Request, db: DbSession, redis: RedisClient
) -> OtpSentResponse:
    """Texts a code to the account's phone. Says the same thing whether or not an account exists."""
    phone = Customer.normalize_phone(payload.phone)
    ip = get_client_ip(request)
    limiter = RateLimiter(redis)
    await limiter.check_login_request(ip, phone)
    customer = await db.scalar(
        select(Customer).where(Customer.phone_primary == phone, Customer.status == CustomerStatus.ACTIVE)
    )
    otp = OtpService(redis)
    expires_in = get_settings().otp_expire_seconds
    if customer is not None:
        await limiter.check_otp_send(ip, phone)
        expires_in = await otp.send(OTP_PURPOSE, phone, phone)
    return OtpSentResponse(
        message="If an account uses this number, we've sent it a code.",
        phone_masked=Customer.mask_phone(phone),
        expires_in=expires_in,
        purpose=OTP_PURPOSE,
        dev_code=getattr(otp, "dev_code", None),
    )


@router.post(
    "/account-deletion/confirm",
    response_model=AccountDeletedResponse,
    summary="Web account deletion: confirm",
    responses={409: {"description": "A loan, application, wallet balance or withdrawal is still open"}},
)
async def web_delete_account(
    payload: WebDeleteAccountRequest, request: Request, db: DbSession, redis: RedisClient
) -> AccountDeletedResponse:
    """Delete the account the phone number belongs to, with its SMS code and sign-in PIN."""
    _check_word(payload.confirmation)
    phone = Customer.normalize_phone(payload.phone)
    await RateLimiter(redis).check_otp_verify(get_client_ip(request))
    await OtpService(redis).verify(OTP_PURPOSE, phone, payload.otp)
    customer = await db.scalar(
        select(Customer).where(Customer.phone_primary == phone, Customer.status == CustomerStatus.ACTIVE)
    )
    if customer is None:
        raise AppError(status.HTTP_400_BAD_REQUEST, ErrorCode.OTP_INVALID, "That code isn't valid. Request a new one.")
    deletion = AccountDeletionService(db)
    await deletion.ensure_deletable(customer)
    await SecurityService(db).verify_login_pin(customer, payload.pin)
    result = await deletion.delete(customer)
    return AccountDeletedResponse(deleted_at=result.deleted_at)
