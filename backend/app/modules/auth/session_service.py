"""
Device sessions and refresh-token rotation.

Flow for a client:
  1. OTP verify → access_token (15 min) + refresh_token (30 days) + session_id
  2. Access token expires → POST /auth/token/refresh with the refresh token
     → a NEW access + refresh pair; the old refresh token stops working.
  3. POST /auth/logout → session revoked; access token dies on next request.

Reuse detection: if an already-rotated refresh token is presented, someone
else holds a copy of it, so the whole session is revoked (both the thief and
the legitimate device must sign in again). A short grace window tolerates the
benign case of one client firing two refreshes at once.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.security import (
    TOKEN_TYPE_CUSTOMER,
    TOKEN_TYPE_STAFF,
    create_access_token,
    generate_refresh_token,
    hash_token,
)
from app.modules.auth.models import AuthSession, SubjectType
from app.modules.auth.schemas import DeviceInfo, TokenPair

logger = structlog.get_logger()


def as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; Postgres returns aware ones."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class RequestMeta:
    ip: str | None = None
    user_agent: str | None = None


def _refresh_ttl(subject_type: SubjectType) -> timedelta:
    settings = get_settings()
    if subject_type == SubjectType.STAFF:
        return timedelta(hours=settings.staff_refresh_token_hours)
    return timedelta(days=settings.customer_refresh_token_days)


def _token_type(subject_type: SubjectType) -> str:
    return TOKEN_TYPE_STAFF if subject_type == SubjectType.STAFF else TOKEN_TYPE_CUSTOMER


class SessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Issue ───────────────────────────────────────────────────────────────

    async def issue(
        self,
        *,
        subject_type: SubjectType,
        subject_id: str,
        phone: str | None = None,
        is_super_admin: bool = False,
        device: DeviceInfo | None = None,
        meta: RequestMeta | None = None,
    ) -> TokenPair:
        now = datetime.now(timezone.utc)
        meta = meta or RequestMeta()

        # Signing in again on the same device replaces that device's session.
        if device and device.device_id:
            await self.db.execute(
                update(AuthSession)
                .where(
                    AuthSession.subject_type == subject_type,
                    AuthSession.subject_id == subject_id,
                    AuthSession.device_id == device.device_id,
                    AuthSession.revoked_at.is_(None),
                )
                .values(revoked_at=now, revoked_reason="replaced")
            )

        refresh_token = generate_refresh_token()
        session = AuthSession(
            subject_type=subject_type,
            subject_id=subject_id,
            refresh_token_hash=hash_token(refresh_token),
            device_id=device.device_id if device else None,
            device_name=device.device_name if device else None,
            platform=device.platform if device else None,
            app_version=device.app_version if device else None,
            ip_address=meta.ip,
            user_agent=(meta.user_agent or "")[:255] or None,
            last_used_at=now,
            expires_at=now + _refresh_ttl(subject_type),
        )
        self.db.add(session)
        await self.db.flush()
        return self._pair(session, refresh_token, phone=phone, is_super_admin=is_super_admin)

    # ── Rotate ──────────────────────────────────────────────────────────────

    async def rotate(
        self,
        refresh_token: str,
        *,
        subject_type: SubjectType,
        meta: RequestMeta | None = None,
    ) -> tuple[AuthSession, str]:
        """Validate a refresh token and rotate it. Returns (session, new_refresh_token)."""
        now = datetime.now(timezone.utc)
        presented = hash_token(refresh_token)

        result = await self.db.execute(
            select(AuthSession)
            .where(
                AuthSession.refresh_token_hash == presented,
                AuthSession.subject_type == subject_type,
            )
            .with_for_update()
        )
        session = result.scalar_one_or_none()

        if session is None:
            await self._handle_unknown_refresh(presented, subject_type, now)
            raise AppError(
                status.HTTP_401_UNAUTHORIZED,
                ErrorCode.REFRESH_TOKEN_INVALID,
                "Session expired. Please sign in again.",
            )

        if session.revoked_at is not None:
            raise AppError(
                status.HTTP_401_UNAUTHORIZED,
                ErrorCode.SESSION_REVOKED,
                "Session ended. Please sign in again.",
            )
        if as_utc(session.expires_at) <= now:
            await self.revoke(session, reason="expired")
            # Commit before raising: the request's error path rolls back.
            await self.db.commit()
            raise AppError(
                status.HTTP_401_UNAUTHORIZED,
                ErrorCode.REFRESH_TOKEN_INVALID,
                "Session expired. Please sign in again.",
            )

        await self.end_if_idle(session, now=now)

        new_token = generate_refresh_token()
        session.previous_refresh_token_hash = presented
        session.refresh_token_hash = hash_token(new_token)
        session.rotated_at = now
        # A staff session's last_used_at marks real activity (see touch()); a refresh happens
        # on a timer, so it doesn't count. Customer sessions have no idle limit.
        if session.subject_type != SubjectType.STAFF:
            session.last_used_at = now
        if meta and meta.ip:
            session.ip_address = meta.ip
        await self.db.flush()
        return session, new_token

    async def _handle_unknown_refresh(
        self, presented: str, subject_type: SubjectType, now: datetime
    ) -> None:
        result = await self.db.execute(
            select(AuthSession).where(
                AuthSession.previous_refresh_token_hash == presented,
                AuthSession.subject_type == subject_type,
                AuthSession.revoked_at.is_(None),
            )
        )
        reused = result.scalar_one_or_none()
        if reused is None:
            return

        grace = timedelta(seconds=get_settings().refresh_token_reuse_grace_seconds)
        # Strict: a grace of 0 means none, even when both requests land in the same
        # clock tick (Windows clocks tick every ~15 ms).
        if reused.rotated_at and now - as_utc(reused.rotated_at) < grace:
            # Concurrent refresh from the same client: the other request already
            # rotated. Reject this one without killing the session; the client
            # should retry with the token it just stored.
            return

        await self.revoke(reused, reason="refresh_token_reuse")
        # Must persist even though this request fails: the error path rolls
        # back, which would otherwise resurrect a session we know is stolen.
        await self.db.commit()
        logger.warning(
            "refresh_token_reuse_detected",
            session_id=reused.id,
            subject_type=subject_type.value,
        )
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.REFRESH_TOKEN_REUSED,
            "This session was signed out for your security. Please sign in again.",
        )

    def pair_for(
        self,
        session: AuthSession,
        refresh_token: str,
        *,
        phone: str | None = None,
        is_super_admin: bool = False,
    ) -> TokenPair:
        return self._pair(session, refresh_token, phone=phone, is_super_admin=is_super_admin)

    def _pair(
        self,
        session: AuthSession,
        refresh_token: str,
        *,
        phone: str | None,
        is_super_admin: bool,
    ) -> TokenPair:
        access_token, expires_in = create_access_token(
            session.subject_id,
            typ=_token_type(session.subject_type),
            session_id=session.id,
            phone=phone,
            is_super_admin=is_super_admin,
        )
        refresh_expires_in = int(
            (as_utc(session.expires_at) - datetime.now(timezone.utc)).total_seconds()
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            refresh_expires_in=max(refresh_expires_in, 0),
            session_id=session.id,
        )

    # ── Idle timeout (staff) ────────────────────────────────────────────────

    async def idle_limit(self, session: AuthSession) -> timedelta | None:
        """Staff sessions end after inactivity (set in the portal); customer sessions don't."""
        if session.subject_type != SubjectType.STAFF:
            return None
        from app.modules.admin.security_settings import staff_idle_minutes

        return timedelta(minutes=await staff_idle_minutes(self.db, session.subject_id))

    async def end_if_idle(self, session: AuthSession, *, now: datetime | None = None) -> None:
        """Revoke and refuse a session that has been idle too long. Commits on refusal."""
        limit = await self.idle_limit(session)
        now = now or datetime.now(timezone.utc)
        if limit is not None and now - as_utc(session.last_used_at) > limit:
            await self.revoke(session, reason="idle_timeout")
            # Must persist even though this request fails: the error path rolls back.
            await self.db.commit()
            raise AppError(
                status.HTTP_401_UNAUTHORIZED,
                ErrorCode.SESSION_IDLE_TIMEOUT,
                "Signed out after a period of inactivity. Please sign in again.",
            )

    async def touch(self, session: AuthSession) -> datetime:
        """Record real activity (staff portal): the idle clock starts again."""
        await self.end_if_idle(session)
        session.last_used_at = datetime.now(timezone.utc)
        await self.db.flush()
        return session.last_used_at

    # ── Validate / revoke / list ────────────────────────────────────────────

    async def is_active(self, session_id: str, *, subject_type: SubjectType, subject_id: str) -> bool:
        session = await self.db.get(AuthSession, session_id)
        return bool(
            session
            and session.revoked_at is None
            and session.subject_type == subject_type
            and session.subject_id == subject_id
            and as_utc(session.expires_at) > datetime.now(timezone.utc)
        )

    async def get_owned(
        self, session_id: str, *, subject_type: SubjectType, subject_id: str
    ) -> AuthSession:
        session = await self.db.get(AuthSession, session_id)
        if not session or session.subject_type != subject_type or session.subject_id != subject_id:
            raise AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Session not found")
        return session

    async def revoke_by_refresh_token(self, refresh_token: str, *, subject_type: SubjectType, reason: str) -> bool:
        """End the session that currently owns this refresh token. False if none matched."""
        session = (
            await self.db.execute(
                select(AuthSession).where(
                    AuthSession.refresh_token_hash == hash_token(refresh_token),
                    AuthSession.subject_type == subject_type,
                )
            )
        ).scalar_one_or_none()
        if session is None:
            return False
        await self.revoke(session, reason=reason)
        return True

    async def revoke(self, session: AuthSession, *, reason: str) -> None:
        if session.revoked_at is None:
            session.revoked_at = datetime.now(timezone.utc)
            session.revoked_reason = reason
            await self.db.flush()

    async def revoke_all(
        self,
        *,
        subject_type: SubjectType,
        subject_id: str,
        reason: str,
        except_session_id: str | None = None,
    ) -> int:
        stmt = (
            update(AuthSession)
            .where(
                AuthSession.subject_type == subject_type,
                AuthSession.subject_id == subject_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc), revoked_reason=reason)
        )
        if except_session_id:
            stmt = stmt.where(AuthSession.id != except_session_id)
        result = await self.db.execute(stmt)
        return result.rowcount or 0

    async def list_active(self, *, subject_type: SubjectType, subject_id: str) -> list[AuthSession]:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(AuthSession)
            .where(
                AuthSession.subject_type == subject_type,
                AuthSession.subject_id == subject_id,
                AuthSession.revoked_at.is_(None),
            )
            .order_by(AuthSession.last_used_at.desc())
        )
        return [s for s in result.scalars().all() if as_utc(s.expires_at) > now]
