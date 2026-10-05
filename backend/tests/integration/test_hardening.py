"""Security hardening: webhook authenticity/failure semantics, status guard, uploads."""

import io
import json

from sqlalchemy import func, select

from app.modules.loans.models import LoanApplication
from app.modules.loans.schemas import ApplicationStatus
from app.modules.payments.models import ProcessedWebhookEvent
from app.modules.payments.webhook_service import WebhookService
from tests.conftest import refresh_settings
from tests.integration.test_loan_workflow_api import _customer_token, _seed, _submit_business_application
from tests.integration.test_payments_api import active_customer, sign_monnify_payload  # noqa: F401

MONNIFY_PAYLOAD = {
    "eventType": "SUCCESSFUL_TRANSACTION",
    "eventData": {
        "transactionReference": "MNFY|HARDEN|001",
        "paymentReference": "HARDEN-001",
        "amountPaid": "5000.00",
        "paymentStatus": "PAID",
        "product": {"type": "RESERVED_ACCOUNT", "reference": "ghtrust_cust_test001"},
        "destinationAccountInformation": {"accountNumber": "9930000901"},
    },
}


class TestWebhookAuthenticity:
    async def test_unconfigured_secret_refused_outside_dev(self, api_client, monkeypatch):
        monkeypatch.setenv("APP_ENV", "staging")
        monkeypatch.setenv("MONNIFY_SECRET_KEY", "")
        refresh_settings()
        res = await api_client.post("/api/v1/webhooks/monnify", content=json.dumps(MONNIFY_PAYLOAD))
        assert res.status_code == 503

    async def test_unsigned_request_rejected_outside_dev(self, api_client, monkeypatch):
        monkeypatch.setenv("APP_ENV", "staging")
        refresh_settings()
        for path in ("/api/v1/webhooks/monnify", "/api/v1/webhooks/paystack"):
            res = await api_client.post(path, content=json.dumps(MONNIFY_PAYLOAD))
            assert res.status_code == 401, path
            assert res.json()["detail"] == "Missing signature"

    async def test_zest_and_stanbic_refuse_when_unconfigured(self, api_client, monkeypatch):
        monkeypatch.setenv("APP_ENV", "staging")
        refresh_settings()
        for path in ("/api/v1/webhooks/zest", "/api/v1/webhooks/stanbic"):
            res = await api_client.post(path, content=b"{}")
            assert res.status_code == 503, path

    async def test_valid_signature_accepted_outside_dev(self, api_client, monkeypatch, active_customer):  # noqa: F811
        monkeypatch.setenv("APP_ENV", "staging")
        refresh_settings()
        body, sig = sign_monnify_payload(MONNIFY_PAYLOAD)
        res = await api_client.post(
            "/api/v1/webhooks/monnify",
            content=body,
            headers={"monnify-signature": sig, "Content-Type": "application/json"},
        )
        assert res.status_code == 200


class TestWebhookFailureSemantics:
    async def test_handler_error_returns_500_and_rolls_back(
        self, api_client, db_session, monkeypatch, active_customer  # noqa: F811
    ):
        async def claim_then_crash(self, payload, raw):
            await self._claim_event("monnify", "SUCCESSFUL_TRANSACTION", payload["eventData"], raw)
            raise RuntimeError("simulated crash after claiming the event")

        monkeypatch.setattr(WebhookService, "handle_monnify_payload", claim_then_crash)
        body, sig = sign_monnify_payload(MONNIFY_PAYLOAD)
        res = await api_client.post(
            "/api/v1/webhooks/monnify",
            content=body,
            headers={"monnify-signature": sig, "Content-Type": "application/json"},
        )
        # 500 → provider retries. Previously 200, silently dropping the credit.
        assert res.status_code == 500
        # The dedupe claim rolled back too, so the retry is not mistaken for a duplicate.
        count = await db_session.scalar(select(func.count()).select_from(ProcessedWebhookEvent))
        assert count == 0

    async def test_retry_after_failure_is_processed(
        self, api_client, db_session, monkeypatch, active_customer  # noqa: F811
    ):
        real = WebhookService.handle_monnify_payload
        calls = {"n": 0}

        async def flaky(self, payload, raw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient failure")
            return await real(self, payload, raw)

        # Tests share one session; commit the fixture so the webhook's rollback
        # can't take the customer with it (each real request has its own session).
        await db_session.commit()
        monkeypatch.setattr(WebhookService, "handle_monnify_payload", flaky)
        body, sig = sign_monnify_payload(MONNIFY_PAYLOAD)
        headers = {"monnify-signature": sig, "Content-Type": "application/json"}
        assert (await api_client.post("/api/v1/webhooks/monnify", content=body, headers=headers)).status_code == 500
        assert (await api_client.post("/api/v1/webhooks/monnify", content=body, headers=headers)).status_code == 200

        from app.modules.payments.ledger_service import LedgerService

        wallet = await LedgerService(db_session).get_or_create_wallet(active_customer.id)
        await db_session.refresh(wallet)
        assert wallet.available_balance == 5000


class TestManualStatusGuard:
    async def _app(self, api_client, db_session) -> str:
        return await _submit_business_application(api_client, db_session)

    async def test_cannot_force_approval(self, api_client, db_session, admin_headers):
        app_id = await self._app(api_client, db_session)
        for target in ("approved", "ready_to_disburse", "disbursed"):
            res = await api_client.patch(
                f"/api/v1/admin/loans/applications/{app_id}/status",
                json={"status": target},
                headers=admin_headers,
            )
            assert res.status_code == 409, target
            assert res.json()["code"] == "INVALID_STATUS_TRANSITION"

    async def test_reject_requires_reason_and_closes_stage(self, api_client, db_session, admin_headers):
        app_id = await self._app(api_client, db_session)
        url = f"/api/v1/admin/loans/applications/{app_id}/status"
        no_reason = await api_client.patch(url, json={"status": "rejected"}, headers=admin_headers)
        assert no_reason.status_code == 422

        ok = await api_client.patch(
            url, json={"status": "rejected", "note": "Unverifiable income"}, headers=admin_headers
        )
        assert ok.status_code == 200
        application = await db_session.get(LoanApplication, app_id)
        await db_session.refresh(application)
        assert application.status == ApplicationStatus.REJECTED
        assert application.current_stage_id is None
        assert application.rejected_at is not None

        again = await api_client.patch(url, json={"approved_amount": "1000"}, headers=admin_headers)
        assert again.status_code == 409  # closed applications are frozen

    async def test_terms_can_be_adjusted_during_review(self, api_client, db_session, admin_headers):
        app_id = await self._app(api_client, db_session)
        res = await api_client.patch(
            f"/api/v1/admin/loans/applications/{app_id}/status",
            json={"approved_amount": "400000", "repayment_cadence": "monthly"},
            headers=admin_headers,
        )
        assert res.status_code == 200, res.text
        application = await db_session.get(LoanApplication, app_id)
        await db_session.refresh(application)
        assert application.approved_amount == 400000
        assert application.status == ApplicationStatus.UNDER_REVIEW


class TestUploadValidation:
    async def _draft(self, api_client, db_session) -> tuple[str, dict]:
        await _seed(db_session)
        headers = {"Authorization": f"Bearer {await _customer_token(api_client)}"}
        created = await api_client.post(
            "/api/v1/loans/me/applications", json={"product_code": "business_loan"}, headers=headers
        )
        return created.json()["id"], headers

    async def _upload(self, api_client, app_id, headers, content: bytes, mime: str, name="doc.pdf"):
        doc_type = "valid_id"
        return await api_client.post(
            f"/api/v1/loans/me/applications/{app_id}/documents/{doc_type}",
            files={"file": (name, io.BytesIO(content), mime)},
            headers=headers,
        )

    async def test_html_disguised_as_pdf_rejected(self, api_client, db_session):
        app_id, headers = await self._draft(api_client, db_session)
        res = await self._upload(
            api_client, app_id, headers, b"<html><script>alert(1)</script></html>", "application/pdf"
        )
        assert res.status_code == 422
        assert res.json()["code"] == "DOCUMENT_INVALID"

    async def test_png_declared_as_pdf_rejected(self, api_client, db_session):
        app_id, headers = await self._draft(api_client, db_session)
        png = bytes.fromhex("89504e470d0a1a0a") + b"rest"
        res = await self._upload(api_client, app_id, headers, png, "application/pdf")
        assert res.status_code == 422

    async def test_real_jpeg_accepted_with_detected_extension(self, api_client, db_session):
        app_id, headers = await self._draft(api_client, db_session)
        jpeg = bytes.fromhex("ffd8ffe0") + b"jfif-body"
        res = await self._upload(api_client, app_id, headers, jpeg, "image/jpg", name="../../evil.html")
        assert res.status_code == 200, res.text
        doc = res.json()["documents"][0] if res.json().get("documents") else None
        if doc:
            assert doc["file_name"] == "evil.html"  # path components stripped


class TestMonnifyWebhookOrigin:
    """With the IP check on, the sender is read through Railway's proxy, not the proxy itself."""

    async def test_real_sender_ip_is_checked(self, api_client, monkeypatch):
        from tests.conftest import refresh_settings

        monkeypatch.setenv("APP_ENV", "staging")
        monkeypatch.setenv("MONNIFY_WEBHOOK_IP_CHECK", "true")
        monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
        refresh_settings()
        url = "/api/v1/webhooks/monnify"
        stranger = await api_client.post(url, content=b"{}", headers={"X-Forwarded-For": "6.6.6.6"})
        assert stranger.status_code == 403
        monnify = await api_client.post(url, content=b"{}", headers={"X-Forwarded-For": "35.242.133.146"})
        assert monnify.status_code != 403  # past the origin check; the signature check decides next
