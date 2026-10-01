"""Realtime event envelope for Agora Signaling."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

_MAX_PAYLOAD_BYTES = 32 * 1024


@dataclass(slots=True)
class RealtimeEvent:
    v: int = 1
    type: str = ""
    tenant_id: UUID | None = None
    conversation_id: UUID | None = None
    seq: int | None = None
    actor_id: UUID | None = None
    at: datetime | None = None
    data: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    event_id: UUID | None = None

    def to_json(self) -> str:
        payload = asdict(self)
        for key in ("tenant_id", "conversation_id", "actor_id", "event_id"):
            value = payload.get(key)
            if isinstance(value, UUID):
                payload[key] = str(value)
        at = payload.get("at")
        if isinstance(at, datetime):
            payload["at"] = at.isoformat()
        encoded = json.dumps(payload, separators=(",", ":"), default=str)
        if len(encoded.encode("utf-8")) <= _MAX_PAYLOAD_BYTES:
            return encoded
        return truncate_event_json(payload)


def truncate_event_json(payload: dict[str, Any]) -> str:
    """Shrink an event payload to fit Agora's 32 KB limit."""

    data = payload.get("data")
    if isinstance(data, dict):
        body = data.get("body")
        if isinstance(body, str) and len(body) > 500:
            data = {**data, "body": body[:500]}
    slim = {**payload, "data": data if isinstance(data, dict) else {}, "truncated": True}
    encoded = json.dumps(slim, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) <= _MAX_PAYLOAD_BYTES:
        return encoded
    slim["data"] = {}
    return json.dumps(slim, separators=(",", ":"), default=str)
