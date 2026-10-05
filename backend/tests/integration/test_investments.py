"""Investments: staff plans, investing wallet money with the PIN, payout at maturity, card top-ups."""

import base64
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.investments.models import CustomerInvestment
from app.modules.investments.service import InvestmentService, projected_return
from app.modules.payments.models import CustomerWallet, PaymentTransaction
from tests.conftest import TEST_TXN_PIN, refresh_settings
from tests.integration.test_wallet_history import _customer, _fund

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 600


@pytest.fixture
def investments_on(monkeypatch):
    monkeypatch.setenv("FEATURE_FLAGS", "wallet,investments")
    refresh_settings()


async def _plan(api_client, admin_headers, **overrides) -> dict:
    body = {
        "name": "Test Growth",
        "min_amount": "5000",
        "max_amount": "500000",
        "return_rate": "12",
        "tenure_months": 6,
        "risk": "low",
        "description": "A test plan",
        **overrides,
    }
    res = await api_client.post("/api/v1/admin/investments/plans", json=body, headers=admin_headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _balance(db_session, customer_id: str) -> Decimal:
    wallet = (
        await db_session.execute(select(CustomerWallet).where(CustomerWallet.customer_id == customer_id))
    ).scalar_one()
    await db_session.refresh(wallet)
    return wallet.available_balance


async def _invest(api_client, headers, plan_id: str, amount: str, pin: str = TEST_TXN_PIN):
    return await api_client.post(
        "/api/v1/investments/me",
        json={"plan_id": plan_id, "amount": amount, "transaction_pin": pin},
        headers=headers,
    )


def test_returns_are_simple_interest():
    assert projected_return(Decimal("100000"), Decimal("12"), 6) == Decimal("6000.00")
    assert projected_return(Decimal("50000"), Decimal("14"), 12) == Decimal("7000.00")


class TestStaffPlans:
    async def test_create_edit_and_picture(self, api_client, admin_headers):
        plan = await _plan(api_client, admin_headers)
        assert plan["active_investors"] == 0 and plan["image_url"] is None

        res = await api_client.patch(
            f"/api/v1/admin/investments/plans/{plan['id']}", json={"return_rate": "15"}, headers=admin_headers
        )
        assert res.status_code == 200 and Decimal(res.json()["return_rate"]) == 15

        image = base64.b64encode(PNG).decode()
        res = await api_client.put(
            f"/api/v1/admin/investments/plans/{plan['id']}/image", json={"image": image}, headers=admin_headers
        )
        assert res.status_code == 200, res.text
        url = res.json()["image_url"]
        assert url.startswith(f"/api/v1/investments/plans/{plan['id']}/image")
        pic = await api_client.get(url)
        assert pic.status_code == 200 and pic.headers["content-type"] == "image/png"

    async def test_picture_must_be_an_image(self, api_client, admin_headers):
        plan = await _plan(api_client, admin_headers)
        res = await api_client.put(
            f"/api/v1/admin/investments/plans/{plan['id']}/image",
            json={"image": base64.b64encode(b"not an image" * 100).decode()},
            headers=admin_headers,
        )
        assert res.status_code == 422 and res.json()["code"] == "IMAGE_INVALID"

    async def test_customers_see_only_active_plans(self, api_client, admin_headers):
        plan = await _plan(api_client, admin_headers)
        await api_client.patch(
            f"/api/v1/admin/investments/plans/{plan['id']}", json={"is_active": False}, headers=admin_headers
        )
        listed = (await api_client.get("/api/v1/investments/plans")).json()
        assert plan["id"] not in [p["id"] for p in listed]

    async def test_customers_cannot_manage_plans(self, api_client):
        _, headers = await _customer(api_client)
        res = await api_client.get("/api/v1/admin/investments/plans", headers=headers)
        assert res.status_code in (401, 403)


class TestInvesting:
    async def test_invest_from_the_wallet(self, api_client, db_session, admin_headers, investments_on):
        plan = await _plan(api_client, admin_headers)
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id, "20000")

        res = await _invest(api_client, headers, plan["id"], "10000")
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["reference"].startswith("INV-")
        assert Decimal(body["projected_return"]) == Decimal("600.00")
        assert Decimal(body["maturity_value"]) == Decimal("10600.00")
        assert await _balance(db_session, customer_id) == Decimal("10000")

        mine = (await api_client.get("/api/v1/investments/me", headers=headers)).json()
        assert [m["status"] for m in mine] == ["active"]
        history = (await api_client.get("/api/v1/wallet/transactions?direction=out", headers=headers)).json()
        assert [i["kind"] for i in history["items"]] == ["investment"]

        staff = (await api_client.get("/api/v1/admin/investments/holdings", headers=admin_headers)).json()
        assert staff["total"] == 1 and Decimal(str(staff["active_amount"])) == Decimal("10000")

    async def test_not_enough_money(self, api_client, db_session, admin_headers, investments_on):
        plan = await _plan(api_client, admin_headers)
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id, "6000")
        res = await _invest(api_client, headers, plan["id"], "8000")
        assert res.status_code == 409 and res.json()["code"] == "INSUFFICIENT_FUNDS"
        assert await _balance(db_session, customer_id) == Decimal("6000")

    @pytest.mark.parametrize(("amount", "code"), [("1000", "AMOUNT_TOO_SMALL"), ("900000", "AMOUNT_TOO_LARGE")])
    async def test_plan_limits(self, api_client, db_session, admin_headers, investments_on, amount, code):
        plan = await _plan(api_client, admin_headers)
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id, "1000000")
        res = await _invest(api_client, headers, plan["id"], amount)
        assert res.status_code == 422 and res.json()["code"] == code

    async def test_wrong_pin(self, api_client, db_session, admin_headers, investments_on):
        plan = await _plan(api_client, admin_headers)
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id, "20000")
        res = await _invest(api_client, headers, plan["id"], "10000", pin="9999")
        assert res.status_code == 400
        assert await _balance(db_session, customer_id) == Decimal("20000")

    async def test_switched_off(self, api_client, db_session, admin_headers):
        plan = await _plan(api_client, admin_headers)
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id, "20000")
        res = await _invest(api_client, headers, plan["id"], "10000")
        assert res.status_code == 403 and res.json()["code"] == "FEATURE_DISABLED"

    async def test_payout_at_maturity_once(self, api_client, db_session, admin_headers, investments_on):
        plan = await _plan(api_client, admin_headers)
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id, "10000")
        assert (await _invest(api_client, headers, plan["id"], "10000")).status_code == 201

        service = InvestmentService(db_session)
        assert await service.pay_out_matured(today=date.today()) == 0  # not due yet
        later = date.today() + timedelta(days=200)
        assert await service.pay_out_matured(today=later) == 1
        assert await service.pay_out_matured(today=later) == 0
        await db_session.commit()

        assert await _balance(db_session, customer_id) == Decimal("10600.00")
        inv = (await db_session.execute(select(CustomerInvestment))).scalar_one()
        assert inv.status == "paid_out" and inv.payout_amount == Decimal("10600.00")
        history = (await api_client.get("/api/v1/wallet/transactions?direction=in", headers=headers)).json()
        assert "investment_payout" in [i["kind"] for i in history["items"]]

    async def test_active_investment_blocks_account_deletion(
        self, api_client, db_session, admin_headers, investments_on
    ):
        plan = await _plan(api_client, admin_headers)
        customer_id, headers = await _customer(api_client)
        await _fund(db_session, customer_id, "10000")
        assert (await _invest(api_client, headers, plan["id"], "10000")).status_code == 201
        res = await api_client.get("/api/v1/auth/me/account-deletion", headers=headers)
        assert res.status_code == 200, res.text
        assert "INVESTMENT_ACTIVE" in [b["code"] for b in res.json()["blockers"]]


class TestCardTopUp:
    async def test_mock_card_top_up_is_credited_at_once(self, api_client, db_session):
        customer_id, headers = await _customer(api_client)
        res = await api_client.post("/api/v1/wallet/fund/card", json={"amount": "5000"}, headers=headers)
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["status"] == "completed" and body["checkout_url"] is None
        assert body["return_url"].endswith("/api/v1/wallet/fund/card/return")
        assert await _balance(db_session, customer_id) == Decimal("5000")

        again = await api_client.get(f"/api/v1/wallet/fund/card/{body['reference']}", headers=headers)
        assert again.json()["status"] == "completed"
        assert await _balance(db_session, customer_id) == Decimal("5000")

    async def test_webhook_credits_a_pending_top_up_once(self, api_client, db_session):
        from app.modules.payments.card_funding import CardFundingService
        from app.modules.payments.models import PaymentChannel, PaymentDirection, PaymentProvider
        from app.models.base import TransactionStatus
        from app.modules.users.models import Customer

        customer_id, _ = await _customer(api_client)
        customer = await db_session.get(Customer, customer_id)
        tx = PaymentTransaction(
            provider=PaymentProvider.MONNIFY,
            provider_reference="GHT-CARD-ABC123",
            direction=PaymentDirection.INBOUND,
            channel=PaymentChannel.CARD,
            amount=Decimal("7000"),
            status=TransactionStatus.PENDING,
            customer_id=customer.id,
        )
        db_session.add(tx)
        await db_session.flush()
        data = {"paymentReference": "GHT-CARD-ABC123", "transactionReference": "MNFY|1", "amountPaid": "7000"}
        service = CardFundingService(db_session)
        assert await service.handle_webhook(data)
        assert await service.handle_webhook(data)
        await db_session.commit()
        assert await _balance(db_session, customer_id) == Decimal("7000")
        assert tx.status == TransactionStatus.COMPLETED

    async def test_amount_limits(self, api_client):
        _, headers = await _customer(api_client)
        res = await api_client.post("/api/v1/wallet/fund/card", json={"amount": "50"}, headers=headers)
        assert res.status_code == 422

    async def test_return_page_hands_back_to_the_app(self, api_client):
        res = await api_client.get("/api/v1/wallet/fund/card/return?paymentReference=GHT-CARD-1<script>")
        assert res.status_code == 200
        assert "ghtrust://fund?reference=GHT-CARD-1script" in res.text
        assert "<script>location" in res.text
