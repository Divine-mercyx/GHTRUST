"""Demo sign-in: fixed code for listed numbers, no SMS, and no money leaving on the live system."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.demo import blocks_money_out, demo_code_for, weak_code
from app.core.errors import AppError
from app.core.pins import verify_pin
from app.modules.auth.demo_accounts import DemoSeedError, seed_demo_customers
from app.modules.auth.models import SelfieAttempt
from app.modules.auth.security_service import SecurityService
from app.modules.users.models import Customer
from tests.conftest import TEST_ADMIN_PHONE, TEST_OTP, refresh_settings
from tests.integration.test_registration_selfie import _selfie

DEMO_PHONE = "08011112222"
DEMO_E164 = "+2348011112222"
DEMO_OTP = "482917"
PHONE_A = {"device_id": "install-aaa", "device_name": "Reviewer iPhone", "platform": "ios", "app_version": "1.0.0"}
PHONE_B = {"device_id": "install-bbb", "device_name": "Tester Pixel", "platform": "android", "app_version": "1.0.0"}
SMS = "app.integrations.sms.get_sms_sender"


@pytest.fixture
def demo_env(monkeypatch):
    monkeypatch.setenv("DEMO_PHONES", f"{DEMO_PHONE}, {TEST_ADMIN_PHONE}")
    monkeypatch.setenv("DEMO_OTP", DEMO_OTP)
    monkeypatch.setenv("DEMO_LOGIN_PIN", "250813")
    monkeypatch.setenv("DEMO_TRANSACTION_PIN", "7031")
    refresh_settings()


def _production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    refresh_settings()


async def _sign_in(api_client, device: dict, *, phone: str = DEMO_PHONE, otp: str = DEMO_OTP):
    sent = await api_client.post("/api/v1/auth/login/request-otp", json={"phone": phone})
    assert sent.status_code == 200, sent.text
    return await api_client.post(
        "/api/v1/auth/login/verify-otp", json={"phone": phone, "otp": otp, "device": device}
    )


class TestSeed:
    async def test_creates_an_open_account_with_the_demo_pins(self, db_session, demo_env, super_admin):
        seeded = await seed_demo_customers(db_session)
        # The admin's number is staff: it stays a portal login, not a customer.
        assert seeded == [DEMO_E164]
        customer = (
            await db_session.execute(select(Customer).where(Customer.phone_primary == DEMO_E164))
        ).scalar_one()
        assert customer.status == "active" and customer.first_name == "Demo"
        assert verify_pin("250813", customer.login_pin_hash)
        assert verify_pin("7031", customer.transaction_pin_hash)

    async def test_rerun_resets_instead_of_duplicating(self, db_session, demo_env):
        query = select(Customer).where(Customer.phone_primary == DEMO_E164)
        await seed_demo_customers(db_session)
        customer = (await db_session.execute(query)).scalar_one()
        customer.login_pin_failed_attempts = 5
        await seed_demo_customers(db_session)
        rows = (await db_session.execute(query)).scalars().all()
        assert len(rows) == 1 and rows[0].login_pin_failed_attempts == 0

    async def test_rerun_keeps_a_pin_the_tester_changed_unless_asked(self, db_session, demo_env):
        """Every deploy and restart re-runs the seed: it mustn't make a tester's PIN "wrong"."""
        await seed_demo_customers(db_session)
        customer = (await db_session.execute(select(Customer).where(Customer.phone_primary == DEMO_E164))).scalar_one()
        await SecurityService(db_session).change_login_pin(customer, "no-session", "250813", "480173")

        await seed_demo_customers(db_session)
        assert verify_pin("480173", customer.login_pin_hash)
        await seed_demo_customers(db_session, reset_pins=True)
        assert verify_pin("250813", customer.login_pin_hash)

    async def test_rejects_a_malformed_pin(self, db_session, demo_env, monkeypatch):
        monkeypatch.setenv("DEMO_LOGIN_PIN", "12")
        refresh_settings()
        with pytest.raises(DemoSeedError, match="DEMO_LOGIN_PIN"):
            await seed_demo_customers(db_session)


class TestSignIn:
    async def test_demo_number_signs_in_with_the_fixed_code_and_no_sms(self, api_client, db_session, demo_env):
        await seed_demo_customers(db_session)
        await db_session.commit()
        sender = AsyncMock()
        with patch(SMS, return_value=sender):
            res = await _sign_in(api_client, PHONE_A)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "signed_in"
        sender.send.assert_not_called()

    async def test_second_phone_is_not_held_for_approval(self, api_client, db_session, demo_env):
        await seed_demo_customers(db_session)
        await db_session.commit()
        assert (await _sign_in(api_client, PHONE_A)).json()["status"] == "signed_in"
        # A normal account would wait for PHONE_A to approve; a shared demo account can't.
        assert (await _sign_in(api_client, PHONE_B)).json()["status"] == "signed_in"

    async def test_other_numbers_still_get_a_random_code_by_sms(self, api_client, registered_customer, demo_env):
        sender = AsyncMock()
        with patch(SMS, return_value=sender):
            wrong = await _sign_in(api_client, PHONE_A, phone="08035794364")
        assert wrong.status_code == 400  # the demo code doesn't open a normal account
        sender.send.assert_awaited_once()
        ok = await api_client.post(
            "/api/v1/auth/login/verify-otp", json={"phone": "08035794364", "otp": TEST_OTP}
        )
        assert ok.status_code == 200, ok.text

    async def test_staff_can_use_it_on_a_test_server(self, api_client, super_admin, demo_env):
        await api_client.post("/api/v1/admin/auth/login/request-otp", json={"phone": TEST_ADMIN_PHONE})
        res = await api_client.post(
            "/api/v1/admin/auth/login/verify-otp", json={"phone": TEST_ADMIN_PHONE, "otp": DEMO_OTP}
        )
        assert res.status_code == 200, res.text


class TestProductionLimits:
    def test_staff_never_get_the_demo_code_in_production(self, demo_env, monkeypatch):
        assert demo_code_for("staff_login", TEST_ADMIN_PHONE) == DEMO_OTP
        _production(monkeypatch)
        assert demo_code_for("staff_login", TEST_ADMIN_PHONE) is None
        assert demo_code_for("login", DEMO_PHONE) == DEMO_OTP

    def test_money_only_blocked_on_the_live_system(self, demo_env, monkeypatch):
        assert not blocks_money_out(DEMO_E164)
        _production(monkeypatch)
        assert blocks_money_out(DEMO_E164)
        assert not blocks_money_out("+2348035794364")

    async def test_withdrawals_refused_but_signing_still_works(self, db_session, demo_env, monkeypatch):
        _production(monkeypatch)
        customer = Customer(phone_primary=DEMO_E164)
        security = SecurityService(db_session)
        with pytest.raises(AppError) as money_out:
            await security.authorize_transaction(customer, "7031")
        assert money_out.value.code == "DEMO_ACCOUNT"
        # Signing an offer (check_hold=False) goes on to the normal PIN checks.
        with pytest.raises(AppError) as signing:
            await security.authorize_transaction(customer, "7031", check_hold=False)
        assert signing.value.code == "TRANSACTION_PIN_NOT_SET"


DEMO_BVN = "00000000001"
DOJAH = "app.integrations.dojah.client.DojahClient"


def _dojah_off():
    """Fail the test if a demo BVN reaches Dojah or the payment provider."""
    boom = AsyncMock(side_effect=AssertionError("called an external service for a demo BVN"))
    return (
        patch(f"{DOJAH}.lookup_bvn_advanced", boom),
        patch(f"{DOJAH}.verify_bvn_selfie", boom),
        patch(f"{DOJAH}.check_liveness", boom),
        patch("app.modules.payments.wallet_service.WalletService.provision_payment_rail", boom),
    )


@pytest.fixture
def demo_bvn_env(monkeypatch):
    monkeypatch.setenv("DEMO_BVNS", DEMO_BVN)
    monkeypatch.setenv("DEMO_OTP", DEMO_OTP)
    monkeypatch.setenv("DOJAH_SELFIE_REQUIRED", "true")
    monkeypatch.setenv("DOJAH_LIVENESS_REQUIRED", "true")
    refresh_settings()


async def _register_demo(api_client) -> dict:
    sent = await api_client.post("/api/v1/auth/register/bvn", json={"bvn": DEMO_BVN})
    assert sent.status_code == 200, sent.text
    assert sent.json()["phone_masked"].endswith("0001")
    started = await api_client.post("/api/v1/auth/register/verify-otp", json={"bvn": DEMO_BVN, "otp": DEMO_OTP})
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "selfie_required"
    assert started.json()["first_name"] == "Demo"
    opened = await _selfie(api_client, started.json()["registration_token"])
    assert opened.status_code == 200, opened.text
    return opened.json()


class TestDemoBvn:
    async def test_signs_up_without_dojah_sms_or_payment_provider(self, api_client, db_session, demo_bvn_env):
        sender = AsyncMock()
        lookup, verify, live, rail = _dojah_off()
        with lookup, verify, live, rail, patch(SMS, return_value=sender):
            tokens = await _register_demo(api_client)
        assert "access_token" in tokens
        sender.send.assert_not_called()
        customer = (await db_session.execute(select(Customer).where(Customer.bvn == DEMO_BVN))).scalar_one()
        assert customer.status == "active" and customer.phone_primary == "+2347000000001"
        # Simulated sign-ups stay out of the Onboarding face-check figures.
        assert (await db_session.execute(select(SelfieAttempt))).first() is None

    async def test_entering_it_again_starts_over(self, api_client, db_session, demo_bvn_env):
        lookup, verify, live, rail = _dojah_off()
        with lookup, verify, live, rail:
            first = await _register_demo(api_client)
            await _register_demo(api_client)
        rows = (await db_session.execute(select(Customer).order_by(Customer.created_at))).scalars().all()
        assert [c.status for c in rows] == ["inactive", "active"]
        assert rows[1].bvn == DEMO_BVN and rows[0].bvn != DEMO_BVN
        # The first attempt's session was signed out.
        me = await api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {first['access_token']}"})
        assert me.status_code == 401

    async def test_signs_in_later_with_the_demo_code(self, api_client, demo_bvn_env):
        lookup, verify, live, rail = _dojah_off()
        with lookup, verify, live, rail:
            await _register_demo(api_client)
        res = await _sign_in(api_client, PHONE_A, phone="07000000001")
        assert res.status_code == 200, res.text

    async def test_real_bvns_still_go_to_dojah(self, api_client, demo_bvn_env):
        with patch(f"{DOJAH}.lookup_bvn_advanced", AsyncMock(side_effect=AssertionError("dojah"))):
            with pytest.raises(AssertionError, match="dojah"):
                await api_client.post("/api/v1/auth/register/bvn", json={"bvn": "22222222222"})

    def test_refused_in_production(self):
        from app.core.config import Settings
        from tests.unit.test_platform import LIVE_PROD

        errors = Settings(_env_file=None, **{**LIVE_PROD, "demo_bvns": DEMO_BVN}).production_config_errors()
        assert any("DEMO_BVNS" in e for e in errors)


@pytest.mark.parametrize(
    ("code", "weak"),
    [("000000", True), ("123456", True), ("654321", True), ("482917", False), ("112233", False)],
)
def test_weak_codes(code, weak):
    assert weak_code(code) is weak
