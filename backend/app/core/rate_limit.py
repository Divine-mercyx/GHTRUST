import hashlib
import hmac
import secrets

import structlog
from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode

logger = structlog.get_logger()


class RateLimitExceeded(HTTPException):
    def __init__(self, retry_after: int = 60):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


class RateLimiter:
    """Redis fixed-window rate limiter."""

    def __init__(self, redis: Redis):
        self.redis = redis
        # Set by send() in local development only (see Settings.expose_dev_otp).
        self.dev_code: str | None = None

    async def hit(self, key: str, limit: int, window_seconds: int) -> None:
        if not get_settings().rate_limits_active:
            return
        full_key = f"ratelimit:{key}"
        # Create-with-TTL and increment in one MULTI, so a crash between the two
        # can never leave a counter without an expiry (a permanent lockout).
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(full_key, 0, ex=window_seconds, nx=True)
            pipe.incr(full_key)
            _, count = await pipe.execute()
        if count > limit:
            ttl = await self.redis.ttl(full_key)
            raise RateLimitExceeded(retry_after=max(ttl, 1))

    async def check_bvn_registration(self, ip: str, bvn: str) -> None:
        s = get_settings()
        await self.hit(f"bvn:ip:{ip}", s.rate_limit_bvn_per_ip_hour, 3600)
        await self.hit(f"bvn:bvn:{bvn}", s.rate_limit_bvn_per_bvn_day, 86400)

    async def check_otp_send(self, ip: str, phone: str) -> None:
        s = get_settings()
        await self.hit(f"otp:send:phone:{phone}", s.rate_limit_otp_send_per_phone_15min, 900)
        await self.hit(f"otp:send:ip:{ip}", s.rate_limit_otp_send_per_ip_hour, 3600)

    async def check_otp_verify(self, ip: str) -> None:
        s = get_settings()
        await self.hit(f"otp:verify:ip:{ip}", s.rate_limit_otp_verify_per_ip_hour, 3600)

    async def check_login_request(self, ip: str, phone: str) -> None:
        s = get_settings()
        await self.hit(f"login:phone:{phone}", s.rate_limit_login_request_per_phone_15min, 900)
        await self.hit(f"login:ip:{ip}", s.rate_limit_otp_send_per_ip_hour, 3600)

    async def check_refresh(self, ip: str) -> None:
        # Generous: a legitimate device refreshes every ~15 minutes.
        await self.hit(f"refresh:ip:{ip}", 120, 3600)


def get_client_ip(request: Request) -> str:
    """
    Resolve the client IP without trusting spoofable headers.

    With TRUSTED_PROXY_COUNT=N, the real client is the Nth address from the
    right of X-Forwarded-For (each trusted proxy appends the address it saw).
    Anything to the left of that was written by the client and is ignored.
    With N=0 the header is ignored entirely.
    """
    trusted = get_settings().trusted_proxy_count
    if trusted > 0:
        forwarded = request.headers.get("X-Forwarded-For", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(hops) >= trusted:
            return hops[-trusted]
    if request.client:
        return request.client.host
    return "unknown"


def _hash_otp(otp: str) -> str:
    key = get_settings().secret_key.encode("utf-8")
    return hmac.new(key, otp.encode("utf-8"), hashlib.sha256).hexdigest()


class OtpService:
    """OTP generation, storage, and verification via Redis."""

    def __init__(self, redis: Redis):
        self.redis = redis

    def _generate(self) -> str:
        return "".join(secrets.choice("0123456789") for _ in range(get_settings().otp_length))

    async def send(self, purpose: str, identifier: str, phone: str) -> int:
        """Generate OTP, store its hash in Redis, dispatch SMS. Returns expiry seconds."""
        from app.integrations.sms import get_sms_sender, otp_message

        settings = get_settings()
        otp = self._generate()
        key = f"otp:{purpose}:{identifier}"
        attempts_key = f"otp:attempts:{purpose}:{identifier}"

        # Send first: if delivery fails, no dangling OTP is left in Redis.
        await get_sms_sender().send(phone, otp_message(otp, purpose))

        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.setex(key, settings.otp_expire_seconds, _hash_otp(otp))
            pipe.setex(attempts_key, settings.otp_expire_seconds, "0")
            await pipe.execute()
        self.dev_code = otp if settings.expose_dev_otp else None
        return settings.otp_expire_seconds

    async def verify(self, purpose: str, identifier: str, otp: str) -> bool:
        settings = get_settings()
        key = f"otp:{purpose}:{identifier}"
        attempts_key = f"otp:attempts:{purpose}:{identifier}"

        stored = await self.redis.get(key)
        if not stored:
            raise AppError(
                status.HTTP_400_BAD_REQUEST,
                ErrorCode.OTP_EXPIRED,
                "OTP expired or not found. Request a new one.",
            )

        attempts = int(await self.redis.get(attempts_key) or "0")
        if attempts >= settings.otp_max_attempts:
            await self.redis.delete(key, attempts_key)
            raise AppError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                ErrorCode.OTP_ATTEMPTS_EXCEEDED,
                "Too many failed OTP attempts. Request a new OTP.",
            )

        if not hmac.compare_digest(stored, _hash_otp(otp)):
            await self.redis.incr(attempts_key)
            remaining = settings.otp_max_attempts - attempts - 1
            raise AppError(
                status.HTTP_400_BAD_REQUEST,
                ErrorCode.OTP_INVALID,
                f"Invalid OTP. {remaining} attempt(s) remaining.",
            )

        await self.redis.delete(key, attempts_key)
        return True


class CustomerMask:
    @staticmethod
    def mask_phone(phone: str) -> str:
        from app.modules.users.models import Customer

        return Customer.mask_phone(phone)

    @staticmethod
    def mask_bvn(bvn: str) -> str:
        if len(bvn) >= 6:
            return f"{bvn[:3]}****{bvn[-3:]}"
        return "****"
