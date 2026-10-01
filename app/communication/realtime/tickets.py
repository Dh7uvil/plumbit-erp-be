"""Single-use WebSocket connection tickets."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.core.config import Settings, get_settings

_TICKET_PREFIX = "ws:ticket:"
_TICKET_TTL_SECONDS = 60
_memory_tickets: dict[str, tuple[str, float]] = {}


@dataclass(frozen=True, slots=True)
class WsTicketPayload:
    user_id: UUID
    tenant_id: UUID
    token_version: int


async def create_ws_ticket(
    *,
    user_id: UUID,
    tenant_id: UUID,
    token_version: int,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    ticket = uuid4().hex
    payload = json.dumps(
        {
            "user_id": str(user_id),
            "tenant_id": str(tenant_id),
            "token_version": token_version,
        }
    )
    if settings.redis_url:
        import redis.asyncio as redis

        client = redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.setex(f"{_TICKET_PREFIX}{ticket}", _TICKET_TTL_SECONDS, payload)
        finally:
            await client.close()
    else:
        _memory_tickets[ticket] = (payload, time.time() + _TICKET_TTL_SECONDS)
    return ticket


async def consume_ws_ticket(
    ticket: str,
    *,
    settings: Settings | None = None,
) -> WsTicketPayload | None:
    settings = settings or get_settings()
    raw: str | None = None
    if settings.redis_url:
        import redis.asyncio as redis

        client = redis.from_url(settings.redis_url, decode_responses=True)
        key = f"{_TICKET_PREFIX}{ticket}"
        try:
            raw = await client.getdel(key)
        finally:
            await client.close()
    else:
        entry = _memory_tickets.pop(ticket, None)
        if entry is None:
            return None
        payload, expires_at = entry
        if time.time() > expires_at:
            return None
        raw = payload

    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return WsTicketPayload(
            user_id=UUID(str(data["user_id"])),
            tenant_id=UUID(str(data["tenant_id"])),
            token_version=int(data["token_version"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def clear_ws_tickets_for_tests() -> None:
    _memory_tickets.clear()
