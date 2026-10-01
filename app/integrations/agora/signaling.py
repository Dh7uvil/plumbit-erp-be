"""Realtime signaling client protocol and test double."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.core.config import Settings, get_settings
from app.integrations.agora.events import RealtimeEvent


class SignalingClient(Protocol):
    async def publish(
        self,
        *,
        channel: str,
        sender_id: str,
        event: RealtimeEvent,
    ) -> None: ...


class NullSignalingClient:
    """Records published events in memory for tests and local dev."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, RealtimeEvent]] = []

    async def publish(
        self,
        *,
        channel: str,
        sender_id: str,
        event: RealtimeEvent,
    ) -> None:
        self.events.append((channel, sender_id, event))

    def clear(self) -> None:
        self.events.clear()


_null_client: NullSignalingClient | None = None


def get_null_signaling_client() -> NullSignalingClient:
    global _null_client
    if _null_client is None:
        _null_client = NullSignalingClient()
    return _null_client


def get_signaling_client(settings: Settings | None = None) -> SignalingClient:
    settings = settings or get_settings()
    if settings.feature_communication_enabled:
        from app.integrations.realtime.client import get_redis_realtime_client

        return get_redis_realtime_client(settings)
    return get_null_signaling_client()


def system_sender_id(tenant_id: UUID) -> str:
    return f"system-{tenant_id}"
