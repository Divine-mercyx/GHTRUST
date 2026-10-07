"""Staff can preview the customer repayment schedule before sending the offer."""

from tests.integration.test_disbursement_lifecycle import submitted_application, verify_all_documents


async def test_offer_preview_matches_terms(api_client, db_session, admin_headers):
    app_id = await submitted_application(api_client, db_session)
    await verify_all_documents(api_client, app_id, admin_headers)
    await api_client.patch(
        f"/api/v1/admin/loans/applications/{app_id}/status",
        json={"approved_amount": "500000", "tenure_months": 6, "repayment_cadence": "monthly"},
        headers=admin_headers,
    )
    res = await api_client.get(
        f"/api/v1/admin/loans/applications/{app_id}/offer-preview",
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["principal"] == "500000.00"
    assert body["tenure_months"] == 6
    assert body["installments"] == 6
    assert len(body["schedule"]) == 6
    assert float(body["total_repayable"]) > float(body["principal"])
