"""
Uniform API error envelope.

Every error response has the same shape, so clients (the mobile app, the admin
portal) can branch on a stable ``code`` instead of pattern-matching English:

    {
      "detail": "Invalid OTP. 3 attempt(s) remaining.",   # human-readable
      "code": "OTP_INVALID",                                # stable, machine-readable
      "errors": [...],                                      # optional field-level detail
      "request_id": "b1c2..."                               # correlates with server logs
    }

``detail`` keeps its historical meaning (a string, or the FastAPI validation
list for 422s) so existing clients that read ``detail`` keep working.

Raise ``AppError`` for anything a client should branch on. A plain
``HTTPException`` still works and gets a code derived from its status.
"""

from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger()

STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    426: "UPGRADE_REQUIRED",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    501: "NOT_IMPLEMENTED",
    502: "UPSTREAM_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


class ErrorCode:
    """Codes clients are expected to branch on. Add here, never rename."""

    # Auth
    OTP_INVALID = "OTP_INVALID"
    OTP_EXPIRED = "OTP_EXPIRED"
    OTP_ATTEMPTS_EXCEEDED = "OTP_ATTEMPTS_EXCEEDED"
    TOKEN_INVALID = "TOKEN_INVALID"
    SESSION_REVOKED = "SESSION_REVOKED"
    SESSION_IDLE_TIMEOUT = "SESSION_IDLE_TIMEOUT"
    REFRESH_TOKEN_INVALID = "REFRESH_TOKEN_INVALID"
    REFRESH_TOKEN_REUSED = "REFRESH_TOKEN_REUSED"
    ACCOUNT_INACTIVE = "ACCOUNT_INACTIVE"
    ACCOUNT_EXISTS = "ACCOUNT_EXISTS"
    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"  # the BVN belongs to an account the customer deleted
    # Account deletion refused (several reasons at once; each is listed in `errors`).
    ACCOUNT_DELETION_BLOCKED = "ACCOUNT_DELETION_BLOCKED"
    LOAN_OUTSTANDING = "LOAN_OUTSTANDING"
    APPLICATION_IN_PROGRESS = "APPLICATION_IN_PROGRESS"
    WALLET_NOT_EMPTY = "WALLET_NOT_EMPTY"
    WITHDRAWAL_PENDING = "WITHDRAWAL_PENDING"
    DELETE_CONFIRMATION_REQUIRED = "DELETE_CONFIRMATION_REQUIRED"
    PHOTO_INVALID = "PHOTO_INVALID"
    PHONE_IN_USE = "PHONE_IN_USE"
    PRODUCT_EXISTS = "PRODUCT_EXISTS"
    WORKFLOW_REQUIRED = "WORKFLOW_REQUIRED"
    ACCOUNT_RESTRICTED = "ACCOUNT_RESTRICTED"
    BVN_NOT_FOUND = "BVN_NOT_FOUND"
    KYC_UNAVAILABLE = "KYC_UNAVAILABLE"
    BVN_NO_PHONE = "BVN_NO_PHONE"
    REGISTRATION_EXPIRED = "REGISTRATION_EXPIRED"
    SELFIE_UNREADABLE = "SELFIE_UNREADABLE"
    SELFIE_NO_MATCH = "SELFIE_NO_MATCH"
    LIVENESS_FAILED = "LIVENESS_FAILED"
    SELFIE_ATTEMPTS_EXCEEDED = "SELFIE_ATTEMPTS_EXCEEDED"  # no longer sent; see SELFIE_COOLDOWN
    SELFIE_COOLDOWN = "SELFIE_COOLDOWN"
    SMS_UNAVAILABLE = "SMS_UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"

    # PINs and devices
    LOGIN_PIN_NOT_SET = "LOGIN_PIN_NOT_SET"
    PIN_INVALID = "PIN_INVALID"
    PIN_ATTEMPTS_EXCEEDED = "PIN_ATTEMPTS_EXCEEDED"
    PIN_TOO_WEAK = "PIN_TOO_WEAK"
    PIN_ALREADY_SET = "PIN_ALREADY_SET"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    BVN_MISMATCH = "BVN_MISMATCH"
    DEVICE_NOT_TRUSTED = "DEVICE_NOT_TRUSTED"
    APPROVAL_NOT_FOUND = "APPROVAL_NOT_FOUND"
    APPROVAL_NOT_ACTIVE = "APPROVAL_NOT_ACTIVE"
    APPROVAL_CODE_INVALID = "APPROVAL_CODE_INVALID"

    # Client contract
    APP_UPDATE_REQUIRED = "APP_UPDATE_REQUIRED"
    MAINTENANCE_MODE = "MAINTENANCE_MODE"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    IDEMPOTENCY_IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"

    # Money
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    PAYOUT_ACCOUNT_REQUIRED = "PAYOUT_ACCOUNT_REQUIRED"
    PAYMENT_PROVIDER_ERROR = "PAYMENT_PROVIDER_ERROR"
    BANK_ACCOUNT_UNVERIFIED = "BANK_ACCOUNT_UNVERIFIED"
    TRANSACTION_PIN_NOT_SET = "TRANSACTION_PIN_NOT_SET"
    TRANSACTION_PIN_INVALID = "TRANSACTION_PIN_INVALID"
    TRANSACTION_PIN_LOCKED = "TRANSACTION_PIN_LOCKED"
    TRANSFERS_ON_HOLD = "TRANSFERS_ON_HOLD"
    DEMO_ACCOUNT = "DEMO_ACCOUNT"

    # Loans
    APPLICATION_INCOMPLETE = "APPLICATION_INCOMPLETE"
    APPLICATION_NOT_EDITABLE = "APPLICATION_NOT_EDITABLE"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    DOCUMENT_TYPE_NOT_ALLOWED = "DOCUMENT_TYPE_NOT_ALLOWED"
    DOCUMENT_INVALID = "DOCUMENT_INVALID"
    DOCUMENTS_NOT_VERIFIED = "DOCUMENTS_NOT_VERIFIED"
    LOAN_NOT_REPAYABLE = "LOAN_NOT_REPAYABLE"
    OFFER_NOT_AVAILABLE = "OFFER_NOT_AVAILABLE"  # not approved yet, or already paid out / closed
    OFFER_CHANGED = "OFFER_CHANGED"  # terms changed since the customer loaded them
    OFFER_NOT_ACCEPTED = "OFFER_NOT_ACCEPTED"  # staff tried to disburse before the customer accepted

    # Legal
    LEGAL_VERSION_OUTDATED = "LEGAL_VERSION_OUTDATED"


class AppError(HTTPException):
    """
    HTTPException that carries a stable machine-readable code.

    Subclasses FastAPI's HTTPException so existing ``except HTTPException``
    handlers and ``pytest.raises(HTTPException)`` keep catching it.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        errors: list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.errors = errors


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _body(
    request: Request, detail: Any, code: str, errors: list[Any] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"detail": detail, "code": code}
    if errors:
        body["errors"] = errors
    rid = _request_id(request)
    if rid:
        body["request_id"] = rid
    return body


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = getattr(exc, "code", None) or STATUS_CODES.get(exc.status_code, "ERROR")
    errors = getattr(exc, "errors", None)
    detail: Any = exc.detail
    # Legacy shape: detail={"message": ..., "errors": [...]}
    if isinstance(detail, dict):
        errors = errors or detail.get("errors")
        detail = detail.get("message") or detail.get("detail") or "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=_body(request, detail, code, errors),
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Keep FastAPI's list in ``detail`` — the admin portal already renders it.
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_body(request, errors, STATUS_CODES[422]),
    )


async def redis_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    # Redis down or unconfigured: a clear, retryable 503 instead of a generic 500.
    logger.error(
        "redis_unavailable",
        path=request.url.path,
        method=request.method,
        error=f"{type(exc).__name__}: {exc}",
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=_body(
            request,
            "We can't complete this right now. Please try again in a few minutes.",
            STATUS_CODES[503],
        ),
        headers={"Retry-After": "30"},
    )


_DB_CONNECT_ERRORS = (OSError, TimeoutError, ConnectionError)


def _database_unreachable(exc: BaseException) -> bool:
    """True when the error is a failure to reach Postgres, not a bug in a query."""
    from sqlalchemy.exc import InterfaceError, OperationalError

    if isinstance(exc, (OperationalError, InterfaceError)) and getattr(exc, "connection_invalidated", False):
        return True
    if type(exc).__name__ in {"CannotConnectNowError", "ConnectionDoesNotExistError", "TooManyConnectionsError"}:
        return True
    if isinstance(exc, _DB_CONNECT_ERRORS) or isinstance(exc, OperationalError):
        # Only when raised while the pool was opening a connection (not file I/O etc.).
        tb = exc.__traceback__
        while tb is not None:
            path = tb.tb_frame.f_code.co_filename.replace("\\", "/")
            if "sqlalchemy/pool" in path or "asyncpg/connect_utils" in path:
                return True
            tb = tb.tb_next
    return False


async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Registered for connection-type errors so an outage is answered here, where
    Starlette does not re-raise (the catch-all Exception handler always re-raises,
    which printed every failure twice). Anything else is passed on unchanged.
    """
    if not _database_unreachable(exc):
        raise exc
    # An outage, not a bug: one log line and a retryable 503, no traceback flood.
    from app.core.database import database_host

    logger.error(
        "database_unavailable",
        path=request.url.path,
        method=request.method,
        db_host=database_host(),
        error=f"{type(exc).__name__}: {exc}"[:300],
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=_body(
            request,
            "We can't complete this right now. Please try again in a few minutes.",
            STATUS_CODES[503],
        ),
        headers={"Retry-After": "30"},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", path=request.url.path, method=request.method)
    from app.core.observability import capture_exception

    capture_exception(exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_body(request, "An unexpected error occurred.", STATUS_CODES[500]),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(RedisConnectionError, redis_unavailable_handler)
    app.add_exception_handler(RedisTimeoutError, redis_unavailable_handler)
    # Postgres unreachable (refused, timed out, dropped): see database_unavailable_handler.
    from sqlalchemy.exc import InterfaceError, OperationalError

    for exc_type in (OSError, OperationalError, InterfaceError):
        app.add_exception_handler(exc_type, database_unavailable_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
