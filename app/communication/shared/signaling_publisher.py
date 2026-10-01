"""Post-commit Agora signaling publish helpers."""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.integrations.agora.events import RealtimeEvent
from app.integrations.agora.identity import ChatIdentityService
from app.integrations.agora.signaling import (
    SignalingClient,
    get_signaling_client,
    system_sender_id,
)

logger = logging.getLogger(__name__)

_PENDING_KEY = "communication_signaling_events"
_OUTBOX_KEY = "communication_signaling_outbox_specs"


def schedule_signaling_event(session: AsyncSession, event: RealtimeEvent) -> None:
    session.sync_session.info.setdefault(_PENDING_KEY, []).append(event)
    if event.tenant_id is not None and event.event_id is not None:
        session.sync_session.info.setdefault(_OUTBOX_KEY, []).append(event)


async def enqueue_scheduled_signaling_outbox(session: AsyncSession) -> None:
    """Persist pending signaling events to the transactional outbox before commit."""

    specs: list[RealtimeEvent] = session.sync_session.info.pop(_OUTBOX_KEY, [])
    if not specs:
        return
    from app.common.outbox.service import OutboxService
    from app.communication.shared.signaling_outbox_handlers import SIGNALING_PUBLISH_EVENT

    outbox = OutboxService(session)
    for event in specs:
        if event.tenant_id is None or event.event_id is None:
            continue
        await outbox.enqueue(
            event.tenant_id,
            event_type=SIGNALING_PUBLISH_EVENT,
            aggregate_type="signaling",
            aggregate_id=event.event_id,
            payload={"event": event.to_json()},
            dedupe_key=str(event.event_id),
        )


def schedule_inbox_signaling_events(
    session: AsyncSession,
    event: RealtimeEvent,
    *,
    participant_user_ids: list[UUID],
    actor_user_id: UUID,
) -> None:
    """Publish one conversation event plus inbox copies for every other participant."""
    schedule_signaling_event(session, event)
    for user_id in participant_user_ids:
        if user_id == actor_user_id:
            continue
        schedule_signaling_event(
            session,
            build_event(
                event_type=event.type,
                tenant_id=event.tenant_id,  # type: ignore[arg-type]
                actor_id=event.actor_id,
                conversation_id=event.conversation_id,
                seq=event.seq,
                data={**event.data, "target_user_id": str(user_id)},
            ),
        )


async def publish_realtime_event(
    event: RealtimeEvent,
    *,
    client: SignalingClient | None = None,
) -> bool:
    """Publish one realtime event. Returns True when Agora accepted the message."""

    settings = get_settings()
    if not settings.feature_communication_enabled:
        return True
    channel = _channel_for_event(event)
    if channel is None:
        return True
    signaling = client or get_signaling_client(settings)
    async with async_session_factory() as session:
        identity = ChatIdentityService(session)
        sender = await _resolve_signaling_sender(identity, event, {})
        return await _publish_one(signaling, channel=channel, sender=sender, event=event)


async def _mark_signaling_outbox_done(session: AsyncSession, event: RealtimeEvent) -> None:
    if event.tenant_id is None or event.event_id is None:
        return
    from app.common.outbox.repository import OutboxRepository
    from app.common.outbox.service import OutboxService
    from app.communication.shared.signaling_outbox_handlers import SIGNALING_PUBLISH_EVENT
    from app.core.enums import OutboxStatus

    repo = OutboxRepository(session)
    row = await repo.get_by_dedupe(
        event.tenant_id, SIGNALING_PUBLISH_EVENT, str(event.event_id)
    )
    if row is not None and row.status == OutboxStatus.PENDING.value:
        await OutboxService(session).succeed(row.id)


async def _publish_one(
    signaling: SignalingClient,
    *,
    channel: str,
    sender: str,
    event: RealtimeEvent,
    session: AsyncSession | None = None,
) -> bool:
    for attempt in range(2):
        started = time.perf_counter()
        try:
            await signaling.publish(channel=channel, sender_id=sender, event=event)
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "Published signaling event type=%s channel=%s seq=%s elapsed_ms=%.1f",
                event.type,
                channel,
                event.seq,
                elapsed_ms,
            )
            if session is not None:
                try:
                    await _mark_signaling_outbox_done(session, event)
                except Exception:
                    logger.warning(
                        "Could not mark signaling outbox row done for event type=%s",
                        event.type,
                        exc_info=True,
                    )
            return True
        except Exception as exc:  # noqa: BLE001 - publish must never fail the API response
            elapsed_ms = (time.perf_counter() - started) * 1000
            if attempt == 0:
                await asyncio.sleep(0.25)
                continue
            logger.warning(
                "Failed to publish signaling event type=%s channel=%s seq=%s "
                "after retry elapsed_ms=%.1f: %s",
                event.type,
                channel,
                event.seq,
                elapsed_ms,
                exc,
            )
            return False
    return False


async def flush_pending_signaling(
    session: AsyncSession,
    *,
    client: SignalingClient | None = None,
) -> None:
    pending: list[RealtimeEvent] = session.sync_session.info.pop(_PENDING_KEY, [])
    if not pending:
        return
    settings = get_settings()
    if not settings.feature_communication_enabled:
        return
    signaling = client or get_signaling_client(settings)
    identity = ChatIdentityService(session)
    sender_cache: dict[tuple[UUID, UUID], str] = {}
    publish_tasks: list[asyncio.Task[bool]] = []
    for event in pending:
        channel = _channel_for_event(event)
        if channel is None:
            continue
        sender = await _resolve_signaling_sender(identity, event, sender_cache)
        publish_tasks.append(
            asyncio.create_task(
                _publish_one(
                    signaling,
                    channel=channel,
                    sender=sender,
                    event=event,
                    session=session,
                )
            )
        )
    if publish_tasks:
        await asyncio.gather(*publish_tasks)


async def _resolve_signaling_sender(
    identity: ChatIdentityService,
    event: RealtimeEvent,
    cache: dict[tuple[UUID, UUID], str],
) -> str:
    if event.actor_id is None or event.tenant_id is None:
        return system_sender_id(event.tenant_id)  # type: ignore[arg-type]
    cache_key = (event.tenant_id, event.actor_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    mapping = await identity.get_or_create_mapping(event.tenant_id, event.actor_id)
    cache[cache_key] = mapping.agora_user_id
    return mapping.agora_user_id


def _channel_for_event(event: RealtimeEvent) -> str | None:
    from uuid import UUID

    from app.integrations.agora.channels import (
        conversation_channel_name,
        inbox_channel_name,
        presence_channel_name,
    )

    inbox_target_types = {
        "call.invited",
        "call.ended",
        "call.missed",
        "call.rejected",
        "call.accepted",
        "message.created",
        "message.read",
        "message.delivered",
    }
    if event.type in inbox_target_types:
        target_user_id = event.data.get("target_user_id")
        if target_user_id:
            return inbox_channel_name(UUID(str(target_user_id)))

    if event.type == "presence.changed" and event.tenant_id:
        return presence_channel_name(event.tenant_id)

    if event.conversation_id and event.tenant_id:
        if event.type.startswith("call."):
            return conversation_channel_name(event.tenant_id, event.conversation_id)
        if event.type in {
            "message.created",
            "message.updated",
            "message.deleted",
            "message.read",
            "message.delivered",
            "message.reaction_changed",
            "message.pinned",
            "typing.started",
            "typing.stopped",
        }:
            return conversation_channel_name(event.tenant_id, event.conversation_id)
        if event.type.startswith("conversation.") or event.type.startswith("participant."):
            return conversation_channel_name(event.tenant_id, event.conversation_id)
    return None


def build_event(
    *,
    event_type: str,
    tenant_id: UUID,
    actor_id: UUID | None = None,
    conversation_id: UUID | None = None,
    seq: int | None = None,
    data: dict | None = None,
) -> RealtimeEvent:
    from app.common.utils.datetime import utcnow

    from uuid import uuid4

    event_id = uuid4()
    payload = {**(data or {}), "event_id": str(event_id)}
    return RealtimeEvent(
        type=event_type,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        seq=seq,
        actor_id=actor_id,
        at=utcnow(),
        data=payload,
        event_id=event_id,
    )
