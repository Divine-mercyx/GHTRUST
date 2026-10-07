"""Post-credit customer offer gate pauses workflow until accept or reject."""

from tests.integration.test_disbursement_lifecycle import accept_loan_offer, submitted_application, verify_all_documents
from tests.integration.test_loan_workflow_api import _login


async def test_credit_approval_sends_offer_and_resumes_on_accept(api_client, db_session, admin_headers):
    app_id = await submitted_application(api_client, db_session)
    await verify_all_documents(api_client, app_id, admin_headers)

    # Document verification
    res = await api_client.post(
        f"/api/v1/admin/loans/applications/{app_id}/stage-action",
        json={"action": "approved", "note": "docs ok"},
        headers=admin_headers,
    )
    assert res.status_code == 200

    # Credit assessment → offer to customer
    credit = await api_client.post(
        f"/api/v1/admin/loans/applications/{app_id}/stage-action",
        json={"action": "approved", "note": "credit ok"},
        headers=admin_headers,
    )
    assert credit.status_code == 200
    assert credit.json()["status"] == "offer_sent"

    blocked = await api_client.post(
        f"/api/v1/admin/loans/applications/{app_id}/stage-action",
        json={"action": "approved", "note": "should wait"},
        headers=admin_headers,
    )
    assert blocked.status_code == 409

    customer_headers = {"Authorization": f"Bearer {await _login(api_client)}"}
    offer = await api_client.get(f"/api/v1/loans/me/applications/{app_id}/offer", headers=customer_headers)
    assert offer.status_code == 200

    await accept_loan_offer(api_client, app_id)

    detail = await api_client.get(f"/api/v1/admin/loans/applications/{app_id}", headers=admin_headers)
    assert detail.json()["status"] == "under_review"
    wf = await api_client.get(f"/api/v1/admin/loans/applications/{app_id}/workflow", headers=admin_headers)
    assert wf.json()["current_stage"]["name"] == "Branch approval"


async def test_customer_can_reject_offer(api_client, db_session, admin_headers):
    app_id = await submitted_application(api_client, db_session)
    await verify_all_documents(api_client, app_id, admin_headers)
    for _ in range(2):
        await api_client.post(
            f"/api/v1/admin/loans/applications/{app_id}/stage-action",
            json={"action": "approved", "note": "ok"},
            headers=admin_headers,
        )
    customer_headers = {"Authorization": f"Bearer {await _login(api_client)}"}
    rejected = await api_client.post(
        f"/api/v1/loans/me/applications/{app_id}/offer/reject",
        headers=customer_headers,
    )
    assert rejected.status_code == 204
    detail = await api_client.get(f"/api/v1/admin/loans/applications/{app_id}", headers=admin_headers)
    assert detail.json()["status"] == "under_review"
