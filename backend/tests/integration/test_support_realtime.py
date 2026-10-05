"""Live support chat over the WebSocket: sign-in, instant messages with acks, typing, read receipts."""

import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from app.modules.support import realtime
from tests.integration.test_device_security import _auth, _register

_CLOSE = object()


class FakeSocket:
    """Enough of a Starlette WebSocket to drive realtime._serve from a test."""

    def __init__(self, app):
        self.app = app
        self.scope = {"app": app, "type": "websocket"}
        self.sent: list[dict] = []
        self.closed: int | None = None
        self.inbox: asyncio.Queue = asyncio.Queue()

    async def accept(self):
        pass

    async def receive_text(self) -> str:
        frame = await self.inbox.get()
        if frame is _CLOSE:
            raise WebSocketDisconnect()
        return json.dumps(frame)

    async def send_text(self, text: str):
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000, reason: str | None = None):
        self.closed = code
        await self.inbox.put(_CLOSE)

    async def wait_for(self, kind: str, timeout: float = 3.0, **match) -> dict:
        async def look():
            while True:
                for m in self.sent:
                    if m.get("type") == kind and all(m.get(k) == v for k, v in match.items()):
                        return m
                await asyncio.sleep(0.01)

        return await asyncio.wait_for(look(), timeout)


async def _connect(app, role: str, token: str) -> tuple[FakeSocket, asyncio.Task]:
    ws = FakeSocket(app)
    task = asyncio.create_task(realtime._serve(ws, role))
    await ws.inbox.put({"type": "auth", "token": token})
    await ws.wait_for("ready")
    return ws, task


async def _hang_up(*pairs):
    for ws, task in pairs:
        await ws.inbox.put(_CLOSE)
        await asyncio.wait_for(task, 3)


async def _ticket(api_client, tokens) -> dict:
    res = await api_client.post(
        "/api/v1/support/tickets",
        json={"category": "payments", "message": "My transfer hasn't arrived in the wallet."},
        headers=_auth(tokens),
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def app(api_client):
    return api_client._transport.app


async def test_bad_token_is_refused(app):
    ws = FakeSocket(app)
    task = asyncio.create_task(realtime._serve(ws, "customer"))
    await ws.inbox.put({"type": "auth", "token": "nope"})
    await asyncio.wait_for(task, 3)
    assert ws.closed == 4401 and not any(m["type"] == "ready" for m in ws.sent)


async def test_customer_token_cannot_open_the_staff_socket(api_client, app):
    tokens = await _register(api_client)
    ws = FakeSocket(app)
    task = asyncio.create_task(realtime._serve(ws, "staff"))
    await ws.inbox.put({"type": "auth", "token": tokens["access_token"]})
    await asyncio.wait_for(task, 3)
    assert ws.closed == 4401


async def test_live_conversation(api_client, app, admin_token):
    tokens = await _register(api_client)
    ticket = await _ticket(api_client, tokens)
    customer, c_task = await _connect(app, "customer", tokens["access_token"])
    staff, s_task = await _connect(app, "staff", admin_token)
    try:
        # Customer writes: their ack, the staff member sees it at once.
        await customer.inbox.put({"type": "send", "ticket_id": ticket["id"], "body": "Any news?", "client_id": "c1"})
        ack = await customer.wait_for("ack", client_id="c1")
        assert ack["message"]["body"] == "Any news?" and ack["message"]["author_name"] == "You"
        seen = await staff.wait_for("message", ticket_id=ticket["id"])
        assert seen["message"]["author_name"] == "Customer" and seen["customer_id"]
        assert not any(m["type"] == "message" for m in customer.sent)  # no echo of your own message

        # Staff typing and reply; the customer sees "GH Trust support", not the staff name.
        await staff.inbox.put({"type": "typing", "ticket_id": ticket["id"]})
        typing = await customer.wait_for("typing", ticket_id=ticket["id"])
        assert typing["author"] == "staff"
        await staff.inbox.put({"type": "send", "ticket_id": ticket["id"], "body": "Checking now.", "client_id": "s1"})
        await staff.wait_for("ack", client_id="s1")
        reply = await customer.wait_for("message", ticket_id=ticket["id"])
        assert reply["message"]["author_name"] == "GH Trust support" and reply["status"] == "in_progress"

        # Read receipts both ways.
        await customer.inbox.put({"type": "read", "ticket_id": ticket["id"]})
        receipt = await staff.wait_for("read", by="customer")
        assert receipt["at"]
        await staff.inbox.put({"type": "read", "ticket_id": ticket["id"]})
        await customer.wait_for("read", by="staff")

        await customer.inbox.put({"type": "ping"})
        await customer.wait_for("pong")
    finally:
        await _hang_up((customer, c_task), (staff, s_task))

    one = (await api_client.get(f"/api/v1/support/tickets/{ticket['id']}", headers=_auth(tokens))).json()
    bodies = [(m["author"], m["body"], m["read_at"] is not None) for m in one["messages"]]
    assert bodies[-2:] == [("customer", "Any news?", True), ("staff", "Checking now.", True)]


async def test_customers_only_reach_their_own_requests(api_client, app):
    tokens = await _register(api_client)
    customer, task = await _connect(app, "customer", tokens["access_token"])
    try:
        await customer.inbox.put({"type": "send", "ticket_id": "not-theirs", "body": "hi", "client_id": "x"})
        err = await customer.wait_for("error", client_id="x")
        assert err["code"] == "NOT_FOUND"
    finally:
        await _hang_up((customer, task))


async def test_http_reply_reaches_the_socket(api_client, app, admin_headers):
    tokens = await _register(api_client)
    ticket = await _ticket(api_client, tokens)
    customer, task = await _connect(app, "customer", tokens["access_token"])
    try:
        res = await api_client.patch(
            f"/api/v1/admin/support/tickets/{ticket['id']}", json={"reply": "Fixed it."}, headers=admin_headers
        )
        assert res.status_code == 200, res.text
        live = await customer.wait_for("message", ticket_id=ticket["id"])
        assert live["message"]["body"] == "Fixed it."
    finally:
        await _hang_up((customer, task))
