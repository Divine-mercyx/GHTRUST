"""Help & support: contact details, FAQs, problem reports and staff replies."""

from sqlalchemy import select

from app.modules.notifications.models import Notification
from tests.integration.test_device_security import PHONE_A, _auth, _register


async def _report(api_client, tokens, **overrides):
    body = {
        "category": "payments",
        "message": "I sent 5,000 at 2pm but my wallet hasn't updated.",
        **overrides,
    }
    return await api_client.post(
        "/api/v1/support/tickets", json=body, headers=_auth(tokens)
    )


class TestHelpCentre:
    async def test_faqs_are_public_and_grouped(self, api_client):
        res = (await api_client.get("/api/v1/support/faqs")).json()
        assert res["topics"][0] == "Getting started"
        assert {f["topic"] for f in res["items"]} <= set(res["topics"])
        assert any(f["id"] == "offer" for f in res["items"])

    async def test_contact_details_come_with_app_config(self, api_client, monkeypatch):
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "support_whatsapp", "+234 801 234 5678")
        config = (
            await api_client.get("/api/v1/app/config?platform=android&version=1.0.0")
        ).json()
        assert config["support"]["whatsapp"] == "2348012345678"
        assert config["support"]["hours"]


class TestTickets:
    async def test_customer_reports_and_sees_their_requests(self, api_client):
        tokens = await _register(api_client)
        res = await _report(
            api_client, tokens, related_type="transaction", related_id="j_abc"
        )
        assert res.status_code == 201, res.text
        ticket = res.json()
        assert ticket["reference"].startswith("GHT-") and len(ticket["reference"]) == 10
        assert ticket["status"] == "open" and ticket["related_id"] == "j_abc"

        mine = (
            await api_client.get("/api/v1/support/tickets", headers=_auth(tokens))
        ).json()
        assert [t["id"] for t in mine] == [ticket["id"]]
        one = await api_client.get(
            f"/api/v1/support/tickets/{ticket['id']}", headers=_auth(tokens)
        )
        assert one.json()["message"].startswith("I sent 5,000")

    async def test_message_must_say_something(self, api_client):
        tokens = await _register(api_client)
        assert (await _report(api_client, tokens, message="help")).status_code == 422
        assert (
            await _report(api_client, tokens, category="complaints")
        ).status_code == 422

    async def test_staff_reply_notifies_the_customer(
        self, api_client, db_session, admin_headers
    ):
        tokens = await _register(api_client, PHONE_A)
        ticket = (await _report(api_client, tokens)).json()

        page = (
            await api_client.get(
                "/api/v1/admin/support/tickets?status=open", headers=admin_headers
            )
        ).json()
        assert (
            page["open"] == 1 and page["items"][0]["reference"] == ticket["reference"]
        )
        assert page["items"][0]["device_name"] == PHONE_A["device_name"]
        assert page["items"][0]["app_version"] == PHONE_A["app_version"]

        replied = await api_client.patch(
            f"/api/v1/admin/support/tickets/{ticket['id']}",
            json={
                "reply": "Found it: the transfer was credited at 2:14pm. Please pull down to refresh."
            },
            headers=admin_headers,
        )
        assert replied.status_code == 200, replied.text
        assert replied.json()["status"] == "in_progress"
        note = (
            await db_session.execute(
                select(Notification).where(Notification.kind == "support_reply")
            )
        ).scalar_one()
        assert (
            note.route == f"/support/{ticket['id']}"
            and ticket["reference"] in note.body
        )

        resolved = await api_client.patch(
            f"/api/v1/admin/support/tickets/{ticket['id']}",
            json={"status": "resolved"},
            headers=admin_headers,
        )
        assert resolved.json()["resolved_at"] is not None
        mine = (
            await api_client.get("/api/v1/support/tickets", headers=_auth(tokens))
        ).json()
        assert mine[0]["status"] == "resolved" and mine[0]["reply"].startswith(
            "Found it"
        )

    async def test_customers_cant_see_each_others_requests(
        self, api_client, db_session
    ):
        tokens = await _register(api_client)
        ticket = (await _report(api_client, tokens)).json()
        from app.modules.support.models import SupportTicket

        row = await db_session.get(SupportTicket, ticket["id"])
        row.customer_id = "00000000-0000-0000-0000-000000000000"
        await db_session.commit()
        res = await api_client.get(
            f"/api/v1/support/tickets/{ticket['id']}", headers=_auth(tokens)
        )
        assert res.status_code == 404

    async def test_staff_endpoints_need_permission(self, api_client):
        tokens = await _register(api_client)
        res = await api_client.get(
            "/api/v1/admin/support/tickets", headers=_auth(tokens)
        )
        assert res.status_code in (401, 403)


class TestConversation:
    async def test_customer_and_staff_keep_writing(self, api_client, admin_headers):
        tokens = await _register(api_client)
        ticket = (await _report(api_client, tokens)).json()
        tid = ticket["id"]
        assert [m["author"] for m in ticket["messages"]] == ["customer"]
        assert ticket["awaiting_reply"] is True

        staff = await api_client.patch(
            f"/api/v1/admin/support/tickets/{tid}", json={"reply": "Checking now."}, headers=admin_headers
        )
        assert staff.status_code == 200, staff.text
        assert staff.json()["messages"][-1]["author_name"] != "GH Trust support"  # staff see who replied

        mine = await api_client.post(
            f"/api/v1/support/tickets/{tid}/messages", json={"body": "Thanks, still waiting."}, headers=_auth(tokens)
        )
        assert mine.status_code == 201, mine.text
        convo = mine.json()
        assert [(m["author"], m["author_name"]) for m in convo["messages"]] == [
            ("customer", "You"),
            ("staff", "GH Trust support"),
            ("customer", "You"),
        ]
        assert convo["awaiting_reply"] is True

        again = await api_client.patch(
            f"/api/v1/admin/support/tickets/{tid}", json={"reply": "Credited."}, headers=admin_headers
        )
        bodies = [m["body"] for m in again.json()["messages"]]
        assert bodies[-2:] == ["Thanks, still waiting.", "Credited."]  # earlier replies are kept

    async def test_replying_reopens_a_resolved_request(self, api_client, admin_headers):
        tokens = await _register(api_client)
        tid = (await _report(api_client, tokens)).json()["id"]
        await api_client.patch(f"/api/v1/admin/support/tickets/{tid}", json={"status": "resolved"}, headers=admin_headers)
        res = await api_client.post(
            f"/api/v1/support/tickets/{tid}/messages", json={"body": "It happened again."}, headers=_auth(tokens)
        )
        assert res.json()["status"] == "open"
        page = (await api_client.get("/api/v1/admin/support/tickets", headers=admin_headers)).json()
        assert page["items"][0]["id"] == tid and page["items"][0]["awaiting_reply"] is True

    async def test_cannot_reply_to_someone_elses_request(self, api_client, admin_headers):
        tokens = await _register(api_client)
        tid = (await _report(api_client, tokens)).json()["id"]
        res = await api_client.post(
            "/api/v1/support/tickets/not-mine/messages", json={"body": "hi"}, headers=_auth(tokens)
        )
        assert res.status_code == 404
        assert (await api_client.post(f"/api/v1/support/tickets/{tid}/messages", json={"body": "x"})).status_code == 401
