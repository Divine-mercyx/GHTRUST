"""Staff idle timeout: set by a super admin, shortened per person, enforced on every request."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.modules.admin.models import Staff, StaffStatus
from app.modules.auth.models import AuthSession, SubjectType
from tests.conftest import TEST_OTP

SETTINGS = "/api/v1/admin/settings/security"


async def _sessions(db_session, staff_id: str | None = None) -> list[AuthSession]:
    db_session.expire_all()
    q = select(AuthSession).where(AuthSession.subject_type == SubjectType.STAFF)
    if staff_id:
        q = q.where(AuthSession.subject_id == staff_id)
    return list((await db_session.execute(q)).scalars())


async def _idle_for(db_session, minutes: int, staff_id: str | None = None) -> None:
    for s in await _sessions(db_session, staff_id):
        s.last_used_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    await db_session.commit()


async def _officer(api_client, db_session) -> dict:
    """A staff member who isn't a super admin, signed in."""
    staff = Staff(
        full_name="Loan Officer", email="officer@example.com", phone="+2348000000077",
        is_super_admin=False, status=StaffStatus.ACTIVE,
    )
    db_session.add(staff)
    await db_session.commit()
    await api_client.post("/api/v1/admin/auth/login/request-otp", json={"phone": "08000000077"})
    res = await api_client.post("/api/v1/admin/auth/login/verify-otp", json={"phone": "08000000077", "otp": TEST_OTP})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}", "id": staff.id}


class TestSetting:
    async def test_defaults_to_30_minutes(self, api_client, admin_headers):
        s = (await api_client.get(SETTINGS, headers=admin_headers)).json()
        assert (s["staff_idle_minutes"], s["effective_idle_minutes"], s["can_edit"]) == (30, 30, True)
        assert (s["min_minutes"], s["max_minutes"]) == (5, 60)

    async def test_super_admin_changes_it_within_range(self, api_client, admin_headers):
        res = await api_client.put(SETTINGS, json={"staff_idle_minutes": 10}, headers=admin_headers)
        assert res.status_code == 200, res.text
        assert res.json()["staff_idle_minutes"] == 10
        assert res.json()["updated_by_name"]  # who changed it is shown
        for bad in (4, 61):
            assert (await api_client.put(SETTINGS, json={"staff_idle_minutes": bad}, headers=admin_headers)).status_code == 422

    async def test_other_staff_cannot_change_it(self, api_client, db_session, admin_headers):
        officer = await _officer(api_client, db_session)
        headers = {"Authorization": officer["Authorization"]}
        assert (await api_client.get(SETTINGS, headers=headers)).json()["can_edit"] is False
        res = await api_client.put(SETTINGS, json={"staff_idle_minutes": 60}, headers=headers)
        assert res.status_code == 403

    async def test_staff_may_choose_shorter_never_longer(self, api_client, admin_headers):
        mine = "/api/v1/admin/auth/me/session-timeout"
        assert (await api_client.put(mine, json={"minutes": 45}, headers=admin_headers)).status_code == 422
        res = await api_client.put(mine, json={"minutes": 10}, headers=admin_headers)
        assert res.json()["effective_idle_minutes"] == 10 and res.json()["my_idle_minutes"] == 10
        res = await api_client.put(mine, json={"minutes": None}, headers=admin_headers)
        assert res.json()["effective_idle_minutes"] == 30


class TestEnforcement:
    async def test_idle_session_is_refused_on_any_request(self, api_client, db_session, admin_headers):
        await _idle_for(db_session, 31)
        res = await api_client.get("/api/v1/admin/auth/me", headers=admin_headers)
        assert res.status_code == 401 and res.json()["code"] == "SESSION_IDLE_TIMEOUT"
        assert all(s.revoked_at is not None for s in await _sessions(db_session))

    async def test_a_lower_setting_applies_at_once(self, api_client, db_session, admin_headers):
        await api_client.put(SETTINGS, json={"staff_idle_minutes": 5}, headers=admin_headers)
        await _idle_for(db_session, 6)
        assert (await api_client.get("/api/v1/admin/auth/me", headers=admin_headers)).status_code == 401

    async def test_activity_restarts_the_clock_but_requests_and_refreshes_dont(
        self, api_client, db_session, super_admin
    ):
        await api_client.post("/api/v1/admin/auth/login/request-otp", json={"phone": "08000000001"})
        login = (
            await api_client.post("/api/v1/admin/auth/login/verify-otp", json={"phone": "08000000001", "otp": TEST_OTP})
        ).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}

        await _idle_for(db_session, 20)
        before = (await _sessions(db_session))[0].last_used_at
        # Background polling and a token refresh: still idle.
        assert (await api_client.get("/api/v1/admin/dashboard", headers=headers)).status_code == 200
        refreshed = await api_client.post(
            "/api/v1/admin/auth/token/refresh", json={"refresh_token": login["refresh_token"]}
        )
        assert refreshed.status_code == 200, refreshed.text
        assert (await _sessions(db_session))[0].last_used_at == before

        # Real activity: the clock restarts.
        headers = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}
        act = await api_client.post("/api/v1/admin/auth/activity", headers=headers)
        assert act.status_code == 200, act.text
        assert act.json()["effective_idle_minutes"] == 30
        assert (await _sessions(db_session))[0].last_used_at > before

    async def test_activity_cannot_revive_an_idle_session(self, api_client, db_session, admin_headers):
        await _idle_for(db_session, 31)
        res = await api_client.post("/api/v1/admin/auth/activity", headers=admin_headers)
        assert res.status_code == 401
