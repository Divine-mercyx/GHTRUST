"""Legal documents, recorded acceptance, and the loan offer the customer must accept before payout."""

from sqlalchemy import select

from app.modules.legal.documents import DOCUMENTS
from app.modules.legal.models import LegalAcceptance
from app.modules.loans.models import LoanApplication
from tests.conftest import TEST_TXN_PIN
from tests.integration.test_device_security import _auth, _register
from tests.integration.test_disbursement_lifecycle import (
    _login,
    accept_loan_offer,
    approved_application,
    disburse,
    finish_approval,
    submitted_application,
)

VERSIONS = {slug: d.version for slug, d in DOCUMENTS.items()}


class TestDocuments:
    async def test_public_list_and_document(self, api_client):
        docs = (await api_client.get("/api/v1/legal")).json()
        assert {d["slug"] for d in docs} == {"terms", "privacy"}
        terms = (await api_client.get("/api/v1/legal/terms")).json()
        assert (
            terms["title"] == "Terms of Use" and terms["version"] == VERSIONS["terms"]
        )
        assert len(terms["sections"]) > 5
        assert (await api_client.get("/api/v1/legal/nope")).status_code == 404

    async def test_new_customer_must_accept_then_is_recorded(
        self, api_client, db_session
    ):
        tokens = await _register(api_client)
        me = (await api_client.get("/api/v1/auth/me", headers=_auth(tokens))).json()
        assert me["legal_pending"] == ["terms", "privacy"]

        res = await api_client.post(
            "/api/v1/legal/accept",
            json={"documents": VERSIONS},
            headers={**_auth(tokens), "User-Agent": "GHTrust/1.0"},
        )
        assert res.json() == {"legal_pending": []}
        assert (await api_client.get("/api/v1/auth/me", headers=_auth(tokens))).json()[
            "legal_pending"
        ] == []

        rows = (await db_session.execute(select(LegalAcceptance))).scalars().all()
        assert {(r.document, r.version) for r in rows} == set(VERSIONS.items())
        assert all(r.user_agent == "GHTrust/1.0" and r.device_id for r in rows)

    async def test_old_version_is_refused(self, api_client):
        tokens = await _register(api_client)
        res = await api_client.post(
            "/api/v1/legal/accept",
            json={"documents": {"terms": "2020-01-01"}},
            headers=_auth(tokens),
        )
        assert res.status_code == 409 and res.json()["code"] == "LEGAL_VERSION_OUTDATED"


class TestLoanOffer:
    async def test_no_offer_before_approval(self, api_client, db_session):
        app_id = await submitted_application(api_client, db_session)
        headers = {"Authorization": f"Bearer {await _login(api_client)}"}
        res = await api_client.get(
            f"/api/v1/loans/me/applications/{app_id}/offer", headers=headers
        )
        assert res.status_code == 409 and res.json()["code"] == "OFFER_NOT_AVAILABLE"

    async def test_offer_shows_key_facts(self, api_client, db_session, admin_headers):
        app_id = await approved_application(
            api_client, db_session, admin_headers, accept_offer=False
        )
        headers = {"Authorization": f"Bearer {await _login(api_client)}"}
        offer = (
            await api_client.get(
                f"/api/v1/loans/me/applications/{app_id}/offer", headers=headers
            )
        ).json()
        # 500,000 at 8%/month flat over 6 months, 3% processing fee.
        assert offer["principal"] == "500000.00"
        assert offer["total_interest"] == "240000.00"
        assert offer["total_repayable"] == "740000.00"
        assert offer["processing_fee"] == "15000.00"
        assert offer["total_cost_of_credit"] == "255000.00"
        assert len(offer["schedule"]) == offer["installments"] == 6
        assert offer["payout_account_masked"] == "•••• 6789"
        assert offer["payout_bank"] == "GTBank"
        assert offer["accepted_at"] is None and len(offer["agreement"]) >= 5

    async def test_payout_waits_for_acceptance(
        self, api_client, db_session, admin_headers
    ):
        app_id = await approved_application(
            api_client, db_session, admin_headers, accept_offer=False
        )
        # The workflow is waiting for the customer: nothing can be paid out yet.
        blocked = await disburse(api_client, app_id, admin_headers)
        assert blocked.status_code == 409

        accepted = await accept_loan_offer(api_client, app_id)
        assert accepted["accepted_at"] is not None
        row = (
            await db_session.execute(
                select(LegalAcceptance).where(
                    LegalAcceptance.document == "loan_agreement"
                )
            )
        ).scalar_one()
        assert row.application_id == app_id and row.terms_hash == accepted["terms_hash"]
        await finish_approval(api_client, app_id, admin_headers)
        assert (await disburse(api_client, app_id, admin_headers)).status_code == 200

    async def test_wrong_pin_or_stale_terms_are_refused(
        self, api_client, db_session, admin_headers
    ):
        app_id = await approved_application(
            api_client, db_session, admin_headers, accept_offer=False
        )
        # Create the PIN (and see the offer) through the normal helper path, but don't accept yet.
        headers = {"Authorization": f"Bearer {await _login(api_client)}"}
        from tests.conftest import set_transaction_pin

        await set_transaction_pin(api_client, headers)
        offer = (
            await api_client.get(
                f"/api/v1/loans/me/applications/{app_id}/offer", headers=headers
            )
        ).json()
        url = f"/api/v1/loans/me/applications/{app_id}/offer/accept"

        wrong_pin = await api_client.post(
            url,
            json={"terms_hash": offer["terms_hash"], "transaction_pin": "9999"},
            headers=headers,
        )
        assert wrong_pin.json()["code"] == "TRANSACTION_PIN_INVALID"

        # Staff lower the amount after the customer loaded the offer: the old terms can't be accepted.
        await api_client.patch(
            f"/api/v1/admin/loans/applications/{app_id}/status",
            json={"approved_amount": "300000"},
            headers=admin_headers,
        )
        stale = await api_client.post(
            url,
            json={"terms_hash": offer["terms_hash"], "transaction_pin": TEST_TXN_PIN},
            headers=headers,
        )
        assert stale.status_code == 409 and stale.json()["code"] == "OFFER_CHANGED"

    async def test_changing_terms_after_acceptance_needs_a_new_one(
        self, api_client, db_session, admin_headers
    ):
        app_id = await approved_application(api_client, db_session, admin_headers)
        await api_client.patch(
            f"/api/v1/admin/loans/applications/{app_id}/status",
            json={"tenure_months": 3},
            headers=admin_headers,
        )
        application = await db_session.get(LoanApplication, app_id)
        await db_session.refresh(application)
        assert application.offer_accepted_at is None
        blocked = await disburse(api_client, app_id, admin_headers)
        assert blocked.json()["code"] == "OFFER_NOT_ACCEPTED"
