"""
SMS delivery.

* SMS_MOCK=true                → OTP written to the log (local dev only)
* SMS_PROVIDER=termii          → sent through Termii on the "dnd" channel, which
                                 reaches numbers on Do-Not-Disturb (required for OTPs)
* SMS_PROVIDER=dojah           → sent through Dojah Messaging with the same keys as the
                                 BVN checks (DOJAH_APP_ID / DOJAH_SECRET_KEY) and a sender
                                 ID registered on Dojah (DOJAH_SENDER_ID). Codes go through
                                 Dojah's OTP endpoint, other texts through its SMS endpoint.
* SMS_MOCK=false, no provider  → 503 SMS_UNAVAILABLE, and the production config
                                 guard refuses to boot, so login can never look
                                 healthy while no customer receives a code.

To add a provider: implement ``SmsSender.send`` and return it from
``get_sms_sender`` for the matching ``SMS_PROVIDER`` value. A sender may also implement
``send_otp(phone, code, purpose)`` to deliver codes through a provider's OTP route.

Codes are always generated and checked by GH Trust (OtpService: attempt limits, expiry,
demo numbers); providers only deliver them.
"""

from typing import Protocol

import httpx
import structlog
from fastapi import status

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode

logger = structlog.get_logger()


class SmsSender(Protocol):
    async def send(self, phone: str, message: str) -> None: ...


class ConsoleSmsSender:
    """Dev-only sender: logs the message instead of sending it."""

    async def send(self, phone: str, message: str) -> None:
        logger.info("sms_mock_delivery", phone=_mask(phone), message=message)


class TermiiSmsSender:
    """https://developers.termii.com/messaging-api — POST {base}/api/sms/send."""

    def __init__(self) -> None:
        s = get_settings()
        self.url = f"{s.termii_base_url.rstrip('/')}/api/sms/send"
        self.api_key = s.termii_api_key
        self.sender_id = s.termii_sender_id
        self.channel = s.termii_channel or "dnd"

    async def send(self, phone: str, message: str) -> None:
        payload = {
            "api_key": self.api_key,
            "to": _international(phone),
            "from": self.sender_id,
            "sms": message,
            "type": "plain",
            "channel": self.channel,
        }
        # One attempt only: a blind retry could deliver two different codes.
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.post(self.url, json=payload)
        except httpx.HTTPError as exc:
            logger.error("sms_termii_unreachable", phone=_mask(phone), error=type(exc).__name__)
            raise _unavailable() from exc

        try:
            body = res.json()
        except ValueError:
            body = {}
        if res.status_code >= 400 or (body.get("code") not in (None, "ok")) or not body.get("message_id"):
            # Never log the payload: it holds the API key and the OTP.
            logger.error(
                "sms_termii_rejected",
                phone=_mask(phone),
                status=res.status_code,
                reason=str(body.get("message") or "")[:200],
            )
            raise _unavailable()
        logger.info("sms_sent", provider="termii", phone=_mask(phone), message_id=body.get("message_id"))


class DojahMessaging:
    """
    Dojah Messaging API (https://docs.dojah.io/api-reference/messaging): send OTP, validate
    OTP, send SMS and message status. Auth: the app's secret key as-is in Authorization
    (no "Bearer") and the App ID in AppId.
    """

    def __init__(self) -> None:
        s = get_settings()
        self.base = f"{s.dojah_base_url.rstrip('/')}/api/v1/messaging"
        self.headers = {"Authorization": s.dojah_secret_key, "AppId": s.dojah_app_id}
        self.sender_id = s.dojah_sender_id
        self.channel = s.dojah_sms_channel or "sms"

    async def _call(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None) -> dict:
        # One attempt only: a blind retry could deliver two codes or two messages.
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.request(method, f"{self.base}{path}", json=json, params=params, headers=self.headers)
        except httpx.HTTPError as exc:
            logger.error("sms_dojah_unreachable", path=path, error=type(exc).__name__)
            raise _unavailable() from exc
        try:
            body = res.json()
        except ValueError:
            body = {}
        entity = body.get("entity") if isinstance(body, dict) else None
        if res.status_code >= 400 or not isinstance(entity, dict):
            # Never log the request: it holds the code. Dojah's error text says why (e.g. 402 = wallet low).
            reason = body.get("error") or body.get("message") if isinstance(body, dict) else None
            logger.error("sms_dojah_rejected", path=path, status=res.status_code, reason=str(reason or "")[:200])
            raise _unavailable()
        return entity

    async def send_otp(self, phone: str, *, code: str | None = None, length: int = 6, expiry_minutes: int = 10) -> dict:
        """POST /otp. With `code`, Dojah delivers that code; without, it makes one. Returns reference_id."""
        body: dict = {
            "sender_id": self.sender_id,
            "destination": _international(phone),
            "channel": self.channel,
            "length": len(code) if code else length,
            "expiry": expiry_minutes,
            "priority": True,
        }
        if code:
            body["otp"] = int(code)  # Dojah takes a number: codes never start with 0 (see OtpService)
        return await self._call("POST", "/otp", json=body)

    async def validate_otp(self, reference_id: str, code: str) -> bool:
        """GET /otp/validate: whether `code` is right and unexpired for that reference_id."""
        entity = await self._call("GET", "/otp/validate", params={"code": code, "reference_id": reference_id})
        return entity.get("valid") is True

    async def send_sms(self, phone: str, message: str) -> dict:
        """POST /sms. Returns message_id (for message_status) and reference_id."""
        body = {"destination": _international(phone), "message": message, "channel": self.channel, "priority": True}
        if self.sender_id:
            body["sender_id"] = self.sender_id
        return await self._call("POST", "/sms", json=body)

    async def message_status(self, message_id: str) -> str:
        """GET /sms/get_status: DELIVERED, PENDING, FAILED…"""
        entity = await self._call("GET", "/sms/get_status", params={"message_id": message_id})
        return str(entity.get("status") or "UNKNOWN").upper()


class DojahSmsSender:
    """SMS_PROVIDER=dojah: codes through Dojah's OTP route, other texts through its SMS route."""

    def __init__(self) -> None:
        self.api = DojahMessaging()

    async def send(self, phone: str, message: str) -> None:
        entity = await self.api.send_sms(phone, message)
        logger.info("sms_sent", provider="dojah", phone=_mask(phone), message_id=entity.get("message_id"))

    async def send_otp(self, phone: str, code: str, purpose: str) -> None:
        minutes = max(1, get_settings().otp_expire_seconds // 60)
        entity = await self.api.send_otp(phone, code=code, expiry_minutes=minutes)
        logger.info(
            "otp_sent", provider="dojah", purpose=purpose, phone=_mask(phone), reference_id=entity.get("reference_id")
        )


class UnavailableSmsSender:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def send(self, phone: str, message: str) -> None:
        logger.error("sms_unavailable", reason=self.reason, phone=_mask(phone))
        raise _unavailable()


def get_sms_sender() -> SmsSender:
    settings = get_settings()
    if settings.sms_mock:
        return ConsoleSmsSender()
    provider = settings.sms_provider.strip().lower()
    if not provider:
        return UnavailableSmsSender("SMS_MOCK=false but SMS_PROVIDER is not set")
    if provider == "termii":
        if not (settings.termii_api_key and settings.termii_sender_id):
            return UnavailableSmsSender("SMS_PROVIDER=termii but TERMII_API_KEY / TERMII_SENDER_ID are not set")
        return TermiiSmsSender()
    if provider == "dojah":
        if not (settings.dojah_app_id and settings.dojah_secret_key and settings.dojah_sender_id):
            return UnavailableSmsSender(
                "SMS_PROVIDER=dojah but DOJAH_APP_ID / DOJAH_SECRET_KEY / DOJAH_SENDER_ID are not set"
            )
        return DojahSmsSender()
    return UnavailableSmsSender(f"SMS provider '{provider}' is not supported")


def otp_message(otp: str, purpose: str) -> str:
    action = {
        "register": "complete your GH Trust registration",
        "login": "sign in to GH Trust",
        "staff_login": "sign in to the GH Trust admin portal",
    }.get(purpose, "verify your GH Trust request")
    return f"{otp} is your code to {action}. It expires in 10 minutes. Never share it."


def _mask(phone: str) -> str:
    return f"{phone[:4]}****{phone[-4:]}" if len(phone) >= 8 else "****"


def _unavailable() -> AppError:
    return AppError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorCode.SMS_UNAVAILABLE,
        "We couldn't send your verification code right now. Please try again shortly.",
    )


def _international(phone: str) -> str:
    """Termii and Dojah want 234XXXXXXXXXX: digits only, no plus."""
    from app.modules.users.models import Customer

    return Customer.normalize_phone(phone).lstrip("+")
