"""
SMS delivery.

* SMS_MOCK=true                → OTP written to the log (local dev only)
* SMS_PROVIDER=termii          → sent through Termii on the "dnd" channel, which
                                 reaches numbers on Do-Not-Disturb (required for OTPs)
* SMS_MOCK=false, no provider  → 503 SMS_UNAVAILABLE, and the production config
                                 guard refuses to boot, so login can never look
                                 healthy while no customer receives a code.

To add a provider: implement ``SmsSender.send`` and return it from
``get_sms_sender`` for the matching ``SMS_PROVIDER`` value.
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
    """Termii wants 234XXXXXXXXXX: digits only, no plus."""
    from app.modules.users.models import Customer

    return Customer.normalize_phone(phone).lstrip("+")
