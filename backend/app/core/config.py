from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_INSECURE_SECRETS = frozenset(
    {
        "dev-secret-change-in-production",
        "change-me-in-production-use-openssl-rand-hex-32",
        "",
    }
)



SUPPORTED_SMS_PROVIDERS = frozenset({"termii"})
# Optional modules that are fully built and may be switched on in production.
LIVE_FEATURES = ("wallet",)


def _is_local_url(url: str) -> bool:
    from urllib.parse import urlparse

    return (urlparse(url.replace("+asyncpg", "")).hostname or "") in {"localhost", "127.0.0.1", "::1"}

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "GH Trust MFB API"
    app_env: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    secret_key: str = Field(default="dev-secret-change-in-production")
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8081"

    # Auth tokens. Access tokens are short-lived JWTs; sessions are extended by
    # rotating opaque refresh tokens stored hashed in auth_sessions.
    jwt_algorithm: str = "HS256"
    customer_access_token_minutes: int = 15
    customer_refresh_token_days: int = 30
    staff_access_token_minutes: int = 10
    staff_refresh_token_hours: int = 12
    # A staff session unused (no token refresh) for this long can't be refreshed:
    # the next launch or wake-up goes to the sign-in screen.
    # Default staff idle timeout; a super admin can change it in the portal (5-60 minutes).
    staff_session_idle_minutes: int = 30
    # Web portal: refresh token travels only in this httpOnly cookie (never readable by JS).
    staff_refresh_cookie_name: str = "ghtrust_staff_rt"
    # Seconds during which presenting the just-rotated refresh token is treated
    # as a benign client race (two requests refreshing at once) rather than theft.
    refresh_token_reuse_grace_seconds: int = 30

    # Serve /docs, /redoc and /openapi.json. Independent of DEBUG so staging can
    # publish the contract for the mobile team without enabling debug behaviour.
    enable_api_docs: bool = False

    # Number of reverse proxies in front of the API that append to
    # X-Forwarded-For. 0 = trust nothing and use the socket peer address.
    # Set to 1 behind a single load balancer. Getting this wrong lets clients
    # spoof their IP and evade per-IP rate limits.
    trusted_proxy_count: int = 0

    # SMS OTP delivery: "" (none) or "termii". With SMS_MOCK=false and no
    # provider, OTP sends fail loudly instead of silently.
    sms_provider: str = ""
    termii_api_key: str = ""
    termii_sender_id: str = ""  # approved alphanumeric sender ID, 3-11 chars
    termii_base_url: str = "https://v3.api.termii.com"  # shown on your Termii dashboard
    termii_channel: str = "dnd"  # "dnd" reaches DND numbers; OTPs must use it

    # A loan is only paid out after the customer accepts the final offer in the app.
    loan_offer_acceptance_required: bool = True

    # Push notifications through Expo's push service (https://docs.expo.dev/push-notifications/sending-notifications/).
    # PUSH_MOCK=true logs pushes instead of sending them. EXPO_PUSH_ACCESS_TOKEN is only
    # needed if "enhanced push security" is switched on for the Expo project.
    push_mock: bool = True
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    expo_push_access_token: str = ""

    # Mobile app remote config (GET /api/v1/app/config) and version gate.
    app_min_version_ios: str = "1.0.0"
    app_min_version_android: str = "1.0.0"
    app_latest_version_ios: str = ""
    app_latest_version_android: str = ""
    maintenance_mode: bool = False
    maintenance_message: str = (
        "GH Trust is undergoing scheduled maintenance. Please try again shortly."
    )
    support_phone: str = ""
    support_email: str = ""
    # WhatsApp number in international format, e.g. 2348012345678 (opens wa.me/<number>).
    support_whatsapp: str = ""
    support_hours: str = "Monday to Friday, 8am to 5pm"
    # Comma-separated optional modules shown in the app: wallet, savings,
    # investments, contributions, food_basket. Loans are always on.
    feature_flags: str = ""

    # Dojah KYC
    dojah_base_url: str = "https://api.dojah.io"
    dojah_app_id: str = ""
    dojah_secret_key: str = ""
    dojah_mock: bool = True  # Use sandbox mock when keys missing or mock=true
    # Mock mode only: the phone number the sandbox BVN identity reports, so you can
    # register in development and receive/enter codes for your own number.
    dojah_mock_phone: str = ""
    # Account opening also matches a selfie against the BVN photo (after the SMS code).
    dojah_selfie_required: bool = True
    # Dojah's match cutoff, 50–100 (Dojah's own default is 90).
    dojah_selfie_threshold: int = Field(default=90, ge=50, le=100)
    dojah_selfie_max_attempts: int = 3
    # Before matching, the capture must pass Dojah's liveness check (a real face, not a
    # photo of a photo or a screen). A failed check uses up a selfie attempt.
    dojah_liveness_required: bool = True
    dojah_liveness_min_probability: float = Field(default=0.5, ge=0, le=1)
    # After the last failed selfie, that BVN can't start sign-up again for this long.
    dojah_selfie_cooldown_minutes: int = 60

    # Payment rail: monnify (default), stanbic, paystack, or zest
    payment_provider: str = "monnify"

    # Zest Payments (https://www.zestpayment.com/developers)
    zest_base_url: str = "https://api.dev.gateway.zestpayment.com/payment-engine"
    zest_public_key: str = ""
    zest_secret_key: str = ""
    zest_mock: bool = True
    # AES key/IV for encrypting authData (Notion doc). IV from Zest dashboard; key defaults to secret without SK_ prefix.
    zest_auth_encryption_key: str = ""
    zest_auth_encryption_iv: str = ""
    zest_dynamic_vas_request_type: str = "GENERATE_TEMPORARY_VIRTUAL_ACCOUNT"
    zest_transfer_status_vas_request_type: str = "TRANSFER_PAYMENT_STATUS"
    zest_va_expiry_minutes: int = 5

    # Monnify (https://developers.monnify.com/api)
    monnify_base_url: str = "https://sandbox.monnify.com"
    monnify_api_key: str = ""
    monnify_secret_key: str = ""
    monnify_contract_code: str = ""
    monnify_wallet_account_number: str = ""
    monnify_mock: bool = True
    monnify_webhook_ip_check: bool = False

    # Stanbic IBTC bank partner (https://developer.stanbicibtc.com/sandbox/)
    # Contract unconfirmed — see app/integrations/stanbic/constants.py
    stanbic_base_url: str = "https://api.sandbox.stanbicibtc.com"
    stanbic_token_url: str = ""  # set for OAuth2 client-credentials; blank = IBM key pair
    stanbic_client_id: str = ""
    stanbic_client_secret: str = ""
    stanbic_merchant_id: str = ""
    stanbic_settlement_account_number: str = ""
    stanbic_webhook_secret: str = ""
    stanbic_mock: bool = True

    # Paystack (legacy / optional — https://paystack.com/docs/api/)
    paystack_base_url: str = "https://api.paystack.co"
    paystack_secret_key: str = ""
    paystack_public_key: str = ""
    paystack_mock: bool = True
    paystack_preferred_bank: str = "test-bank"  # test-bank in sandbox; live bank slug in prod

    # OTP
    otp_length: int = 6
    otp_expire_seconds: int = 600  # 10 minutes
    otp_max_attempts: int = 5
    sms_mock: bool = True  # Log OTP to console in dev
    # Development test mode (APP_ENV=development with SMS_MOCK=true only): OTP
    # responses include the code so a dev build of the app can fill it in.
    otp_dev_echo: bool = True
    # Test deployments (e.g. a staging server the mobile team tests against): with SMS
    # mocked, no text is ever sent, so return the code to the app instead. Opt-in, and
    # ignored in production (which refuses SMS_MOCK anyway).
    otp_test_echo: bool = False
    # Demo sign-in (testers, app-store review; see app/core/demo.py). These numbers get
    # DEMO_OTP instead of an SMS. In production staff sign-in never uses it, money can't
    # leave a demo account, and the code must not be guessable (no 000000 or 123456).
    demo_phones: str = ""
    demo_otp: str = ""
    # Test servers only: these 11-digit BVNs simulate sign-up without Dojah (made-up
    # identity, face check passes, code is DEMO_OTP). Entering one again starts over.
    demo_bvns: str = ""
    # Optional PINs `scripts/seed.py` gives demo customers, so reviewers skip PIN setup.
    demo_login_pin: str = ""
    demo_transaction_pin: str = ""

    # Rate limits (requests per window). Disabled automatically when APP_ENV=development.
    rate_limit_enabled: bool = True
    rate_limit_bvn_per_ip_hour: int = 5
    rate_limit_bvn_per_bvn_day: int = 3
    rate_limit_otp_send_per_phone_15min: int = 3
    rate_limit_otp_send_per_ip_hour: int = 10
    rate_limit_otp_verify_per_ip_hour: int = 20
    rate_limit_login_request_per_phone_15min: int = 5
    # Every API request, per client IP (webhooks and health checks exempt).
    rate_limit_api_per_ip_minute: int = 300

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "ghtrust"
    postgres_password: str = "ghtrust_secret"
    postgres_db: str = "ghtrust_mfb"
    database_url: str | None = None
    # Connection pool per API process: total connections ≈ workers × (size + overflow).
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800  # drop connections before proxies/idle timeouts kill them
    db_statement_timeout_ms: int = 15000  # no single query may hold a connection longer than this

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_task_always_eager: bool = False

    default_branch: str = "Lagos Main"

    upload_dir: str = "uploads"
    max_upload_size_mb: int = 30
    # JSON bodies above this are refused before parsing (uploads use max_upload_size_mb).
    max_json_body_kb: int = 256
    # The sign-up selfie sends several camera frames as base64 JSON, far over the
    # general JSON limit; only that endpoint gets this allowance.
    max_selfie_body_mb: int = 30

    # Error tracking. Empty = disabled. Events carry no request bodies or PII.
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.0

    # Seeded super admin (first staff). No defaults: scripts/seed.py refuses to
    # run until these are set, so no real person's details live in source.
    seed_super_admin_name: str = ""
    seed_super_admin_email: str = ""
    seed_super_admin_phone: str = ""

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    def production_config_errors(self) -> list[str]:
        """Misconfigurations that must block a production boot."""
        errors: list[str] = []
        if not self.is_production:
            return errors
        if self.secret_key in _INSECURE_SECRETS or len(self.secret_key) < 32:
            errors.append("SECRET_KEY is a default/placeholder or shorter than 32 characters")
        if self.debug:
            errors.append("DEBUG must be false")
        if self.sms_mock:
            errors.append("SMS_MOCK must be false (customers would never receive OTPs)")
        elif not self.sms_provider:
            errors.append("SMS_PROVIDER must be set when SMS_MOCK=false")
        elif self.sms_provider.strip().lower() not in SUPPORTED_SMS_PROVIDERS:
            errors.append(f"SMS_PROVIDER '{self.sms_provider}' is not supported (use: termii)")
        elif not (self.termii_api_key and self.termii_sender_id):
            errors.append("Termii needs TERMII_API_KEY and TERMII_SENDER_ID")
        if self.dojah_mock or not self.dojah_enabled:
            errors.append("Dojah must be live: set DOJAH_APP_ID, DOJAH_SECRET_KEY and DOJAH_MOCK=false")
        if not self.payment_rail_enabled:
            errors.append(
                f"Payment provider '{self.active_payment_provider}' is in mock mode or missing credentials"
            )
        if not self.active_webhook_secret:
            errors.append(
                f"Webhook signing secret for '{self.active_payment_provider}' is not configured"
            )
        if any("localhost" in o or "127.0.0.1" in o for o in self.cors_origin_list):
            errors.append("CORS_ORIGINS contains localhost")
        if any(not o.startswith("https://") for o in self.cors_origin_list):
            errors.append("CORS_ORIGINS must all be https:// (the staff refresh cookie is Secure)")
        if self.enable_api_docs:
            errors.append("ENABLE_API_DOCS must be false (publishes the full API surface)")
        # Both default to localhost. On a hosted deploy that boots "healthy" and then
        # fails every sign-in, so name the variable instead.
        if _is_local_url(self.async_database_url):
            errors.append("DATABASE_URL points at localhost: set it to the production Postgres")
        if _is_local_url(self.redis_url):
            errors.append("REDIS_URL points at localhost: set it to the production Redis")
        if _is_local_url(self.celery_broker_url) or _is_local_url(self.celery_result_backend):
            errors.append(
                "CELERY_BROKER_URL / CELERY_RESULT_BACKEND point at localhost: set them to the production Redis"
            )
        if self.demo_bvns.strip():
            errors.append("DEMO_BVNS must be empty in production (it opens accounts without identity checks)")
        if self.demo_phones.strip():
            from app.core.demo import weak_code

            code = self.demo_otp.strip()
            if not (code.isdigit() and len(code) == self.otp_length):
                errors.append(f"DEMO_PHONES is set, so DEMO_OTP must be {self.otp_length} digits")
            elif weak_code(code):
                errors.append("DEMO_OTP is guessable (all one digit or a run like 123456): pick another")
        # Savings, investments, contributions and food basket have no account flows yet
        # (their endpoints return 501), so the app must not be told they're on.
        unbuilt = sorted(
            f.strip() for f in self.feature_flags.split(",") if f.strip() and f.strip() not in LIVE_FEATURES
        )
        if unbuilt:
            errors.append(
                f"FEATURE_FLAGS includes modules that aren't built yet: {', '.join(unbuilt)} "
                f"(allowed: {', '.join(LIVE_FEATURES)})"
            )
        return errors

    @property
    def active_webhook_secret(self) -> str:
        provider = self.active_payment_provider
        if provider == "paystack":
            return self.paystack_secret_key
        if provider == "zest":
            return self.zest_secret_key
        if provider == "stanbic":
            return self.stanbic_webhook_secret
        return self.monnify_secret_key

    @property
    def expose_dev_otp(self) -> bool:
        """
        Echo OTP codes to the client. Only ever with mocked SMS (the code reaches no phone
        anyway), never in production: local development by default, or a test deployment
        that opts in with OTP_TEST_ECHO=true.
        """
        if not self.sms_mock or self.is_production:
            return False
        if self.app_env == "development":
            return self.otp_dev_echo
        return self.otp_test_echo

    @property
    def rate_limits_active(self) -> bool:
        """Production/test enforce limits; development is unrestricted for local UX."""
        if self.app_env == "development":
            return False
        return self.rate_limit_enabled

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def async_database_url(self) -> str:
        if self.database_url:
            # Hosts (Railway, Heroku, Render) hand out postgres:// or postgresql:// URLs;
            # the async engine needs the asyncpg driver named in the scheme.
            url = self.database_url
            for plain in ("postgres://", "postgresql://"):
                if url.startswith(plain):
                    return "postgresql+asyncpg://" + url[len(plain) :]
            return url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        url = self.async_database_url
        return url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def dojah_enabled(self) -> bool:
        return bool(self.dojah_app_id and self.dojah_secret_key) and not self.dojah_mock

    @property
    def paystack_enabled(self) -> bool:
        return bool(self.paystack_secret_key) and not self.paystack_mock

    @property
    def monnify_enabled(self) -> bool:
        return (
            bool(self.monnify_api_key and self.monnify_secret_key and self.monnify_contract_code)
            and not self.monnify_mock
        )

    @property
    def stanbic_enabled(self) -> bool:
        return bool(self.stanbic_client_id and self.stanbic_client_secret) and not self.stanbic_mock

    @property
    def zest_enabled(self) -> bool:
        return bool(self.zest_public_key and self.zest_secret_key) and not self.zest_mock

    @property
    def active_payment_provider(self) -> str:
        return self.payment_provider.lower()

    @property
    def payment_rail_enabled(self) -> bool:
        provider = self.active_payment_provider
        if provider == "paystack":
            return self.paystack_enabled
        if provider == "zest":
            return self.zest_enabled
        if provider == "stanbic":
            return self.stanbic_enabled
        return self.monnify_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
