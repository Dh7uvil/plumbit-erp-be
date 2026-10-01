"""Durable outbox handler for Agora signaling publish retries."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from uuid import UUID

from app.common.outbox.models import OutboxEvent
from app.communication.shared.signaling_publisher import publish_realtime_event
from app.core.config import get_settings
from app.integrations.agora.events import RealtimeEvent

logger = logging.getLogger(__name__)

SIGNALING_PUBLISH_EVENT = "communication.signaling.publish"


def parse_realtime_event(payload: dict[str, object]) -> RealtimeEvent | None:
    raw = payload.get("event")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw, dict):
        data = raw
    else:
        return None

    def _uuid(value: object) -> UUID | None:
        if value is None:
            return None
        try:
            return UUID(str(value))
        except ValueError:
            return None

    def _dt(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    event_data = data.get("data")
    return RealtimeEvent(
        v=int(data.get("v", 1)),
        type=str(data.get("type", "")),
        tenant_id=_uuid(data.get("tenant_id")),
        conversation_id=_uuid(data.get("conversation_id")),
        seq=data.get("seq") if isinstance(data.get("seq"), int) else None,
        actor_id=_uuid(data.get("actor_id")),
        at=_dt(data.get("at")),
        data=event_data if isinstance(event_data, dict) else {},
        truncated=bool(data.get("truncated", False)),
        event_id=_uuid(data.get("event_id")),
    )


async def handle_signaling_publish(event: OutboxEvent) -> None:
    settings = get_settings()
    if not settings.feature_communication_enabled:
        return
    payload = event.payload or {}
    realtime = parse_realtime_event(payload)
    if realtime is None:
        logger.warning("signaling_outbox_invalid_payload event_id=%s", event.id)
        return
    published = await publish_realtime_event(realtime)
    if not published:
        raise RuntimeError(f"signaling publish failed for event type={realtime.type}")
