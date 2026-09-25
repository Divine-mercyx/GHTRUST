"""Bank picker + account-name check used by the mobile apply flow."""

from app.integrations.payments.schemas import Bank, PaymentRailError
from app.integrations.paystack.client import PaystackClient
from app.modules.payments import banks as banks_module
from tests.integration.test_loan_workflow_api import _customer_token, _seed


async def _customer(api_client, db_session) -> dict:
    await _seed(db_session)
    return {"Authorization": f"Bearer {await _customer_token(api_client)}"}


async def test_banks_require_a_signed_in_customer(api_client):
    assert (await api_client.get("/api/v1/banks")).status_code == 401
    res = await api_client.post(
        "/api/v1/banks/resolve",
        json={"bank_code": "058", "account_number": "0123456789"},
    )
    assert res.status_code == 401


async def test_bank_list_comes_from_the_rail_sorted_and_cached(
    api_client, db_session, fake_redis, monkeypatch
):
    headers = await _customer(api_client, db_session)
    calls = []

    class Rail:
        async def supported_banks(self):
            calls.append(1)
            return [
                Bank(code="057", name="Zenith Bank"),
                Bank(code="044", name="Access Bank"),
                Bank(code="044", name="Access Bank"),
            ]

    monkeypatch.setattr(banks_module, "get_payment_client", lambda: Rail())
    first = await api_client.get("/api/v1/banks", headers=headers)
    assert first.status_code == 200
    assert first.json() == [
        {"code": "044", "name": "Access Bank"},
        {"code": "057", "name": "Zenith Bank"},
    ]

    again = await api_client.get("/api/v1/banks", headers=headers)
    assert again.json() == first.json()
    assert calls == [1], "second request should be served from the cache"


async def test_bank_list_outage_is_a_503_not_a_500(api_client, db_session, monkeypatch):
    headers = await _customer(api_client, db_session)

    class Rail:
        async def supported_banks(self):
            raise PaymentRailError("provider down")

    monkeypatch.setattr(banks_module, "get_payment_client", lambda: Rail())
    res = await api_client.get("/api/v1/banks", headers=headers)
    assert res.status_code == 503
    assert res.json()["code"] == "PAYMENT_PROVIDER_ERROR"


async def test_resolve_returns_the_account_name(api_client, db_session):
    headers = await _customer(api_client, db_session)
    res = await api_client.post(
        "/api/v1/banks/resolve",
        json={"bank_code": "058", "account_number": "0123456789"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["account_number"] == "0123456789" and body["bank_code"] == "058"
    assert body["account_name"]


async def test_resolve_rejects_malformed_numbers(api_client, db_session):
    headers = await _customer(api_client, db_session)
    for payload in (
        {"bank_code": "058", "account_number": "12345"},
        {"bank_code": "058", "account_number": "01234567AB"},
        {"bank_code": "GTB", "account_number": "0123456789"},
    ):
        res = await api_client.post(
            "/api/v1/banks/resolve", json=payload, headers=headers
        )
        assert res.status_code == 422, payload


async def test_unresolvable_account_is_a_clear_422(api_client, db_session, monkeypatch):
    headers = await _customer(api_client, db_session)

    class Rail:
        async def validate_bank_account(self, account_number, bank_code):
            raise PaymentRailError("Account not found", status_code=502)

    monkeypatch.setattr(banks_module, "get_payment_client", lambda: Rail())
    res = await api_client.post(
        "/api/v1/banks/resolve",
        json={"bank_code": "058", "account_number": "0000000000"},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["code"] == "BANK_ACCOUNT_UNVERIFIED"


async def test_resolve_is_rate_limited_per_customer(
    api_client, db_session, monkeypatch
):
    headers = await _customer(api_client, db_session)
    monkeypatch.setattr(banks_module, "RESOLVE_PER_MINUTE", 2)
    payload = {"bank_code": "058", "account_number": "0123456789"}
    codes = [
        (
            await api_client.post(
                "/api/v1/banks/resolve", json=payload, headers=headers
            )
        ).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


async def test_paystack_implements_the_rail_name_enquiry():
    """Disbursement calls rail.validate_bank_account; Paystack used to lack it (AttributeError → 500)."""
    resolved = await PaystackClient().validate_bank_account("0123456789", "058")
    assert resolved.account_name and resolved.bank_code == "058"
    assert len(await PaystackClient().supported_banks()) > 10
