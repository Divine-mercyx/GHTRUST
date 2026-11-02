"""The loan catalogue from GH Trust's website: products, the Business loan's ₦100,000
guarantor-or-collateral rule, and the Cluster / Group and LPO financing applications."""

import pytest

from tests.integration.test_loans_api import _customer_token, _seed_products

FORM = {
    "residential_address": "52 Ijaye Road, Ogba",
    "bank_name": "GTBank",
    "bank_account_name": "Adaeze Okafor",
    "bank_account_number": "0123456789",
    "next_of_kin_name": "Kin Okafor",
    "next_of_kin_phone": "08030000000",
    "next_of_kin_relationship": "Sister",
    "purpose": "Stock",
    "monthly_income": "250000",
    "repayment_period": "3 months",
    "source_of_repayment": "Business income",
}


async def _errors(api_client, headers, code: str, *, amount: str, product_data: dict, guarantors=None) -> list[str]:
    created = await api_client.post("/api/v1/loans/me/applications", json={"product_code": code}, headers=headers)
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]
    body = {
        "step": 5,
        "total_steps": 6,
        "universal_form": {**FORM, "requested_amount": amount},
        "product_data": product_data,
    }
    if guarantors is not None:
        body["guarantors"] = guarantors
    res = await api_client.patch(f"/api/v1/loans/me/applications/{app_id}", json=body, headers=headers)
    assert res.status_code == 200, res.text
    submit = await api_client.post(f"/api/v1/loans/me/applications/{app_id}/submit", headers=headers)
    assert submit.status_code == 422
    return submit.json()["errors"]


@pytest.fixture
async def headers(api_client, db_session):
    await _seed_products(db_session)
    return {"Authorization": f"Bearer {await _customer_token(api_client)}"}


async def test_catalogue_matches_the_website(api_client, headers):
    products = {p["code"]: p for p in (await api_client.get("/api/v1/loans/products")).json()}
    assert {"business_loan", "payday_loan", "study_loan", "lpo_invoice_financing", "cluster_group_loan"} <= set(products)

    lpo = products["lpo_invoice_financing"]
    assert (lpo["interest_method"], lpo["repayment_cadence_options"]) == ("one_off", ["end_of_term"])
    assert float(lpo["interest_rate_pct_monthly"]) == 7 and float(lpo["processing_fee_pct"]) == 3

    cluster = products["cluster_group_loan"]
    assert cluster["repayment_cadence_options"] == ["weekly"]  # first repayment 7 days after payout
    assert cluster["eligibility_rules"]["max_group_members"] == 15
    assert products["business_loan"]["eligibility_rules"]["security_from_amount"] == 100000


BUSINESS = {"years_in_operation": 5, "trade_type": "Provisions"}
SECURITY = "For loans of ₦100,000 and above"


async def test_small_business_loans_need_no_guarantor(api_client, headers):
    errors = await _errors(api_client, headers, "business_loan", amount="80000", product_data=BUSINESS)
    assert not any("guarantor" in e.lower() or SECURITY in e for e in errors), errors
    assert not any("Guarantor valid ID" in e or "Original collateral" in e for e in errors), errors


async def test_from_100k_a_guarantor_or_collateral_is_needed(api_client, headers):
    errors = await _errors(api_client, headers, "business_loan", amount="150000", product_data=BUSINESS)
    assert any(SECURITY in e for e in errors), errors


async def test_guarantor_and_collateral_documents_are_offered_not_each_required(api_client, headers):
    created = await api_client.post(
        "/api/v1/loans/me/applications", json={"product_code": "business_loan"}, headers=headers
    )
    checklist = {d["document_type"]: d["required"] for d in created.json()["document_checklist"]}
    assert checklist["guarantor_id"] is False and checklist["collateral_original"] is False
    assert checklist["cash_flow_proof"] is True


@pytest.mark.parametrize(
    ("product_data", "expected"),
    [
        ({"group_name": "Oyingbo Women", "group_leader_name": "Mama Ada", "group_size": 20}, "between 2 and 15"),
        ({"group_size": 8}, "group's name and its leader"),
    ],
)
async def test_cluster_group_details_are_checked(api_client, headers, product_data, expected):
    errors = await _errors(
        api_client, headers, "cluster_group_loan", amount="300000", product_data=product_data,
        guarantors=[{"full_name": "Group Guarantor"}],
    )
    assert any(expected in e for e in errors), errors


async def test_lpo_needs_the_contract_details(api_client, headers):
    errors = await _errors(
        api_client, headers, "lpo_invoice_financing", amount="2000000", product_data={},
        guarantors=[{"full_name": "Guarantor One"}],
    )
    assert any("issuing organisation" in e for e in errors), errors
    assert any("Verified LPO" in e for e in errors), errors
