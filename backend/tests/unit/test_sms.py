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
