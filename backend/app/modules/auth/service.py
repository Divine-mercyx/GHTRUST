import base64
import binascii
import json
import re
import secrets
from typing import NoReturn
from datetime import date, datetime, timezone

import structlog
from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.demo import demo_identity, is_demo_bvn, is_demo_phone
from app.core.rate_limit import OtpService, RateLimiter
from app.core.errors import AppError, ErrorCode
from app.core.security import hash_token
from app.integrations.dojah.client import DojahClient
from app.integrations.dojah.schemas import DojahError, DojahSelfieVerification, LivenessResult
from app.modules.auth.models import SelfieAttempt, SelfieOutcome, SubjectType
from app.modules.auth.schemas import (
    AuthTokenResponse,
    CustomerProfileResponse,
    DeviceApprovalRequiredResponse,
    DeviceInfo,
    OtpSentResponse,
    SelfieRequiredResponse,
    SessionResponse,
    TokenPair,
)
from app.modules.auth.security_service import SecurityService
from app.modules.auth.session_service import RequestMeta, SessionService
from app.modules.users.models import Customer, CustomerStatus

logger = structlog.get_logger()


def _validate_bvn(bvn: str) -> str:
    bvn = bvn.strip()
    if not re.fullmatch(r"\d{11}", bvn):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="BVN must be exactly 11 digits")
    return bvn


def _parse_dob(dob_str: str | None) -> date | None:
    if not dob_str:
        return None
    try:
        return date.fromisoformat(dob_str)
    except ValueError:
        return None


SELFIE_TICKET_SECONDS = 30 * 60
# Per image; the app sends ~960 px JPEGs (a few hundred KB), and the whole request is
# capped by MAX_SELFIE_BODY_MB.
MAX_SELFIE_BYTES = 10 * 1024 * 1024


def _selfie_key(token: str) -> str:
    return f"register:selfie:{hash_token(token)}"


def _selfie_cooldown_key(bvn: str) -> str:
    return f"register:selfie:cooldown:{hash_token(bvn)}"


def _cooldown_error(seconds: int) -> AppError:
    minutes = max(1, -(-seconds // 60))
    return AppError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        ErrorCode.SELFIE_COOLDOWN,
        f"Too many selfie attempts. Please try again in {minutes} minute(s).",
        errors=[{"retry_after": seconds}],
        headers={"Retry-After": str(seconds)},
    )


def _clean_selfie(image: str) -> str:
    """Base64 without a data: URL prefix, checked to be a JPEG or PNG of sensible size."""
    image = image.strip()
    if image.startswith("data:"):
        image = image.split(",", 1)[-1]
    try:
        raw = base64.b64decode(image, validate=True)
    except (binascii.Error, ValueError):
        raw = b""
    is_image = raw.startswith(b"\xff\xd8") or raw.startswith(b"\x89PNG")
    if not is_image or not 5_000 <= len(raw) <= MAX_SELFIE_BYTES:
        raise AppError(
            status.HTTP_400_BAD_REQUEST,
            ErrorCode.SELFIE_UNREADABLE,
            "We couldn't read that photo. Take it again facing the camera in good light.",
        )
    return image


def _generate_account_number() -> str:
    return f"30{secrets.randbelow(10**8):08d}"


class AuthService:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis
        self.dojah = DojahClient()
        self.otp = OtpService(redis)

    async def _check_selfie_cooldown(self, bvn: str) -> None:
        """After too many failed selfies a BVN waits out a cooldown before trying again."""
        ttl = await self.redis.ttl(_selfie_cooldown_key(bvn))
        if ttl and ttl > 0:
            raise _cooldown_error(ttl)

    async def register_with_bvn(self, bvn: str, *, ip: str) -> OtpSentResponse:
        bvn = _validate_bvn(bvn)
        demo = is_demo_bvn(bvn)
        limiter = RateLimiter(self.redis)
        if not demo:  # testers rerun sign-up with the same demo BVN many times a day
            await limiter.check_bvn_registration(ip, bvn)
        # Checked before the (paid) BVN lookup.
        await self._check_selfie_cooldown(bvn)

        existing = await self.db.execute(select(Customer).where(Customer.bvn == bvn))
        customer = existing.scalar_one_or_none()
        if customer and demo:
            await self._retire_demo_customer(customer)
            customer = None
        if customer and customer.status == CustomerStatus.DELETED:
            # Its financial records are kept against this BVN, so it can't simply open again.
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.ACCOUNT_CLOSED,
                "The account for this BVN was deleted. To open a new one, please contact us.",
            )
        if customer and customer.status == CustomerStatus.ACTIVE:
            raise AppError(status.HTTP_409_CONFLICT, ErrorCode.ACCOUNT_EXISTS, "An account with this BVN already exists. Please login.")
        if customer and customer.phone_verified:
            raise AppError(status.HTTP_409_CONFLICT, ErrorCode.ACCOUNT_EXISTS, "Account already verified. Please login with your phone number.")

        try:
            entity = demo_identity(bvn) if demo else await self.dojah.lookup_bvn_advanced(bvn)
        except DojahError as e:
            if e.status_code == 404:
                raise AppError(status.HTTP_404_NOT_FOUND, ErrorCode.BVN_NOT_FOUND, e.message) from e
            raise AppError(status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.KYC_UNAVAILABLE, e.message) from e

        if not entity.phone_number1:
            raise AppError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ErrorCode.BVN_NO_PHONE,
                "There's no phone number on this BVN record, so we can't send you a code. "
                "Please visit a branch to open your account.",
            )
        phone = Customer.normalize_phone(entity.phone_number1)

        # Phone numbers are unique per customer; a second BVN registered to the same
        # number (e.g. a family member's) must not reach the unique constraint as a 500.
        clash = await self.db.execute(
            select(Customer.id).where(Customer.phone_primary == phone, Customer.bvn != bvn)
        )
        if clash.first() is not None:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.PHONE_IN_USE,
                "BVN phone number already belongs to a customer with a different BVN.",
            )

        if customer is None:
            customer = Customer(
                bvn=bvn,
                account_number=_generate_account_number(),
                branch=settings.default_branch,
                status=CustomerStatus.PENDING_OTP,
                first_name=entity.first_name.title(),
                last_name=entity.last_name.title(),
                middle_name=entity.middle_name.title() if entity.middle_name else None,
                gender=entity.gender,
                date_of_birth=_parse_dob(entity.date_of_birth),
                title=entity.title,
                phone_primary=phone,
                phone_secondary=Customer.normalize_phone(entity.phone_number2) if entity.phone_number2 else None,
                email=entity.email.lower() if entity.email else None,
                residential_address=entity.residential_address or None,
                state_of_residence=entity.state_of_residence,
                lga_of_residence=entity.lga_of_residence,
                state_of_origin=entity.state_of_origin,
                lga_of_origin=entity.lga_of_origin,
                nationality=entity.nationality,
                marital_status=entity.marital_status,
                enrollment_bank=entity.enrollment_bank,
                enrollment_branch=entity.enrollment_branch,
                level_of_account=entity.level_of_account,
                name_on_card=entity.name_on_card or None,
                bvn_registration_date=entity.registration_date or None,
                watch_listed=entity.watch_listed,
                bvn_photo_base64=entity.image,
                phone_verified=False,
            )
            self.db.add(customer)
        else:
            # Refresh profile from latest BVN lookup for pending accounts
            customer.first_name = entity.first_name.title()
            customer.last_name = entity.last_name.title()
            customer.phone_primary = phone

        await self.db.flush()

        await limiter.check_otp_send(ip, phone)
        expires_in = await self.otp.send("register", bvn, phone)

        logger.info("register_bvn_success", customer_id=customer.id, bvn=bvn[:3] + "****")

        return OtpSentResponse(
            message="OTP sent to the phone number registered with your BVN.",
            phone_masked=Customer.mask_phone(phone),
            expires_in=expires_in,
            purpose="registration",
            dev_code=self.otp.dev_code,
        )

    async def _retire_demo_customer(self, customer: Customer) -> None:
        """
        Starting sign-up again with a demo BVN: close the previous attempt instead of
        deleting it (loans, wallet and audit rows still point at it), sign it out
        everywhere, and free its BVN and phone for the new attempt.
        """
        await SessionService(self.db).revoke_all(
            subject_type=SubjectType.CUSTOMER, subject_id=customer.id, reason="demo_restart"
        )
        customer.status = CustomerStatus.INACTIVE
        customer.bvn = "R" + "".join(secrets.choice("0123456789") for _ in range(10))
        customer.phone_primary = f"retired-{secrets.token_hex(6)}"
        await self.db.flush()
        logger.info("demo_registration_restarted", customer_id=customer.id)

    async def verify_registration_otp(
        self,
        bvn: str,
        otp: str,
        *,
        meta: RequestMeta,
        device: DeviceInfo | None = None,
    ) -> AuthTokenResponse | SelfieRequiredResponse:
        bvn = _validate_bvn(bvn)
        await RateLimiter(self.redis).check_otp_verify(meta.ip or "unknown")
        await self.otp.verify("register", bvn, otp)

        result = await self.db.execute(select(Customer).where(Customer.bvn == bvn))
        customer = result.scalar_one_or_none()
        if not customer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found. Start again with your BVN.")

        if customer.watch_listed and customer.watch_listed.upper() == "YES":
            raise AppError(status.HTTP_403_FORBIDDEN, ErrorCode.ACCOUNT_RESTRICTED, "Account cannot be opened at this time. Please visit a branch.")

        if settings.dojah_selfie_required:
            await self._check_selfie_cooldown(bvn)
            # The code proves they hold the BVN's phone; a selfie proves they're its owner.
            token = secrets.token_urlsafe(32)
            await self.redis.set(
                _selfie_key(token),
                json.dumps({"bvn": bvn, "attempts": 0}),
                ex=SELFIE_TICKET_SECONDS,
            )
            return SelfieRequiredResponse(
                registration_token=token,
                expires_in=SELFIE_TICKET_SECONDS,
                attempts_left=settings.dojah_selfie_max_attempts,
                first_name=customer.first_name,
            )

        return await self._open_account(customer, meta=meta, device=device)

    async def verify_registration_selfie(
        self,
        token: str,
        selfie_image: str,
        *,
        meta: RequestMeta,
        device: DeviceInfo | None = None,
        liveness_frames: list[str] | None = None,
    ) -> AuthTokenResponse:
        """
        Last step of sign-up: a live face capture must pass Dojah's liveness check and
        match the BVN photo, then the account opens.
        """
        liveness_frames = liveness_frames or []
        await RateLimiter(self.redis).check_otp_verify(meta.ip or "unknown")
        key = _selfie_key(token)
        raw = await self.redis.get(key)
        if not raw:
            raise AppError(
                status.HTTP_410_GONE,
                ErrorCode.REGISTRATION_EXPIRED,
                "This sign-up has expired. Please start again with your BVN.",
            )
        ticket = json.loads(raw)
        image = _clean_selfie(selfie_image)
        frames = [_clean_selfie(f) for f in liveness_frames]
        if settings.dojah_liveness_required:
            # A live capture yields several different frames; a replayed still photo can't.
            if not frames or len({image, *frames}) != len(frames) + 1:
                raise AppError(
                    status.HTTP_400_BAD_REQUEST,
                    ErrorCode.SELFIE_UNREADABLE,
                    "Use the live camera in the app to capture your face.",
                )

        result_customer = await self.db.execute(select(Customer).where(Customer.bvn == ticket["bvn"]))
        customer = result_customer.scalar_one_or_none()
        if customer is None:
            await self.redis.delete(key)
            raise AppError(status.HTTP_410_GONE, ErrorCode.REGISTRATION_EXPIRED, "Please start again with your BVN.")

        demo = is_demo_bvn(ticket["bvn"])
        if demo:
            # No BVN photo to match against; kept out of the Onboarding face-check figures.
            result = DojahSelfieVerification(confidence_value=100.0, match=True)
            liveness = None
        else:
            result, liveness = await self._check_face(key, ticket, customer, image)

        # Single use: a second request with this ticket finds nothing.
        if not await self.redis.delete(key):
            raise AppError(status.HTTP_410_GONE, ErrorCode.REGISTRATION_EXPIRED, "Please start again with your BVN.")
        customer.selfie_verified_at = datetime.now(timezone.utc)
        customer.selfie_match_score = result.confidence_value
        logger.info("registration_selfie_matched", customer_id=customer.id, confidence=result.confidence_value)
        if not demo:
            await self._record_selfie_attempt(
                customer, ticket, SelfieOutcome.PASSED, match=result.confidence_value, liveness=liveness, commit=False
            )
        return await self._open_account(customer, meta=meta, device=device)

    async def _check_face(
        self, key: str, ticket: dict, customer: Customer, image: str
    ) -> tuple[DojahSelfieVerification, LivenessResult | None]:
        """Dojah liveness (if required) and BVN photo match. Raises on a failed check."""
        dojah = DojahClient()
        liveness: LivenessResult | None = None
        try:
            if settings.dojah_liveness_required:
                liveness = await dojah.check_liveness(image, settings.dojah_liveness_min_probability)
                if not liveness.live:
                    logger.warning(
                        "registration_liveness_failed",
                        customer_id=customer.id,
                        reason=liveness.reason,
                        probability=liveness.probability,
                    )
                    await self._record_selfie_attempt(customer, ticket, SelfieOutcome.NOT_LIVE, liveness=liveness)
                    await self._selfie_attempt_failed(
                        key, ticket, customer, ErrorCode.LIVENESS_FAILED,
                        "We couldn't confirm a live face. {left} attempt(s) left.",
                    )
            result = await dojah.verify_bvn_selfie(ticket["bvn"], image, settings.dojah_selfie_threshold)
        except DojahError as e:
            unreadable = e.status_code == 400
            await self._record_selfie_attempt(
                customer,
                ticket,
                SelfieOutcome.UNREADABLE if unreadable else SelfieOutcome.PROVIDER_ERROR,
                liveness=liveness,
            )
            if unreadable:
                raise AppError(
                    status.HTTP_400_BAD_REQUEST,
                    ErrorCode.SELFIE_UNREADABLE,
                    "We couldn't read that photo. Take it again facing the camera in good light.",
                ) from e
            raise AppError(status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.KYC_UNAVAILABLE, e.message) from e

        if not result.match:
            logger.warning("registration_selfie_no_match", customer_id=customer.id, confidence=result.confidence_value)
            await self._record_selfie_attempt(
                customer, ticket, SelfieOutcome.NO_MATCH, match=result.confidence_value, liveness=liveness
            )
            await self._selfie_attempt_failed(
                key, ticket, customer, ErrorCode.SELFIE_NO_MATCH,
                "Your selfie didn't match your BVN photo. {left} attempt(s) left.",
            )
        return result, liveness

    async def _record_selfie_attempt(
        self,
        customer: Customer,
        ticket: dict,
        outcome: SelfieOutcome,
        *,
        match: float | None = None,
        liveness: LivenessResult | None = None,
        commit: bool = True,
    ) -> None:
        """
        Keep every face check for pilot tuning. Failed checks end in an error, which
        rolls the request back, so those are committed straight away.
        """
        self.db.add(
            SelfieAttempt(
                customer_id=customer.id,
                outcome=outcome.value,
                attempt_number=ticket["attempts"] + 1,
                threshold=settings.dojah_selfie_threshold,
                liveness_min=settings.dojah_liveness_min_probability if settings.dojah_liveness_required else None,
                match_score=match,
                liveness_probability=liveness.probability if liveness else None,
                liveness_reason=liveness.reason if liveness else None,
            )
        )
        if commit:
            await self.db.commit()

    async def _selfie_attempt_failed(
        self, key: str, ticket: dict, customer: Customer, code: str, message: str
    ) -> NoReturn:
        """Use up an attempt; after the last one the BVN cools down before sign-up can restart."""
        ticket["attempts"] += 1
        left = settings.dojah_selfie_max_attempts - ticket["attempts"]
        if left <= 0:
            cooldown = settings.dojah_selfie_cooldown_minutes * 60
            await self.redis.delete(key)
            await self.redis.set(_selfie_cooldown_key(ticket["bvn"]), "1", ex=cooldown)
            logger.warning("registration_selfie_cooldown", customer_id=customer.id, seconds=cooldown)
            raise _cooldown_error(cooldown)
        ttl = await self.redis.ttl(key)
        await self.redis.set(key, json.dumps(ticket), ex=max(ttl, 1))
        raise AppError(
            status.HTTP_400_BAD_REQUEST, code, message.format(left=left), errors=[{"attempts_left": left}]
        )

    async def _open_account(
        self, customer: Customer, *, meta: RequestMeta, device: DeviceInfo | None
    ) -> AuthTokenResponse:
        customer.status = CustomerStatus.ACTIVE
        customer.phone_verified = True
        customer.phone_verified_at = datetime.now(timezone.utc)
        await self.db.flush()

        from app.modules.payments.wallet_service import WalletService

        wallets = WalletService(self.db)
        if is_demo_bvn(customer.bvn):
            # A made-up identity mustn't reach the payment provider: internal wallet only.
            await wallets.ledger.get_or_create_wallet(customer.id)
        else:
            await wallets.provision_paystack(customer)

        return await self._issue_tokens(customer, meta=meta, device=device)

    async def resend_registration_otp(self, bvn: str, *, ip: str) -> OtpSentResponse:
        bvn = _validate_bvn(bvn)
        limiter = RateLimiter(self.redis)
        result = await self.db.execute(
            select(Customer).where(Customer.bvn == bvn, Customer.status == CustomerStatus.PENDING_OTP)
        )
        customer = result.scalar_one_or_none()
        if not customer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No pending registration found for this BVN.")

        await limiter.check_otp_send(ip, customer.phone_primary)
        expires_in = await self.otp.send("register", bvn, customer.phone_primary)
        return OtpSentResponse(
            message="OTP resent successfully.",
            phone_masked=Customer.mask_phone(customer.phone_primary),
            expires_in=expires_in,
            purpose="registration",
            dev_code=self.otp.dev_code,
        )

    async def request_login_otp(self, phone: str, *, ip: str) -> OtpSentResponse:
        normalized = Customer.normalize_phone(phone)
        limiter = RateLimiter(self.redis)
        await limiter.check_login_request(ip, normalized)
        result = await self.db.execute(
            select(Customer).where(
                Customer.phone_primary == normalized,
                Customer.status == CustomerStatus.ACTIVE,
            )
        )
        customer = result.scalar_one_or_none()
        if not customer:
            logger.warning("login_otp_unknown_phone", phone=Customer.mask_phone(normalized))
            return OtpSentResponse(
                message="If an account exists, an OTP has been sent to your registered phone number.",
                phone_masked=Customer.mask_phone(normalized),
                expires_in=settings.otp_expire_seconds,
                purpose="login",
            )

        await limiter.check_otp_send(ip, normalized)
        expires_in = await self.otp.send("login", normalized, normalized)
        return OtpSentResponse(
            message="OTP sent to your registered phone number.",
            phone_masked=Customer.mask_phone(normalized),
            expires_in=expires_in,
            purpose="login",
            dev_code=self.otp.dev_code,
        )

    async def verify_login_otp(
        self,
        phone: str,
        otp: str,
        *,
        meta: RequestMeta,
        device: DeviceInfo | None = None,
    ) -> AuthTokenResponse | DeviceApprovalRequiredResponse:
        normalized = Customer.normalize_phone(phone)
        await RateLimiter(self.redis).check_otp_verify(meta.ip or "unknown")
        await self.otp.verify("login", normalized, otp)

        result = await self.db.execute(
            select(Customer).where(
                Customer.phone_primary == normalized,
                Customer.status == CustomerStatus.ACTIVE,
            )
        )
        customer = result.scalar_one_or_none()
        if not customer:
            raise AppError(status.HTTP_401_UNAUTHORIZED, "UNAUTHENTICATED", "Invalid credentials.")

        # A new phone while another is signed in: hold the sign-in until it's approved there.
        # Demo accounts are shared by testers and reviewers: nobody is there to approve.
        security = SecurityService(self.db)
        approvers = [] if is_demo_phone(normalized) else await security.approver_sessions(customer, device)
        if approvers:
            return await security.start_approval(customer, approvers, device, meta)

        customer.last_login_at = datetime.now(timezone.utc)
        await self.db.flush()
        return await self._issue_tokens(customer, meta=meta, device=device)

    async def complete_device_approval(
        self, approval_id: str, secret: str, code: str, *, meta: RequestMeta, device: DeviceInfo | None
    ) -> AuthTokenResponse:
        customer, approval = await SecurityService(self.db).complete_approval(approval_id, secret, code)
        return await self._issue_tokens(customer, meta=meta, device=device or _approval_device(approval))

    async def lost_phone_sign_in(
        self,
        approval_id: str,
        secret: str,
        bvn: str,
        pin: str | None,
        *,
        meta: RequestMeta,
        device: DeviceInfo | None,
    ) -> AuthTokenResponse:
        customer, approval = await SecurityService(self.db).lost_phone_sign_in(approval_id, secret, bvn, pin)
        return await self._issue_tokens(customer, meta=meta, device=device or _approval_device(approval))

    async def pin_sign_in(
        self, device_id: str, device_token: str, pin: str, *, meta: RequestMeta, device: DeviceInfo | None
    ) -> AuthTokenResponse:
        await RateLimiter(self.redis).check_otp_verify(meta.ip or "unknown")
        customer = await SecurityService(self.db).pin_sign_in(device_id, device_token, pin)
        device = (device or DeviceInfo()).model_copy(update={"device_id": device_id})
        return await self._issue_tokens(customer, meta=meta, device=device)

    async def resend_login_otp(self, phone: str, *, ip: str) -> OtpSentResponse:
        return await self.request_login_otp(phone, ip=ip)

    # -- Sessions -------------------------------------------------------------

    async def _issue_tokens(
        self, customer: Customer, *, meta: RequestMeta, device: DeviceInfo | None
    ) -> AuthTokenResponse:
        pair = await SessionService(self.db).issue(
            subject_type=SubjectType.CUSTOMER,
            subject_id=customer.id,
            phone=customer.phone_primary,
            device=device,
            meta=meta,
        )
        device_token = await SecurityService(self.db).trust_device(customer, device)
        return AuthTokenResponse(
            **pair.model_dump(),
            customer=CustomerProfileResponse.from_customer(customer),
            device_token=device_token,
        )

    async def refresh(self, refresh_token: str, *, meta: RequestMeta) -> TokenPair:
        await RateLimiter(self.redis).check_refresh(meta.ip or "unknown")
        sessions = SessionService(self.db)
        session, new_refresh = await sessions.rotate(
            refresh_token, subject_type=SubjectType.CUSTOMER, meta=meta
        )
        customer = await self.db.get(Customer, session.subject_id)
        if not customer or customer.status != CustomerStatus.ACTIVE:
            await sessions.revoke(session, reason="account_inactive")
            await self.db.commit()
            raise AppError(
                status.HTTP_401_UNAUTHORIZED,
                ErrorCode.ACCOUNT_INACTIVE,
                "Account not found or inactive",
            )
        return sessions.pair_for(session, new_refresh, phone=customer.phone_primary)

    async def logout(
        self, customer: Customer, session_id: str, *, everywhere: bool = False, forget_device: bool = False
    ) -> None:
        """
        Sign out. The phone stays trusted (PIN sign-in still works there) unless
        ``forget_device`` ("Not you?") or everywhere, which forgets every other phone.
        """
        sessions = SessionService(self.db)
        security = SecurityService(self.db)
        session = await sessions.get_owned(
            session_id, subject_type=SubjectType.CUSTOMER, subject_id=customer.id
        )
        if everywhere:
            await sessions.revoke_all(
                subject_type=SubjectType.CUSTOMER, subject_id=customer.id, reason="logout_all"
            )
            await security.forget_other_devices(customer.id, keep_device_id=session.device_id)
        else:
            await sessions.revoke(session, reason="logout")
        if forget_device and session.device_id:
            await security.forget_device(customer.id, session.device_id)

    async def list_sessions(self, customer: Customer, current_session_id: str) -> list[SessionResponse]:
        active = await SessionService(self.db).list_active(
            subject_type=SubjectType.CUSTOMER, subject_id=customer.id
        )
        return [
            SessionResponse(
                id=s.id,
                device_id=s.device_id,
                device_name=s.device_name,
                platform=s.platform,
                app_version=s.app_version,
                ip_address=s.ip_address,
                created_at=s.created_at,
                last_used_at=s.last_used_at,
                expires_at=s.expires_at,
                current=s.id == current_session_id,
            )
            for s in active
        ]

    async def revoke_session(self, customer: Customer, session_id: str, current_session_id: str | None = None) -> None:
        sessions = SessionService(self.db)
        session = await sessions.get_owned(
            session_id, subject_type=SubjectType.CUSTOMER, subject_id=customer.id
        )
        await sessions.revoke(session, reason="revoked_by_user")
        # Signed out from another phone: that phone can't PIN back in either.
        if session.id != current_session_id and session.device_id:
            await SecurityService(self.db).forget_device(customer.id, session.device_id)


def _approval_device(approval) -> DeviceInfo:
    return DeviceInfo(
        device_id=approval.device_id,
        device_name=approval.device_name,
        platform=approval.platform,
        app_version=approval.app_version,
    )
