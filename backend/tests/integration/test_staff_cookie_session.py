"""Web-portal session: httpOnly refresh cookie, cookie-only sign-out, idle timeout."""

from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

from sqlalchemy import select

from app.core.security import hash_token
from app.modules.auth.models import AuthSession
from tests.integration.test_loan_workflow_api import _seed
from tests.conftest import TEST_ADMIN_PHONE, TEST_OTP

COOKIE = "ghtrust_staff_rt"
WEB = {"X-Token-Transport": "cookie"}


def _cookie(res) -> tuple[str | None, str]:
    """(value, raw Set-Cookie header) for the refresh cookie."""
    for raw in res.headers.get_list("set-cookie"):
        jar = SimpleCookie()
        jar.load(raw)
        if COOKIE in jar:
            return jar[COOKIE].value, raw
    return None, ""


async def _web_login(api_client, admin_token):  # admin_token seeds the super admin
    await api_client.post("/api/v1/admin/auth/login/request-otp", json={"phone": TEST_ADMIN_PHONE})
    res = await api_client.post(
        "/api/v1/admin/auth/login/verify-otp", json={"phone": TEST_ADMIN_PHONE, "otp": TEST_OTP}, headers=WEB
    )
    assert res.status_code == 200, res.text
    return res


async def test_cookie_transport_keeps_refresh_token_out_of_js(api_client, admin_token):
    res = await _web_login(api_client, admin_token)
    body = res.json()
    token, raw = _cookie(res)

    assert body["access_token"] and body["refresh_token"] is None
    assert token
    lowered = raw.lower()
    assert "httponly" in lowered and "samesite=strict" in lowered and "path=/api/v1/admin/auth" in lowered
    assert "max-age" not in lowered and "expires" not in lowered  # browser-session cookie


async def test_refresh_and_logout_with_cookie_only(api_client, admin_token):
    token, _ = _cookie(await _web_login(api_client, admin_token))

    refreshed = await api_client.post("/api/v1/admin/auth/token/refresh", headers={"Cookie": f"{COOKIE}={token}"})
    assert refreshed.status_code == 200, refreshed.text
    new_token, _ = _cookie(refreshed)
    assert refreshed.json()["refresh_token"] is None and new_token and new_token != token
    access = refreshed.json()["access_token"]
    assert (await api_client.get("/api/v1/admin/auth/me", headers={"Authorization": f"Bearer {access}"})).status_code == 200

    # Sign-out needs no access token — the cookie is enough — and clears the cookie.
    out = await api_client.post("/api/v1/admin/auth/logout", headers={"Cookie": f"{COOKIE}={new_token}"})
    assert out.status_code == 204
    _, cleared = _cookie(out)
    assert 'max-age=0' in cleared.lower() or "expires=" in cleared.lower()

    again = await api_client.post("/api/v1/admin/auth/token/refresh", headers={"Cookie": f"{COOKIE}={new_token}"})
    assert again.status_code == 401


async def test_refresh_without_any_token_is_401(api_client):
    res = await api_client.post("/api/v1/admin/auth/token/refresh")
    assert res.status_code == 401
    assert res.json()["code"] == "REFRESH_TOKEN_INVALID"


async def test_idle_staff_session_cannot_be_refreshed(api_client, db_session, admin_token):
    token, _ = _cookie(await _web_login(api_client, admin_token))

    session = (
        await db_session.execute(select(AuthSession).where(AuthSession.refresh_token_hash == hash_token(token)))
    ).scalar_one()
    session.last_used_at = datetime.now(timezone.utc) - timedelta(minutes=31)  # default timeout is 30 minutes
    await db_session.commit()

    res = await api_client.post("/api/v1/admin/auth/token/refresh", headers={"Cookie": f"{COOKIE}={token}"})
    assert res.status_code == 401
    assert res.json()["code"] == "SESSION_IDLE_TIMEOUT"
    await db_session.refresh(session)
    assert session.revoked_at is not None and session.revoked_reason == "idle_timeout"


async def test_large_responses_are_gzipped(api_client, db_session, admin_headers):
    await _seed(db_session)  # loan products: a multi-KB JSON list
    res = await api_client.get("/api/v1/admin/loans/products", headers={**admin_headers, "Accept-Encoding": "gzip"})
    assert res.status_code == 200 and len(res.json()) > 1
    assert res.headers.get("content-encoding") == "gzip"
