"""Realtime pub/sub bus for WebSocket fan-out."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable, Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

BusHandler = Callable[[str, str], Awaitable[None]]

_BUS_PREFIX = "rt:"


class RealtimeBus(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def publish(self, channel: str, payload: str) -> None: ...

    async def subscribe(self, channel: str, handler: BusHandler) -> Callable[[], None]: ...


class InProcessBus:
    """Single-process fan-out used when Redis is unavailable."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[BusHandler]] = defaultdict(list)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self._handlers.clear()

    async def publish(self, channel: str, payload: str) -> None:
        for handler in list(self._handlers.get(channel, [])):
            try:
                await handler(channel, payload)
            except Exception:  # noqa: BLE001
                logger.warning("InProcessBus handler failed channel=%s", channel, exc_info=True)

    async def subscribe(self, channel: str, handler: BusHandler) -> Callable[[], None]:
        self._handlers[channel].append(handler)

        def unsubscribe() -> None:
            handlers = self._handlers.get(channel, [])
            if handler in handlers:
                handlers.remove(handler)
            if not handlers and channel in self._handlers:
                del self._handlers[channel]

        return unsubscribe


class RedisRealtimeBus:
    """Cross-process fan-out via Redis pub/sub."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis = None
        self._pubsub = None
        self._listener_task: asyncio.Task[None] | None = None
        self._handlers: dict[str, list[BusHandler]] = defaultdict(list)
        self._subscribed_redis_channels: set[str] = set()
        self._lock = asyncio.Lock()

    def _redis_channel(self, channel: str) -> str:
        return f"{_BUS_PREFIX}{channel}"

    async def start(self) -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(self._redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        self._listener_task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None
        if self._pubsub is not None:
            await self._pubsub.close()
            self._pubsub = None
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
        self._handlers.clear()
        self._subscribed_redis_channels.clear()

    async def publish(self, channel: str, payload: str) -> None:
        if self._redis is None:
            return
        await self._redis.publish(self._redis_channel(channel), payload)

    async def subscribe(self, channel: str, handler: BusHandler) -> Callable[[], None]:
        async with self._lock:
            self._handlers[channel].append(handler)
            redis_channel = self._redis_channel(channel)
            if redis_channel not in self._subscribed_redis_channels and self._pubsub is not None:
                await self._pubsub.subscribe(redis_channel)
                self._subscribed_redis_channels.add(redis_channel)

        def unsubscribe() -> None:
            handlers = self._handlers.get(channel, [])
            if handler in handlers:
                handlers.remove(handler)
            if not handlers:
                self._handlers.pop(channel, None)
                redis_channel = self._redis_channel(channel)
                if redis_channel in self._subscribed_redis_channels and self._pubsub is not None:
                    asyncio.create_task(self._unsubscribe_redis(redis_channel, channel))

        return unsubscribe

    async def _unsubscribe_redis(self, redis_channel: str, channel: str) -> None:
        async with self._lock:
            if channel in self._handlers:
                return
            if self._pubsub is not None and redis_channel in self._subscribed_redis_channels:
                await self._pubsub.unsubscribe(redis_channel)
                self._subscribed_redis_channels.discard(redis_channel)

    async def _listen(self) -> None:
        assert self._pubsub is not None
        while True:
            message = await self._pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0,
            )
            if message is None:
                await asyncio.sleep(0.01)
                continue
            if message.get("type") != "message":
                continue
            redis_channel = message.get("channel")
            data = message.get("data")
            if not isinstance(redis_channel, str) or not isinstance(data, str):
                continue
            if not redis_channel.startswith(_BUS_PREFIX):
                continue
            channel = redis_channel[len(_BUS_PREFIX) :]
            for handler in list(self._handlers.get(channel, [])):
                try:
                    await handler(channel, data)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "RedisRealtimeBus handler failed channel=%s",
                        channel,
                        exc_info=True,
                    )


_bus: RealtimeBus | None = None


def get_realtime_bus(settings: Settings | None = None) -> RealtimeBus:
    global _bus
    settings = settings or get_settings()
    if _bus is None:
        if settings.redis_url:
            _bus = RedisRealtimeBus(settings.redis_url)
        else:
            _bus = InProcessBus()
    return _bus


def reset_realtime_bus_for_tests() -> None:
    global _bus
    _bus = None
