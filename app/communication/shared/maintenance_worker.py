"""Periodic communication maintenance (presence TTL, stale calls)."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from app.common.utils.datetime import utcnow
from app.communication.calls.models import Call
from app.communication.calls.repository import CallParticipantRepository
from app.communication.presence.models import UserPresence
from app.communication.shared.signaling_publisher import (
    build_event,
    flush_pending_signaling,
    schedule_signaling_event,
)
from app.core.config import get_settings
from app.core.enums import CallParticipantStatus, CallStatus, PresenceStatus
from app.db.session import async_session_factory, transaction
from app.integrations.realtime.presence import get_presence_connection_store

logger = logging.getLogger(__name__)


async def run_communication_maintenance() -> None:
    settings = get_settings()
    if not settings.feature_communication_enabled:
        return
    await sweep_stale_presence(settings.presence_offline_after_seconds)
    await sweep_stale_active_calls()


async def sweep_stale_presence(offline_after_seconds: int) -> None:
    cutoff = utcnow() - timedelta(seconds=offline_after_seconds)
    settings = get_settings()
    presence_store = get_presence_connection_store(settings)
    async with async_session_factory() as session:
        async with transaction(session):
            stmt = select(UserPresence).where(
                UserPresence.status != PresenceStatus.OFFLINE.value,
            )
            candidates = list((await session.execute(stmt)).scalars().all())
            rows: list[UserPresence] = []
            for row in candidates:
                if await presence_store.is_online(row.tenant_id, row.user_id):
                    continue
                heartbeat_stale = (
                    row.last_heartbeat_at is None or row.last_heartbeat_at < cutoff
                )
                if heartbeat_stale:
                    rows.append(row)
            now = utcnow()
            for row in rows:
                row.status = PresenceStatus.OFFLINE.value
                row.last_seen_at = row.last_heartbeat_at or now
                schedule_signaling_event(
                    session,
                    build_event(
                        event_type="presence.changed",
                        tenant_id=row.tenant_id,
                        actor_id=row.user_id,
                        data={
                            "user_id": str(row.user_id),
                            "status": PresenceStatus.OFFLINE.value,
                            "custom_status": row.custom_status,
                            "last_seen_at": (row.last_seen_at or now).isoformat(),
                        },
                    ),
                )
            if rows:
                logger.info("presence_sweep marked_offline=%s", len(rows))
        await flush_pending_signaling(session)


async def sweep_stale_active_calls() -> None:
    """Finalize ACTIVE calls that no longer have any JOINED participants."""

    async with async_session_factory() as session:
        async with transaction(session):
            participants_repo = CallParticipantRepository(session)
            stmt = select(Call).where(Call.status == CallStatus.ACTIVE.value)
            calls = list((await session.execute(stmt)).scalars().all())
            if not calls:
                return

            from app.communication.calls.service import CallService

            call_service = CallService(session)
            finalized = 0
            for call in calls:
                parts = await participants_repo.list_for_call(call.tenant_id, call.id)
                joined = [
                    part
                    for part in parts
                    if part.status == CallParticipantStatus.JOINED.value
                ]
                if joined:
                    continue
                await call_service._finalize_call(
                    call.tenant_id,
                    call,
                    reason="all_left",
                    actor_user_id=None,
                )
                finalized += 1
            if finalized:
                logger.info("call_sweep finalized_active=%s", finalized)
        await flush_pending_signaling(session)
