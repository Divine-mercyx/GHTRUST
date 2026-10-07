"""Production config guard, client IP resolution, rate limiter, SMS delivery."""

from types import SimpleNamespace

import fakeredis.aioredis
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.core.rate_limit import RateLimiter, RateLimitExceeded, get_client_ip
from tests.conftest import refresh_settings

LIVE_PROD = dict(
    app_env="production",
    debug=False,
    secret_key="x" * 48,
    sms_mock=False,
    sms_provider="termii",
    termii_api_key="TL_live_key",
    termii_sender_id="GHTrust",
    dojah_mock=False,
    dojah_app_id="app",
    dojah_secret_key="secret",
    payment_provider="monnify",
    monnify_mock=False,
    monnify_api_key="MK_PROD_k",
    monnify_base_url="https://api.monnify.com",
    monnify_secret_key="s",
    monnify_contract_code="c",
    cors_origins="https://admin.ghtrust.com",
    database_url="postgresql+asyncpg://ghtrust:s@db.internal:5432/ghtrust",
    redis_url="redis://redis.internal:6379/0",
    celery_broker_url="redis://redis.internal:6379/1",
    celery_result_backend="redis://redis.internal:6379/2",
)


class TestProductionGuard:
    def test_fully_configured_production_passes(self):
        assert Settings(_env_file=None, **LIVE_PROD).production_config_errors() == []

    def test_wallet_may_be_switched_on(self):
        s = Settings(_env_file=None, **{**LIVE_PROD, "feature_flags": " wallet "})
        assert s.production_config_errors() == []

    def test_demo_numbers_with_a_strong_code_pass(self):
        s = Settings(_env_file=None, **{**LIVE_PROD, "demo_phones": "08011112222", "demo_otp": "482917"})
        assert s.production_config_errors() == []

    def test_non_production_is_never_blocked(self):
        s = Settings(_env_file=None, app_env="staging", debug=True, sms_mock=True)
        assert s.production_config_errors() == []

    @pytest.mark.parametrize(
        ("override", "fragment"),
        [
            ({"secret_key": "dev-secret-change-in-production"}, "SECRET_KEY"),
            ({"secret_key": "short"}, "SECRET_KEY"),
            ({"debug": True}, "DEBUG"),
            ({"database_url": "postgresql+asyncpg://u:p@localhost:5432/db"}, "DATABASE_URL"),
            ({"redis_url": "redis://127.0.0.1:6379/0"}, "REDIS_URL"),
            ({"celery_broker_url": "redis://localhost:6379/1"}, "CELERY_BROKER_URL"),
            ({"sms_mock": True}, "SMS_MOCK"),
            ({"sms_provider": ""}, "SMS_PROVIDER"),
            ({"dojah_mock": True}, "Dojah"),
            ({"monnify_mock": True}, "mock mode"),
            ({"monnify_secret_key": ""}, "Webhook signing secret"),
            ({"monnify_base_url": "https://sandbox.monnify.com"}, "sandbox"),
            ({"monnify_api_key": "MK_TEST_abc"}, "sandbox"),
            ({"dojah_base_url": "https://sandbox.dojah.io"}, "DOJAH_BASE_URL"),
            ({"cors_origins": "http://localhost:5173"}, "localhost"),
            ({"feature_flags": "wallet,savings"}, "savings"),
            ({"feature_flags": "food_basket"}, "FEATURE_FLAGS"),
            ({"demo_phones": "08011112222"}, "DEMO_OTP must be"),
            ({"demo_phones": "08011112222", "demo_otp": "123456"}, "guessable"),
        ],
    )
    def test_each_misconfiguration_is_reported(self, override, fragment):
        errors = Settings(_env_file=None, **{**LIVE_PROD, **override}).production_config_errors()
        assert any(fragment in e for e in errors), errors

    def test_app_refuses_to_boot_in_misconfigured_production(self, monkeypatch):
        from app.main import ProductionConfigError, create_app

        monkeypatch.setenv("APP_ENV", "production")
        refresh_settings()
        with pytest.raises(ProductionConfigError, match="Refusing to start"):
            create_app()


def _request(peer: str, xff: str | None = None):
    headers = {"X-Forwarded-For": xff} if xff else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))


class TestClientIp:
    def test_header_ignored_without_trusted_proxies(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_COUNT", "0")
        refresh_settings()
        assert get_client_ip(_request("10.0.0.5", "1.2.3.4")) == "10.0.0.5"

    def test_railway_trusts_its_edge_proxy_by_default(self, monkeypatch):
        monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)
        monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
        assert Settings(_env_file=None).trusted_proxy_count == 1
        assert Settings(_env_file=None, trusted_proxy_count=0).trusted_proxy_count == 0
        monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME")
        assert Settings(_env_file=None).trusted_proxy_count == 0

    def test_uses_address_appended_by_trusted_proxy(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
        refresh_settings()
        # Client forged "6.6.6.6"; the load balancer appended the real 41.1.1.1.
        assert get_client_ip(_request("10.0.0.1", "6.6.6.6, 41.1.1.1")) == "41.1.1.1"

    def test_spoofed_prefix_cannot_escape_rate_limit(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
        refresh_settings()
        a = get_client_ip(_request("10.0.0.1", "1.1.1.1, 41.1.1.1"))
        b = get_client_ip(_request("10.0.0.1", "2.2.2.2, 41.1.1.1"))
        assert a == b == "41.1.1.1"


class TestRateLimiter:
    async def test_counter_always_has_ttl_and_blocks_over_limit(self):
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        limiter = RateLimiter(redis)
        for _ in range(3):
            await limiter.hit("k", limit=3, window_seconds=60)
        assert 0 < await redis.ttl("ratelimit:k") <= 60
        with pytest.raises(RateLimitExceeded) as exc:
            await limiter.hit("k", limit=3, window_seconds=60)
        assert int(exc.value.headers["Retry-After"]) >= 1
        await redis.aclose()

    async def test_window_is_not_extended_by_later_hits(self):
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        limiter = RateLimiter(redis)
        await limiter.hit("w", limit=10, window_seconds=60)
        await redis.expire("ratelimit:w", 5)
        await limiter.hit("w", limit=10, window_seconds=60)
        assert await redis.ttl("ratelimit:w") <= 5
        await redis.aclose()


class TestSms:
    async def test_no_provider_fails_loudly(self, monkeypatch):
        from app.integrations.sms import get_sms_sender

        monkeypatch.setenv("SMS_MOCK", "false")
        monkeypatch.setenv("SMS_PROVIDER", "")
        refresh_settings()
        with pytest.raises(AppError) as exc:
            await get_sms_sender().send("+2348000000000", "123456")
        assert exc.value.status_code == 503
        assert exc.value.code == "SMS_UNAVAILABLE"

    async def test_otp_not_stored_when_delivery_fails(self, monkeypatch):
        from app.core.rate_limit import OtpService

        monkeypatch.setenv("SMS_MOCK", "false")
        refresh_settings()
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        with pytest.raises(AppError):
            await OtpService(redis).send("login", "+2348000000000", "+2348000000000")
        assert await redis.get("otp:login:+2348000000000") is None
        await redis.aclose()

    async def test_debug_alone_does_not_log_otp(self, monkeypatch, capsys):
        """OTP used to be logged whenever DEBUG=true, even with a real provider."""
        from app.integrations.sms import ConsoleSmsSender, get_sms_sender

        monkeypatch.setenv("SMS_MOCK", "false")
        monkeypatch.setenv("SMS_PROVIDER", "termii")
        monkeypatch.setenv("DEBUG", "true")
        refresh_settings()
        assert not isinstance(get_sms_sender(), ConsoleSmsSender)


class TestDatabaseUrl:
    """Hosts hand out plain postgres URLs; the async engine needs the asyncpg driver."""

    @pytest.mark.parametrize(
        "given",
        ["postgres://u:p@db.railway.internal:5432/app", "postgresql://u:p@db.railway.internal:5432/app"],
    )
    def test_plain_host_urls_get_the_async_driver(self, given):
        s = Settings(_env_file=None, database_url=given)
        assert s.async_database_url == "postgresql+asyncpg://u:p@db.railway.internal:5432/app"
        assert s.sync_database_url == "postgresql://u:p@db.railway.internal:5432/app"

    def test_explicit_asyncpg_url_is_untouched(self):
        url = "postgresql+asyncpg://u:p@db:5432/app"
        assert Settings(_env_file=None, database_url=url).async_database_url == url
