"""Account opening: BVN → SMS code → selfie matched to the BVN photo (Dojah) → account open."""

import base64
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.integrations.dojah.schemas import DojahError, DojahSelfieVerification, LivenessResult
from app.modules.users.models import Customer, CustomerStatus
from tests.conftest import TEST_BVN, TEST_OTP, refresh_settings

# A tiny but valid-looking JPEG: the right magic bytes and a plausible size.
SELFIE = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 8000).decode()
# Other frames from the same live capture: valid images, each one different.
FRAMES = [base64.b64encode(b"\xff\xd8\xff\xe0" + bytes([n]) * 8000).decode() for n in (1, 2)]
VERIFY = "app.integrations.dojah.client.DojahClient.verify_bvn_selfie"
LIVENESS = "app.integrations.dojah.client.DojahClient.check_liveness"


def _selfie_on(monkeypatch, attempts: int = 3):
    monkeypatch.setenv("DOJAH_SELFIE_REQUIRED", "true")
    monkeypatch.setenv("DOJAH_SELFIE_MAX_ATTEMPTS", str(attempts))
    refresh_settings()


async def _start(api_client) -> dict:
    await api_client.post("/api/v1/auth/register/bvn", json={"bvn": TEST_BVN})
    res = await api_client.post("/api/v1/auth/register/verify-otp", json={"bvn": TEST_BVN, "otp": TEST_OTP})
    assert res.status_code == 200, res.text
    return res.json()


async def _selfie(api_client, token: str, image: str = SELFIE, frames: list[str] | None = None):
    return await api_client.post(
        "/api/v1/auth/register/selfie",
        json={
            "registration_token": token,
            "selfie_image": image,
            "liveness_frames": FRAMES if frames is None else frames,
            "device": {"device_id": "phone-1"},
        },
    )


async def _customer(db_session) -> Customer:
    customer = (await db_session.execute(select(Customer))).scalar_one()
    await db_session.refresh(customer)
    return customer


class TestSelfieStep:
    async def test_code_then_selfie_opens_the_account(self, api_client, db_session, monkeypatch):
        _selfie_on(monkeypatch)
        started = await _start(api_client)
        assert started["status"] == "selfie_required"
        assert "access_token" not in started
        assert started["attempts_left"] == 3
        assert started["first_name"] == "Adaeze"
        # Not open yet: the code alone doesn't open the account.
        assert (await _customer(db_session)).status == CustomerStatus.PENDING_OTP

        with patch(VERIFY, AsyncMock(return_value=DojahSelfieVerification(confidence_value=96.4, match=True))) as call:
            res = await _selfie(api_client, started["registration_token"], f"data:image/jpeg;base64,{SELFIE}")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "signed_in" and body["access_token"] and body["device_token"]
        # The data: prefix is stripped and the configured threshold (Dojah's 90) is sent.
        assert call.await_args.args == (TEST_BVN, SELFIE, 90)

        customer = await _customer(db_session)
        assert customer.status == CustomerStatus.ACTIVE
        assert customer.phone_verified is True
        assert customer.selfie_match_score == 96.4
        assert customer.selfie_verified_at is not None

    async def test_ticket_is_single_use(self, api_client, monkeypatch):
        _selfie_on(monkeypatch)
        token = (await _start(api_client))["registration_token"]
        with patch(VERIFY, AsyncMock(return_value=DojahSelfieVerification(confidence_value=96, match=True))):
            assert (await _selfie(api_client, token)).status_code == 200
            again = await _selfie(api_client, token)
        assert again.status_code == 410
        assert again.json()["code"] == "REGISTRATION_EXPIRED"

    async def test_no_match_counts_down_then_cools_down_for_an_hour(
        self, api_client, db_session, fake_redis, monkeypatch
    ):
        _selfie_on(monkeypatch, attempts=2)
        token = (await _start(api_client))["registration_token"]
        with patch(VERIFY, AsyncMock(return_value=DojahSelfieVerification(confidence_value=41.0, match=False))):
            first = await _selfie(api_client, token)
            assert first.status_code == 400
            assert first.json()["code"] == "SELFIE_NO_MATCH"
            assert first.json()["errors"] == [{"attempts_left": 1}]
            last = await _selfie(api_client, token)
        assert last.status_code == 429
        assert last.json()["code"] == "SELFIE_COOLDOWN"
        assert last.json()["errors"] == [{"retry_after": 3600}]
        assert last.headers["Retry-After"] == "3600"
        assert (await _customer(db_session)).status == CustomerStatus.PENDING_OTP

        # The ticket is spent, and the BVN can't start sign-up again (no paid lookup) until it ends.
        assert (await _selfie(api_client, token)).json()["code"] == "REGISTRATION_EXPIRED"
        with patch("app.integrations.dojah.client.DojahClient.lookup_bvn_advanced", AsyncMock()) as lookup:
            again = await api_client.post("/api/v1/auth/register/bvn", json={"bvn": TEST_BVN})
        assert again.status_code == 429
        assert again.json()["code"] == "SELFIE_COOLDOWN"
        assert 3500 < again.json()["errors"][0]["retry_after"] <= 3600
        lookup.assert_not_awaited()

        # Once the hour is up, they can start again.
        for key in await fake_redis.keys("register:selfie:cooldown:*"):
            await fake_redis.delete(key)
        restarted = await _start(api_client)
        assert restarted["status"] == "selfie_required"
        assert restarted["attempts_left"] == 2

    async def test_cooldown_length_is_configurable(self, api_client, monkeypatch):
        _selfie_on(monkeypatch, attempts=1)
        monkeypatch.setenv("DOJAH_SELFIE_COOLDOWN_MINUTES", "15")
        refresh_settings()
        token = (await _start(api_client))["registration_token"]
        with patch(VERIFY, AsyncMock(return_value=DojahSelfieVerification(confidence_value=10, match=False))):
            res = await _selfie(api_client, token)
        assert res.json()["errors"] == [{"retry_after": 900}]

    async def test_unreadable_images_are_rejected_before_dojah(self, api_client, monkeypatch):
        _selfie_on(monkeypatch)
        token = (await _start(api_client))["registration_token"]
        not_an_image = base64.b64encode(b"hello" * 2000).decode()
        with patch(VERIFY, AsyncMock()) as call:
            res = await _selfie(api_client, token, not_an_image)
        assert res.status_code == 400
        assert res.json()["code"] == "SELFIE_UNREADABLE"
        call.assert_not_awaited()

    async def test_dojah_rejecting_the_image_does_not_use_an_attempt(self, api_client, monkeypatch):
        _selfie_on(monkeypatch)
        token = (await _start(api_client))["registration_token"]
        with patch(VERIFY, AsyncMock(side_effect=DojahError("Invalid image", status_code=400))):
            res = await _selfie(api_client, token)
        assert res.json()["code"] == "SELFIE_UNREADABLE"
        with patch(VERIFY, AsyncMock(return_value=DojahSelfieVerification(confidence_value=40, match=False))):
            res = await _selfie(api_client, token)
        assert res.json()["errors"] == [{"attempts_left": 2}]

    async def test_dojah_outage_is_retryable(self, api_client, monkeypatch):
        _selfie_on(monkeypatch)
        token = (await _start(api_client))["registration_token"]
        with patch(VERIFY, AsyncMock(side_effect=DojahError("down", status_code=503))):
            res = await _selfie(api_client, token)
        assert res.status_code == 503
        assert res.json()["code"] == "KYC_UNAVAILABLE"
        with patch(VERIFY, AsyncMock(return_value=DojahSelfieVerification(confidence_value=95, match=True))):
            assert (await _selfie(api_client, token)).status_code == 200

    async def test_liveness_runs_before_the_match(self, api_client, monkeypatch):
        _selfie_on(monkeypatch)
        token = (await _start(api_client))["registration_token"]
        live = AsyncMock(return_value=LivenessResult(live=True, probability=0.97))
        with (
            patch(LIVENESS, live),
            patch(VERIFY, AsyncMock(return_value=DojahSelfieVerification(confidence_value=95, match=True))),
        ):
            assert (await _selfie(api_client, token)).status_code == 200
        assert live.await_args.args == (SELFIE, 0.5)

    async def test_failed_liveness_uses_an_attempt_and_skips_the_match(self, api_client, monkeypatch):
        _selfie_on(monkeypatch, attempts=2)
        token = (await _start(api_client))["registration_token"]
        spoof = AsyncMock(return_value=LivenessResult(live=False, probability=0.02, reason="spoof"))
        with patch(LIVENESS, spoof), patch(VERIFY, AsyncMock()) as match:
            first = await _selfie(api_client, token)
            assert first.status_code == 400
            assert first.json()["code"] == "LIVENESS_FAILED"
            assert first.json()["errors"] == [{"attempts_left": 1}]
            last = await _selfie(api_client, token)
        match.assert_not_awaited()
        assert last.status_code == 429
        assert last.json()["code"] == "SELFIE_COOLDOWN"

    async def test_a_still_photo_is_not_a_live_capture(self, api_client, monkeypatch):
        _selfie_on(monkeypatch)
        token = (await _start(api_client))["registration_token"]
        with patch(LIVENESS, AsyncMock()) as live, patch(VERIFY, AsyncMock()) as match:
            no_frames = await _selfie(api_client, token, frames=[])
            same_frames = await _selfie(api_client, token, frames=[SELFIE, SELFIE])
        for res in (no_frames, same_frames):
            assert res.status_code == 400
            assert res.json()["code"] == "SELFIE_UNREADABLE"
        live.assert_not_awaited()
        match.assert_not_awaited()
        # Rejected before Dojah: no attempt was used.
        with patch(VERIFY, AsyncMock(return_value=DojahSelfieVerification(confidence_value=40, match=False))):
            assert (await _selfie(api_client, token)).json()["errors"] == [{"attempts_left": 2}]

    async def test_liveness_can_be_switched_off(self, api_client, monkeypatch):
        _selfie_on(monkeypatch)
        monkeypatch.setenv("DOJAH_LIVENESS_REQUIRED", "false")
        refresh_settings()
        token = (await _start(api_client))["registration_token"]
        with (
            patch(LIVENESS, AsyncMock()) as live,
            patch(VERIFY, AsyncMock(return_value=DojahSelfieVerification(confidence_value=95, match=True))),
        ):
            assert (await _selfie(api_client, token, frames=[])).status_code == 200
        live.assert_not_awaited()

    async def test_selfie_off_opens_on_the_code(self, api_client):
        body = await _start(api_client)
        assert body["status"] == "signed_in"


class TestBvnLookupErrors:
    async def test_bvn_without_phone_goes_to_branch(self, api_client):
        from tests.conftest import make_dojah_entity

        entity = make_dojah_entity(phone_number1=None)
        with patch("app.integrations.dojah.client.DojahClient.lookup_bvn_advanced", AsyncMock(return_value=entity)):
            res = await api_client.post("/api/v1/auth/register/bvn", json={"bvn": TEST_BVN})
        assert res.status_code == 422
        assert res.json()["code"] == "BVN_NO_PHONE"

    async def test_provider_problem_is_503_not_the_customers_fault(self, api_client):
        with patch(
            "app.integrations.dojah.client.DojahClient.lookup_bvn_advanced",
            AsyncMock(side_effect=DojahError("unavailable", status_code=503)),
        ):
            res = await api_client.post("/api/v1/auth/register/bvn", json={"bvn": TEST_BVN})
        assert res.status_code == 503
        assert res.json()["code"] == "KYC_UNAVAILABLE"


# Real phone frames: ~960 px JPEGs of a few hundred KB each. Three of them, base64
# in JSON, are well over the general 256 KB JSON limit.
BIG_SELFIE = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x07" * 400_000).decode()
BIG_FRAMES = [base64.b64encode(b"\xff\xd8\xff\xe0" + bytes([n]) * 400_000).decode() for n in (1, 2)]


class TestSelfieSize:
    async def test_real_sized_photos_are_accepted(self, api_client, monkeypatch):
        _selfie_on(monkeypatch)
        started = await _start(api_client)
        res = await _selfie(api_client, started["registration_token"], BIG_SELFIE, BIG_FRAMES)
        assert res.status_code == 200, res.text

    async def test_the_selfie_allowance_is_still_capped(self, api_client, monkeypatch):
        _selfie_on(monkeypatch)
        monkeypatch.setenv("MAX_SELFIE_BODY_MB", "1")
        refresh_settings()
        started = await _start(api_client)
        res = await _selfie(api_client, started["registration_token"], BIG_SELFIE, BIG_FRAMES)
        assert res.status_code == 413

    async def test_other_json_requests_keep_the_small_limit(self, api_client):
        res = await api_client.post("/api/v1/auth/login/request-otp", json={"phone": "0" * 300_000})
        assert res.status_code == 413
