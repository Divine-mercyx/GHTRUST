"""
Live support chat over a WebSocket: messages arrive instantly, with typing indicators and
read receipts. The HTTP routes in router.py stay as the fallback; they publish the same events.

Endpoints: /api/v1/ws/support (customers) and /api/v1/ws/admin/support (staff with support:read).
Browsers can't set headers on a WebSocket, so the access token goes in the first message.

Protocol (JSON frames):
  client → {"type": "auth", "token": "<access token>"}           first, within 10 seconds
  server → {"type": "ready"}
  client → {"type": "send", "ticket_id", "body", "client_id"}
  server → {"type": "ack", "client_id", "ticket_id", "message"}  saved; or {"type": "error", "client_id", ...}
  client → {"type": "typing", "ticket_id"}
  client → {"type": "read", "ticket_id"}
  client → {"type": "ping"}                                       server → {"type": "pong"}
  server → {"type": "message", "ticket_id", "status", "message"}  the other side wrote
  server → {"type": "typing", "ticket_id", "author"}
  server → {"type": "read", "ticket_id", "by", "at"}              the other side read up to now
  server → {"type": "ticket", "ticket_id", "status"}              staff changed the status

The API runs several worker processes, so events go through Redis pub/sub (channel
support:events) to reach sockets held by other workers. Each worker also delivers its own
events directly, which keeps chat working on one worker if Redis pub/sub is unavailable.
"""

import asyncio
import json
import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.core.rate_limit import RateLimitExceeded
from app.core.redis import redis_for_scope
from app.core.security import TOKEN_TYPE_CUSTOMER, TOKEN_TYPE_STAFF, TokenError, decode_access_token

logger = structlog.get_logger()

router = APIRouter(tags=["Support"])

CHANNEL = "support:events"
AUTH_TIMEOUT_SECONDS = 10
TYPING_EVERY_SECONDS = 2.0


class _Conn:
    def __init__(self, ws: WebSocket, role: str, subject_id: str, session_id: str):
        self.ws = ws
        self.role = role  # customer | staff
        self.subject_id = subject_id
        self.session_id = session_id
        self.last_typing = 0.0
        self.lock = asyncio.Lock()

    async def send(self, data: dict) -> None:
        async with self.lock:
            await self.ws.send_text(json.dumps(data, default=str))


class Hub:
    def __init__(self) -> None:
        self.origin = uuid.uuid4().hex
        self.customers: dict[str, set[_Conn]] = {}
        self.staff: set[_Conn] = set()
        self._listener: asyncio.Task | None = None

    # ── Connections ─────────────────────────────────────────────────────────

    def add(self, conn: _Conn, redis) -> None:
        if conn.role == "staff":
            self.staff.add(conn)
        else:
            self.customers.setdefault(conn.subject_id, set()).add(conn)
        if self._listener is None or self._listener.done():
            self._listener = asyncio.create_task(self._listen(redis))

    def remove(self, conn: _Conn) -> None:
        self.staff.discard(conn)
        conns = self.customers.get(conn.subject_id)
        if conns is not None:
            conns.discard(conn)
            if not conns:
                del self.customers[conn.subject_id]
        if not self.staff and not self.customers and self._listener is not None:
            self._listener.cancel()
            self._listener = None

    # ── Events ──────────────────────────────────────────────────────────────

    async def publish(self, redis, event: dict) -> None:
        """Deliver here and tell the other worker processes. Never raises."""
        await self.deliver(event)
        try:
            await redis.publish(CHANNEL, json.dumps({**event, "_origin": self.origin}, default=str))
        except Exception as exc:  # pub/sub down: this worker's sockets still got it
            logger.warning("support_publish_failed", error=str(exc))

    async def deliver(self, event: dict) -> None:
        targets: list[tuple[_Conn, dict]] = []
        customer_id = event.get("customer_id")
        skip = event.pop("_skip", None)
        for conn in self.customers.get(customer_id, ()):  # type: ignore[arg-type]
            targets.append((conn, self._view(event, "customer")))
        for conn in self.staff:
            targets.append((conn, self._view(event, "staff")))
        for conn, data in targets:
            if data is None or conn.session_id == skip:
                continue
            try:
                await conn.send(data)
            except Exception:
                pass  # the socket's own loop notices and cleans up

    @staticmethod
    def _view(event: dict, role: str) -> dict | None:
        kind = event.get("type")
        if kind == "typing" and event.get("author") == role:
            return None  # your own typing isn't news
        if kind == "read" and event.get("by") == role:
            return None
        out = {k: v for k, v in event.items() if k not in {"views", "customer_id", "_origin", "_skip"}}
        if role == "staff":
            out["customer_id"] = event.get("customer_id")
        if kind == "message":
            out["message"] = event["views"][role]
        return out

    async def _listen(self, redis) -> None:
        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(CHANNEL)
        except Exception as exc:
            logger.warning("support_subscribe_failed", error=str(exc))
            return
        try:
            async for item in pubsub.listen():
                if item.get("type") != "message":
                    continue
                try:
                    event = json.loads(item["data"])
                except (TypeError, ValueError):
                    continue
                if event.get("_origin") == self.origin:
                    continue
                await self.deliver(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("support_listener_stopped", error=str(exc))
        finally:
            try:
                await pubsub.unsubscribe(CHANNEL)
                await pubsub.aclose()
            except Exception:
                pass


hub = Hub()


# ── Sign-in ──────────────────────────────────────────────────────────────────


async def _authenticate(ws: WebSocket, role: str) -> tuple[str, str] | None:
    """(subject id, session id) from the first frame, or None (socket closed)."""
    from app.modules.admin.models import Staff, StaffStatus
    from app.modules.admin.permissions import SUPPORT_READ
    from app.modules.auth.models import SubjectType
    from app.modules.auth.session_service import SessionService
    from app.modules.users.models import Customer, CustomerStatus

    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_SECONDS))
        token = str(first.get("token") or "") if first.get("type") == "auth" else ""
        claims = decode_access_token(token, expected_typ=TOKEN_TYPE_STAFF if role == "staff" else TOKEN_TYPE_CUSTOMER)
    except (asyncio.TimeoutError, ValueError, TokenError, AttributeError):
        await ws.close(code=4401, reason="Sign in again")
        return None
    except WebSocketDisconnect:
        return None

    async with _session(ws)() as db:
        subject = SubjectType.STAFF if role == "staff" else SubjectType.CUSTOMER
        ok = await SessionService(db).is_active(claims.sid, subject_type=subject, subject_id=claims.sub)
        if ok and role == "staff":
            staff = await db.scalar(
                select(Staff)
                .options(selectinload(Staff.role))
                .where(Staff.id == claims.sub, Staff.status == StaffStatus.ACTIVE)
            )
            ok = staff is not None and staff.has_permission(SUPPORT_READ)
        elif ok:
            ok = bool(
                await db.scalar(
                    select(Customer.id).where(Customer.id == claims.sub, Customer.status == CustomerStatus.ACTIVE)
                )
            )
    if not ok:
        await ws.close(code=4401, reason="Sign in again")
        return None
    return claims.sub, claims.sid


def _session(ws: WebSocket):
    """The app's session factory, or the test override of get_db."""
    from app.core.database import get_db

    override = ws.app.dependency_overrides.get(get_db)
    if override is None:
        return AsyncSessionLocal

    class _Override:
        async def __aenter__(self):
            self._gen = override()
            return await self._gen.__anext__()

        async def __aexit__(self, *exc):
            try:
                await self._gen.__anext__()
            except StopAsyncIteration:
                pass

    return _Override


# ── Actions ──────────────────────────────────────────────────────────────────


async def _ticket(db, conn: _Conn, ticket_id: str):
    from app.modules.support.models import SupportTicket

    query = select(SupportTicket).where(SupportTicket.id == str(ticket_id)[:36])
    if conn.role == "customer":
        query = query.where(SupportTicket.customer_id == conn.subject_id)
    return await db.scalar(query)


async def _handle(conn: _Conn, frame: dict, redis, ws: WebSocket) -> None:
    from app.modules.admin.models import Staff
    from app.modules.admin.permissions import SUPPORT_RESPOND
    from app.modules.auth.models import SubjectType
    from app.modules.auth.session_service import SessionService
    from app.modules.support import router as support

    kind = frame.get("type")
    if kind == "ping":
        await conn.send({"type": "pong"})
        return
    ticket_id = frame.get("ticket_id")
    if kind not in {"send", "typing", "read"} or not ticket_id:
        return

    if kind == "typing":
        now = time.monotonic()
        if now - conn.last_typing < TYPING_EVERY_SECONDS:
            return
        conn.last_typing = now

    async with _session(ws)() as db:
        ticket = await _ticket(db, conn, ticket_id)
        if ticket is None:
            if kind == "send":
                await conn.send({"type": "error", "client_id": frame.get("client_id"), "code": "NOT_FOUND"})
            return

        if kind == "typing":
            await hub.publish(
                redis,
                {
                    "type": "typing",
                    "ticket_id": ticket.id,
                    "customer_id": ticket.customer_id,
                    "author": conn.role,
                    "_skip": conn.session_id,
                },
            )
            return

        if kind == "read":
            at = await support.mark_read(db, ticket, conn.role)
            await db.commit()
            if at:
                await support.publish_read(redis, ticket, conn.role, at)
            return

        # send
        client_id = frame.get("client_id")
        subject = SubjectType.STAFF if conn.role == "staff" else SubjectType.CUSTOMER
        if not await SessionService(db).is_active(conn.session_id, subject_type=subject, subject_id=conn.subject_id):
            await ws.close(code=4401, reason="Sign in again")
            return
        staff = None
        try:
            if conn.role == "staff":
                staff = await db.scalar(
                    select(Staff).options(selectinload(Staff.role)).where(Staff.id == conn.subject_id)
                )
                if staff is None or not staff.has_permission(SUPPORT_RESPOND):
                    await conn.send({"type": "error", "client_id": client_id, "code": "PERMISSION_DENIED"})
                    return
                message = await support.add_staff_reply(db, ticket, staff, str(frame.get("body") or ""))
            else:
                message = await support.add_customer_message(db, ticket, str(frame.get("body") or ""), redis)
            await db.commit()
        except AppError as exc:
            await db.rollback()
            await conn.send({"type": "error", "client_id": client_id, "code": exc.code, "message": exc.detail})
            return
        except RateLimitExceeded:
            await db.rollback()
            await conn.send({"type": "error", "client_id": client_id, "code": "RATE_LIMITED"})
            return

        views = support.message_views(message, staff.full_name if staff else None)
        await conn.send(
            {"type": "ack", "client_id": client_id, "ticket_id": ticket.id, "status": ticket.status, "message": views[conn.role]}
        )
        await hub.publish(
            redis,
            {
                "type": "message",
                "ticket_id": ticket.id,
                "customer_id": ticket.customer_id,
                "status": ticket.status,
                "views": views,
                "_skip": conn.session_id,  # the sender has the ack
            },
        )


async def _serve(ws: WebSocket, role: str) -> None:
    await ws.accept()
    who = await _authenticate(ws, role)
    if who is None:
        return
    redis = await redis_for_scope(ws.scope)
    conn = _Conn(ws, role, *who)
    hub.add(conn, redis)
    await conn.send({"type": "ready"})
    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) > 8192:
                continue
            try:
                frame: Any = json.loads(raw)
            except ValueError:
                continue
            if isinstance(frame, dict):
                await _handle(conn, frame, redis, ws)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("support_socket_failed", role=role)
    finally:
        hub.remove(conn)


@router.websocket("/ws/support")
async def customer_socket(ws: WebSocket) -> None:
    await _serve(ws, "customer")


@router.websocket("/ws/admin/support")
async def staff_socket(ws: WebSocket) -> None:
    await _serve(ws, "staff")
