"""Connection manager delivery tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.communication.realtime.connection_manager import ConnectionManager
from app.communication.realtime.tickets import WsTicketPayload
from app.integrations.realtime.bus import InProcessBus
from uuid import UUID


@pytest.mark.asyncio
async def test_connection_manager_delivers_bus_events() -> None:
    bus = InProcessBus()
    manager = ConnectionManager(bus)
    await manager.start()

    websocket = AsyncMock()
    user = WsTicketPayload(
        user_id=UUID(int=1),
        tenant_id=UUID(int=2),
        token_version=1,
    )
    await manager.register(websocket, "conn-1", user)
    await manager.subscribe("conn-1", "test-channel")

    event = {"type": "message.created", "data": {"body": "hello"}}
    await bus.publish("test-channel", json.dumps(event))

    websocket.send_json.assert_called()
    frame = websocket.send_json.call_args.args[0]
    assert frame["op"] == "event"
    assert frame["event"]["type"] == "message.created"

    await manager.stop()
