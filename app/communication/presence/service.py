"""Presence use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.datetime import utcnow
from app.communication.presence.repository import PresenceRepository
from app.communication.presence.schemas import HeartbeatRequest, PresenceResponse
from app.communication.shared.feature import require_communication_enabled
from app.communication.shared.signaling_publisher import (
    build_event,
    flush_pending_signaling,
    schedule_signaling_event,
)
from app.core.config import get_settings
from app.core.enums import PresenceStatus
from app.db.session import transaction
from app.integrations.realtime.presence import get_presence_connection_store


class PresenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PresenceRepository(session)

    async def get_presence(
        self, tenant_id: UUID, user_ids: list[UUID]
    ) -> list[PresenceResponse]:
        require_communication_enabled()
        rows = await self.repo.list_for_users(tenant_id, user_ids)
        by_user = {row.user_id: row for row in rows}
        settings = get_settings()
        online_ids: set[UUID] = set()
        store = get_presence_connection_store(settings)
        online_ids = await store.list_online_user_ids(tenant_id, user_ids)
        results: list[PresenceResponse] = []
        for user_id in user_ids:
            row = by_user.get(user_id)
            if row is None:
                status = (
                    PresenceStatus.ONLINE if user_id in online_ids else PresenceStatus.OFFLINE
                )
                results.append(
                    PresenceResponse(
                        user_id=user_id,
                        status=status,
                        custom_status=None,
                        last_seen_at=None,
                        last_heartbeat_at=None,
                    )
                )
            else:
                response = PresenceResponse.model_validate(row)
                if user_id in online_ids and response.status == PresenceStatus.OFFLINE:
                    response = response.model_copy(update={"status": PresenceStatus.ONLINE})
                results.append(response)
        return results

    async def heartbeat(
        self,
        tenant_id: UUID,
        user_id: UUID,
        payload: HeartbeatRequest,
    ) -> PresenceResponse:
        require_communication_enabled()
        now = utcnow()
        async with transaction(self.session):
            existing = await self.repo.get(tenant_id, user_id)
            status_changed = existing is None or existing.status != payload.status.value
            custom_status_changed = (
                existing is None or existing.custom_status != payload.custom_status
            )
            row = await self.repo.upsert(
                tenant_id,
                user_id,
                {
                    "status": payload.status.value,
                    "custom_status": payload.custom_status,
                    "last_heartbeat_at": now,
                    "last_seen_at": now,
                },
            )
            if status_changed or custom_status_changed:
                schedule_signaling_event(
                    self.session,
                    build_event(
                        event_type="presence.changed",
                        tenant_id=tenant_id,
                        actor_id=user_id,
                        data={
                            "user_id": str(user_id),
                            "status": payload.status.value,
                            "custom_status": payload.custom_status,
                            "last_seen_at": now.isoformat(),
                        },
                    ),
                )
        await flush_pending_signaling(self.session)
        return PresenceResponse.model_validate(row)

