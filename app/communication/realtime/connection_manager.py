"""In-process WebSocket connection registry and bus fan-out."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from fastapi import WebSocket

from app.communication.realtime.tickets import WsTicketPayload
from app.integrations.realtime.bus import RealtimeBus, get_realtime_bus

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WsConnection:
    websocket: WebSocket
    user: WsTicketPayload
    conn_id: str


class ConnectionManager:
    def __init__(self, bus: RealtimeBus | None = None) -> None:
        self._bus = bus or get_realtime_bus()
        self._connections: dict[str, WsConnection] = {}
        self._channel_members: dict[str, set[str]] = defaultdict(set)
        self._conn_channels: dict[str, set[str]] = defaultdict(set)
        self._bus_handlers: dict[str, int] = defaultdict(int)
        self._bus_unsubscribers: dict[str, list] = defaultdict(list)
        self._started = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._started:
            return
        await self._bus.start()
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        self._connections.clear()
        self._channel_members.clear()
        self._conn_channels.clear()
        self._bus_handlers.clear()
        self._bus_unsubscribers.clear()
        await self._bus.stop()
        self._started = False

    async def register(self, websocket: WebSocket, conn_id: str, user: WsTicketPayload) -> None:
        await websocket.accept()
        self._connections[conn_id] = WsConnection(
            websocket=websocket,
            user=user,
            conn_id=conn_id,
        )

    async def disconnect(self, conn_id: str) -> None:
        channels = list(self._conn_channels.get(conn_id, set()))
        for channel in channels:
            await self.unsubscribe(conn_id, channel)
        self._connections.pop(conn_id, None)
        self._conn_channels.pop(conn_id, None)

    async def subscribe(self, conn_id: str, channel: str) -> None:
        if conn_id not in self._connections:
            return
        if channel in self._conn_channels[conn_id]:
            return
        self._conn_channels[conn_id].add(channel)
        self._channel_members[channel].add(conn_id)
        async with self._lock:
            if self._bus_handlers[channel] == 0:

                async def handler(bus_channel: str, payload: str) -> None:
                    await self._deliver(bus_channel, payload)

                unsub = await self._bus.subscribe(channel, handler)
                self._bus_unsubscribers[channel].append(unsub)
            self._bus_handlers[channel] += 1

    async def unsubscribe(self, conn_id: str, channel: str) -> None:
        if channel not in self._conn_channels.get(conn_id, set()):
            return
        self._conn_channels[conn_id].discard(channel)
        members = self._channel_members.get(channel)
        if members is not None:
            members.discard(conn_id)
            if not members:
                self._channel_members.pop(channel, None)
        async with self._lock:
            if self._bus_handlers.get(channel, 0) <= 0:
                return
            self._bus_handlers[channel] -= 1
            if self._bus_handlers[channel] == 0:
                self._bus_handlers.pop(channel, None)
                for unsub in self._bus_unsubscribers.pop(channel, []):
                    unsub()

    async def _deliver(self, channel: str, payload: str) -> None:
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("Invalid realtime payload on channel=%s", channel)
            return
        frame = {"op": "event", "event": event}
        for conn_id in list(self._channel_members.get(channel, set())):
            connection = self._connections.get(conn_id)
            if connection is None:
                continue
            try:
                await connection.websocket.send_json(frame)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to deliver to conn=%s channel=%s", conn_id, channel)

    async def send_json(self, conn_id: str, payload: dict) -> None:
        connection = self._connections.get(conn_id)
        if connection is None:
            return
        await connection.websocket.send_json(payload)

    def get_user(self, conn_id: str) -> WsTicketPayload | None:
        connection = self._connections.get(conn_id)
        return connection.user if connection else None


_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


def reset_connection_manager_for_tests() -> None:
    global _manager
    _manager = None
