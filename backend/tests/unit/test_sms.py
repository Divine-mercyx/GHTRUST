"""SMS delivery: Termii integration, failure handling, and provider selection."""

import json

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations import sms
from tests.conftest import refresh_settings


@pytest.fixture
def termii_env(monkeypatch):
    monkeypatch.setenv("SMS_MOCK", "false")
    monkeypatch.setenv("SMS_PROVIDER", "termii")
    monkeypatch.setenv("TERMII_API_KEY", "TL_test_key")
    monkeypatch.setenv("TERMII_SENDER_ID", "GHTrust")
    monkeypatch.setenv("TERMII_BASE_URL", "https://termii.example")
    refresh_settings()


def _route(monkeypatch, handler):
    real = httpx.AsyncClient

    def client(*args, **kwargs):
        return real(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(sms.httpx, "AsyncClient", client)


async def test_termii_sends_otp_on_the_dnd_channel(termii_env, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"code": "ok", "message_id": "3017544054459083819856413"}
        )

    _route(monkeypatch, handler)
    sender = sms.get_sms_sender()
    assert isinstance(sender, sms.TermiiSmsSender)
    await sender.send("08027218077", "123456 is your code")

    assert seen["url"] == "https://termii.example/api/sms/send"
    assert seen["body"] == {
        "api_key": "TL_test_key",
        "to": "2348027218077",  # international, no plus
        "from": "GHTrust",
        "sms": "123456 is your code",
        "type": "plain",
        "channel": "dnd",  # reaches numbers on Do-Not-Disturb
    }


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"message": "Invalid API key"}),
        httpx.Response(200, json={"code": "error", "message": "Insufficient balance"}),
        httpx.Response(200, text="<html>gateway</html>"),
    ],
)
async def test_termii_rejection_is_a_clean_503(termii_env, monkeypatch, response):
    _route(monkeypatch, lambda request: response)
    with pytest.raises(AppError) as exc:
        await sms.get_sms_sender().send("08027218077", "123456 is your code")
    assert exc.value.status_code == 503
    assert exc.value.code == "SMS_UNAVAILABLE"


async def test_termii_unreachable_is_a_clean_503(termii_env, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    _route(monkeypatch, handler)
    with pytest.raises(AppError) as exc:
        await sms.get_sms_sender().send("08027218077", "123456 is your code")
    assert exc.value.code == "SMS_UNAVAILABLE"


def test_termii_without_credentials_fails_loudly(monkeypatch):
    monkeypatch.setenv("SMS_MOCK", "false")
    monkeypatch.setenv("SMS_PROVIDER", "termii")
    refresh_settings()
    assert isinstance(sms.get_sms_sender(), sms.UnavailableSmsSender)


def test_production_requires_a_supported_configured_provider():
    base = dict(app_env="production", sms_mock=False)
    missing = "\n".join(
        Settings(**base, sms_provider="termii").production_config_errors()
    )
    assert "TERMII_API_KEY" in missing
    unknown = "\n".join(
        Settings(**base, sms_provider="carrier-pigeon").production_config_errors()
    )
    assert "not supported" in unknown
    ok = Settings(
        **base, sms_provider="termii", termii_api_key="k", termii_sender_id="GHTrust"
    )
    assert not any("SMS" in e or "Termii" in e for e in ok.production_config_errors())


def test_dev_code_is_never_exposed_outside_local_development():
    assert Settings(app_env="development", sms_mock=True).expose_dev_otp
    assert not Settings(app_env="development", sms_mock=False).expose_dev_otp
    assert not Settings(app_env="test", sms_mock=True).expose_dev_otp
    assert not Settings(app_env="production", sms_mock=True).expose_dev_otp
    assert not Settings(
        app_env="development", sms_mock=True, otp_dev_echo=False
    ).expose_dev_otp


# ── Dojah Messaging ─────────────────────────────────────────────────────────


@pytest.fixture
def dojah_env(monkeypatch):
    monkeypatch.setenv("SMS_MOCK", "false")
    monkeypatch.setenv("SMS_PROVIDER", "dojah")
    monkeypatch.setenv("DOJAH_APP_ID", "app-123")
    monkeypatch.setenv("DOJAH_SECRET_KEY", "prod_sk_test")
    monkeypatch.setenv("DOJAH_SENDER_ID", "GHTrust")
    monkeypatch.setenv("DOJAH_BASE_URL", "https://dojah.example")
    refresh_settings()


def _dojah(monkeypatch, entity: dict, seen: list, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"entity": entity} if status < 400 else {"error": "Insufficient wallet"})

    _route(monkeypatch, handler)


async def test_dojah_delivers_our_code_through_its_otp_route(dojah_env, monkeypatch):
    seen: list[httpx.Request] = []
    _dojah(monkeypatch, {"reference_id": "ref-1", "destination": "2348027218077", "status": "SMS sent"}, seen)
    sender = sms.get_sms_sender()
    assert isinstance(sender, sms.DojahSmsSender)
    await sender.send_otp("08027218077", "482917", "login")

    request = seen[0]
    assert str(request.url) == "https://dojah.example/api/v1/messaging/otp"
    assert request.headers["Authorization"] == "prod_sk_test"  # as-is, not Bearer
    assert request.headers["AppId"] == "app-123"
    body = json.loads(request.content)
    assert body == {
        "sender_id": "GHTrust",
        "destination": "2348027218077",
        "channel": "sms",
        "length": 6,
        "expiry": 10,
        "priority": True,
        "otp": 482917,  # GH Trust's code: we still check it ourselves
    }


async def test_dojah_sms_validate_and_status(dojah_env, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/sms"):
            entity = {"status": "Sent", "message_id": "dj_1", "reference_id": "r"}
        elif path.endswith("/get_status"):
            entity = {"status": "delivered"}
        else:  # /otp/validate
            entity = {"valid": request.url.params["code"] == "1234"}
        return httpx.Response(200, json={"entity": entity})

    _route(monkeypatch, handler)
    api = sms.DojahMessaging()

    sent = await api.send_sms("+2348027218077", "Your loan is approved")
    assert sent["message_id"] == "dj_1"
    assert json.loads(seen[-1].content)["destination"] == "2348027218077"

    assert await api.message_status("dj_1") == "DELIVERED"
    assert seen[-1].url.params["message_id"] == "dj_1"

    assert await api.validate_otp("ref-1", "1234") is True
    assert seen[-1].url.params["reference_id"] == "ref-1"
    assert await api.validate_otp("ref-1", "9999") is False


@pytest.mark.parametrize("status", [401, 402, 422])
async def test_dojah_rejection_is_a_clean_503(dojah_env, monkeypatch, status):
    _dojah(monkeypatch, {}, [], status=status)
    with pytest.raises(AppError) as exc:
        await sms.get_sms_sender().send_otp("08027218077", "482917", "login")
    assert exc.value.status_code == 503 and exc.value.code == "SMS_UNAVAILABLE"


def test_dojah_without_a_sender_id_fails_loudly(dojah_env, monkeypatch):
    monkeypatch.setenv("DOJAH_SENDER_ID", "")
    refresh_settings()
    assert isinstance(sms.get_sms_sender(), sms.UnavailableSmsSender)
    errors = "\n".join(
        Settings(app_env="production", sms_mock=False, sms_provider="dojah", dojah_app_id="a").production_config_errors()
    )
    assert "DOJAH_SENDER_ID" in errors


async def test_login_codes_go_through_dojah_and_are_checked_by_us(dojah_env, monkeypatch, fake_redis):
    from app.core.rate_limit import OtpService

    seen: list[httpx.Request] = []
    _dojah(monkeypatch, {"reference_id": "ref-9"}, seen)
    otp = OtpService(fake_redis)
    await otp.send("login", "+2348027218077", "+2348027218077")
    code = str(json.loads(seen[0].content)["otp"])
    assert len(code) == 6 and code[0] != "0"
    assert await otp.verify("login", "+2348027218077", code) is True
