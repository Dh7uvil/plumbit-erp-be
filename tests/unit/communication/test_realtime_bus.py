"""Realtime bus and Redis signaling client tests."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.communication.shared.signaling_publisher import build_event
from app.core.config import get_settings
from app.integrations.realtime.bus import InProcessBus, reset_realtime_bus_for_tests
from app.integrations.realtime.client import RedisRealtimeClient, reset_redis_realtime_client_for_tests


@pytest.fixture(autouse=True)
def reset_realtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_COMMUNICATION_ENABLED", "true")
    reset_realtime_bus_for_tests()
    reset_redis_realtime_client_for_tests()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_inprocess_bus_delivers_to_subscriber() -> None:
    bus = InProcessBus()
    await bus.start()
    received: list[tuple[str, str]] = []

    async def handler(channel: str, payload: str) -> None:
        received.append((channel, payload))

    unsub = await bus.subscribe("u-test", handler)
    await bus.publish("u-test", '{"type":"ping"}')
    assert received == [("u-test", '{"type":"ping"}')]
    unsub()
    await bus.stop()


@pytest.mark.asyncio
async def test_redis_realtime_client_records_events() -> None:
    client = RedisRealtimeClient()
    event = build_event(
        event_type="message.created",
        tenant_id=UUID(int=1),
        conversation_id=UUID(int=2),
        seq=1,
        data={"id": "msg-1", "body": "hello"},
    )
    await client.publish(channel="u-inbox", sender_id="sender", event=event)
    assert len(client.events) == 1
    assert client.events[0][0] == "u-inbox"
