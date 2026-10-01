"""Redis-backed signaling client for WebSocket transport."""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.integrations.agora.events import RealtimeEvent
from app.integrations.agora.signaling import SignalingClient
from app.integrations.realtime.bus import get_realtime_bus


class RedisRealtimeClient:
    """Publish realtime events to the Redis/in-process bus."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._bus = get_realtime_bus(self._settings)
        self.events: list[tuple[str, str, RealtimeEvent]] = []

    async def publish(
        self,
        *,
        channel: str,
        sender_id: str,
        event: RealtimeEvent,
    ) -> None:
        payload = event.to_json()
        self.events.append((channel, sender_id, event))
        await self._bus.publish(channel, payload)


_redis_client: RedisRealtimeClient | None = None


def get_redis_realtime_client(settings: Settings | None = None) -> SignalingClient:
    global _redis_client
    settings = settings or get_settings()
    if _redis_client is None:
        _redis_client = RedisRealtimeClient(settings)
    return _redis_client


def reset_redis_realtime_client_for_tests() -> None:
    global _redis_client
    if _redis_client is not None:
        _redis_client.events.clear()
    _redis_client = None
