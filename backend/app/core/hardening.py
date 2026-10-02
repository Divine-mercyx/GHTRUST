"""
Production hardening middleware (pure ASGI, so they add no per-request overhead
beyond what they do):

* ``AccessLogMiddleware`` — one structured line per request (status, duration,
  client IP), warning level for 5xx. Replaces uvicorn's unstructured access log.
* ``SecurityHeadersMiddleware`` — nosniff / no framing / no referrer, ``no-store``
  on API responses (financial data must not sit in browser or proxy caches), and
  HSTS in production.
* ``ApiRateLimitMiddleware`` — a per-IP ceiling on every API route, on top of the
  tighter per-endpoint limits on OTP/login/BVN. Webhooks and health checks are
  exempt. Fails open if Redis is unreachable (logged), so an outage of the cache
  tier can't take the whole API down.
* ``BodySizeLimitMiddleware`` — refuses oversized request bodies before they're
  parsed; counts streamed bytes too, so a missing/lying Content-Length can't
  bypass it.
"""

import json
import time

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.rate_limit import get_client_ip
from app.core.redis import redis_for_scope

logger = structlog.get_logger()

_QUIET_PATHS = ("/api/v1/health", "/health")
_RATE_LIMIT_EXEMPT = ("/api/v1/health", "/health", "/api/v1/webhooks")


async def _send_error(send: Send, scope: Scope, status: int, code: str, detail: str, headers=()) -> None:
    body: dict = {"detail": detail, "code": code}
    request_id = scope.get("state", {}).get("request_id")
    if request_id:
        body["request_id"] = request_id
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith(_QUIET_PATHS):
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            status = status_holder["status"]
            fields = {
                "status": status,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                "client_ip": get_client_ip(Request(scope)),
            }
            if status >= 500:
                logger.warning("http_request", **fields)
            else:
                logger.info("http_request", **fields)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope.get("path", "").startswith("/api/")
        hsts = get_settings().is_production

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                ]
                if is_api and b"cache-control" not in present:
                    extra.append((b"cache-control", b"no-store"))
                if hsts:
                    extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                headers.extend(h for h in extra if h[0] not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class ApiRateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = get_settings()
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or scope.get("method") == "OPTIONS"
            or not settings.rate_limits_active
            or not path.startswith("/api/")
            or path.startswith(_RATE_LIMIT_EXEMPT)
        ):
            await self.app(scope, receive, send)
            return

        ip = get_client_ip(Request(scope))
        window = int(time.time() // 60)
        key = f"ratelimit:api:{ip}:{window}"
        try:
            redis = await redis_for_scope(scope)
            async with redis.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, 70)
                count, _ = await pipe.execute()
        except Exception:  # cache tier down: serve the request rather than fail everything
            logger.warning("rate_limit_unavailable", exc_info=True)
            await self.app(scope, receive, send)
            return

        if count > settings.rate_limit_api_per_ip_minute:
            retry_after = 60 - int(time.time()) % 60
            logger.warning("rate_limited", limit_scope="api", client_ip=ip, count=count)
            await _send_error(
                send,
                scope,
                429,
                "RATE_LIMITED",
                "Too many requests. Please slow down and try again shortly.",
                headers=[(b"retry-after", str(retry_after).encode())],
            )
            return
        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS", "DELETE"):
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        content_type = headers.get(b"content-type", b"").decode("latin-1").lower()
        multipart = content_type.startswith("multipart/form-data")
        if multipart:
            limit = settings.max_upload_size_mb * 1024 * 1024 + 64 * 1024  # file + form overhead
        elif scope.get("path", "") == f"{settings.api_v1_prefix}/auth/register/selfie":
            limit = settings.max_selfie_body_mb * 1024 * 1024
        else:
            limit = settings.max_json_body_kb * 1024

        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _send_error(send, scope, 413, "PAYLOAD_TOO_LARGE", f"Request body exceeds {limit // 1024} KB.")
            return
        if multipart:
            # Uploads stream through; the storage layer enforces the per-file limit.
            await self.app(scope, receive, send)
            return

        # JSON/form bodies are small: read them fully (bounded) and replay, so an
        # undeclared or lying Content-Length can't push past the limit.
        chunks: list[bytes] = []
        size = 0
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > limit:
                await _send_error(send, scope, 413, "PAYLOAD_TOO_LARGE", f"Request body exceeds {limit // 1024} KB.")
                return
            chunks.append(body)
            more = message.get("more_body", False)

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
