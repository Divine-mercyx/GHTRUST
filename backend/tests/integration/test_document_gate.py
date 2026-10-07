"""Loans cannot be finally approved or paid out until every required document is verified."""

from tests.integration.test_disbursement_lifecycle import (
    accept_loan_offer,
    approved_application,
    disburse,
    submitted_application,
    verify_all_documents,
)


async def _approve(api_client, app_id, admin_headers):
    return await api_client.post(
        f"/api/v1/admin/loans/applications/{app_id}/stage-action",
        json={"action": "approved", "note": "ok"},
        headers=admin_headers,
    )


async def test_final_approval_blocked_until_documents_verified(
    api_client, db_session, admin_headers
):
    app_id = await submitted_application(api_client, db_session)

    # Earlier stages are not gated; the credit stage sends the offer, which the customer accepts.
    for _ in range(3):
        status = (
            await api_client.get(f"/api/v1/admin/loans/applications/{app_id}", headers=admin_headers)
        ).json()["status"]
        if status == "offer_sent":
            await accept_loan_offer(api_client, app_id)
        assert (await _approve(api_client, app_id, admin_headers)).status_code == 200

    blocked = await _approve(api_client, app_id, admin_headers)
    assert blocked.status_code == 409
    body = blocked.json()
    assert body["code"] == "DOCUMENTS_NOT_VERIFIED"
    assert "Valid means of identification" in body["detail"]

    detail = (
        await api_client.get(
            f"/api/v1/admin/loans/applications/{app_id}", headers=admin_headers
        )
    ).json()
    assert detail["status"] == "under_review"  # the refused approval changed nothing

    await verify_all_documents(api_client, app_id, admin_headers)
    approved = await _approve(api_client, app_id, admin_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


async def test_disbursement_blocked_if_document_rejected_after_approval(
    api_client, db_session, admin_headers
):
    app_id = await approved_application(api_client, db_session, admin_headers)
    await verify_all_documents(api_client, app_id, admin_headers, status="rejected")

    rail = await disburse(api_client, app_id, admin_headers)
    assert rail.status_code == 409
    assert rail.json()["code"] == "DOCUMENTS_NOT_VERIFIED"

    manual = await api_client.post(
        f"/api/v1/admin/loans/applications/{app_id}/disbursements/manual",
        json={"external_reference": "BANKAPP-1"},
        headers=admin_headers,
    )
    assert manual.status_code == 409
    assert manual.json()["code"] == "DOCUMENTS_NOT_VERIFIED"
