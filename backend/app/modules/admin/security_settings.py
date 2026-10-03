"""
Staff session timeout.

- The organisation's idle timeout: one value for every staff member, changed by a super
  admin in the portal (Settings > Security), 5 to 60 minutes. Until someone changes it,
  STAFF_SESSION_IDLE_MINUTES (default 30).
- Each staff member may pick a shorter one for themselves, never a longer one.
- "Idle" means no real activity: the portal reports clicks, typing and navigation to
  POST /admin/auth/activity (at most about once a minute). Token refreshes and background
  polling don't count, so a portal left open on a screen still signs out.

Enforced by the server on every staff request (admin/deps.py) and on token refresh.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.admin.models import Staff, SystemSetting

logger = structlog.get_logger()

STAFF_IDLE_KEY = "staff_session_idle_minutes"
MIN_IDLE_MINUTES = 5
MAX_IDLE_MINUTES = 60


@dataclass(frozen=True)
class OrgTimeout:
    minutes: int
    updated_at: datetime | None
    updated_by: str | None  # staff id


def _clamp(minutes: int) -> int:
    return max(MIN_IDLE_MINUTES, min(MAX_IDLE_MINUTES, int(minutes)))


async def org_timeout(db: AsyncSession) -> OrgTimeout:
    row = await db.get(SystemSetting, STAFF_IDLE_KEY)
    if row is None or not isinstance(row.value, int):
        return OrgTimeout(_clamp(get_settings().staff_session_idle_minutes), None, None)
    return OrgTimeout(_clamp(row.value), row.updated_at, row.updated_by)


def effective_minutes(org_minutes: int, staff: Staff | None) -> int:
    personal = staff.session_idle_minutes if staff else None
    return min(org_minutes, personal) if personal else org_minutes


async def staff_idle_minutes(db: AsyncSession, staff_id: str) -> int:
    org = (await org_timeout(db)).minutes
    return effective_minutes(org, await db.get(Staff, staff_id))


async def set_org_timeout(db: AsyncSession, minutes: int, by: Staff) -> OrgTimeout:
    before = (await org_timeout(db)).minutes
    row = await db.get(SystemSetting, STAFF_IDLE_KEY)
    now = datetime.now(timezone.utc)
    if row is None:
        row = SystemSetting(key=STAFF_IDLE_KEY, value=minutes, updated_by=by.id, updated_at=now)
        db.add(row)
    else:
        row.value = minutes
        row.updated_by = by.id
        row.updated_at = now
    await db.flush()
    logger.info("security_setting_changed", key=STAFF_IDLE_KEY, old=before, new=minutes, staff_id=by.id)
    return OrgTimeout(minutes, now, by.id)


async def staff_name(db: AsyncSession, staff_id: str | None) -> str | None:
    if not staff_id:
        return None
    return await db.scalar(select(Staff.full_name).where(Staff.id == staff_id))
