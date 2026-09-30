"""The API creates the configured admin and demo customers on start-up, without the seed script."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.bootstrap import ensure_configured_accounts
from app.modules.admin.models import Staff
from app.modules.admin.service import seed_super_admin
from app.modules.users.models import Customer
from tests.conftest import refresh_settings


def _configure(monkeypatch, **env):
    base = {
        "SEED_SUPER_ADMIN_NAME": "Super Admin",
        "SEED_SUPER_ADMIN_EMAIL": "admin@ghtrust.test",
        "SEED_SUPER_ADMIN_PHONE": "08012345678",
        "DEMO_PHONES": "08012345678,09011223344",
        "DEMO_OTP": "482917",
    }
    for key, value in {**base, **env}.items():
        monkeypatch.setenv(key, value)
    refresh_settings()


async def _staff(db_engine) -> list[Staff]:
    async with async_sessionmaker(db_engine, class_=AsyncSession)() as s:
        return list((await s.execute(select(Staff))).scalars())


async def _customers(db_engine) -> list[Customer]:
    async with async_sessionmaker(db_engine, class_=AsyncSession)() as s:
        return list((await s.execute(select(Customer))).scalars())


async def test_startup_creates_the_admin_and_demo_customers(db_engine, monkeypatch):
    _configure(monkeypatch)
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    await ensure_configured_accounts(factory)
    await ensure_configured_accounts(factory)  # every restart: no duplicates

    staff = await _staff(db_engine)
    assert [(s.phone, s.is_super_admin) for s in staff] == [("+2348012345678", True)]
    # The admin's number stays staff; only the other demo number becomes a customer.
    assert [c.phone_primary for c in await _customers(db_engine)] == ["+2349011223344"]


async def test_admin_signs_in_with_the_demo_code_after_startup(api_client, db_engine, monkeypatch):
    _configure(monkeypatch)
    # api_client shares this in-memory database through its session.
    await ensure_configured_accounts(async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False))
    await api_client.post("/api/v1/admin/auth/login/request-otp", json={"phone": "08012345678"})
    res = await api_client.post(
        "/api/v1/admin/auth/login/verify-otp", json={"phone": "08012345678", "otp": "482917"}
    )
    assert res.status_code == 200, res.text


async def test_configured_admin_is_created_even_if_another_super_admin_exists(db_session):
    await seed_super_admin(db_session, full_name="Old", email="old@ghtrust.test", phone="08000000001")
    await seed_super_admin(db_session, full_name="New", email="new@ghtrust.test", phone="08012345678")
    phones = sorted((await db_session.execute(select(Staff.phone))).scalars())
    assert phones == ["+2348000000001", "+2348012345678"]


async def test_changing_the_phone_moves_the_same_admin(db_session):
    first = await seed_super_admin(db_session, full_name="A", email="admin@ghtrust.test", phone="08000000001")
    again = await seed_super_admin(db_session, full_name="A", email="admin@ghtrust.test", phone="08012345678")
    assert again.id == first.id and again.phone == "+2348012345678"
    assert len((await db_session.execute(select(Staff))).scalars().all()) == 1


async def test_bad_demo_settings_never_stop_startup(db_engine, monkeypatch):
    _configure(monkeypatch, DEMO_LOGIN_PIN="12")
    await ensure_configured_accounts(async_sessionmaker(db_engine, class_=AsyncSession))
    # Nothing committed, but no exception either: the log names the problem.
    assert await _staff(db_engine) == []


async def test_nothing_configured_does_nothing(db_engine):
    await ensure_configured_accounts(async_sessionmaker(db_engine, class_=AsyncSession))
    assert await _staff(db_engine) == []
