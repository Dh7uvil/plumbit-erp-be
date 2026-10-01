"""Redis-backed live connection presence."""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_CONN_KEY_PREFIX = "presence:conns:"
_CONN_TTL_SECONDS = 120


def _conn_key(tenant_id: UUID, user_id: UUID) -> str:
    return f"{_CONN_KEY_PREFIX}{tenant_id}:{user_id}"


class PresenceConnectionStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._memory: dict[str, int] = {}

    async def _redis(self):
        import redis.asyncio as redis

        url = self._settings.redis_url
        if not url:
            return None
        return redis.from_url(url, decode_responses=True)

    async def increment(self, tenant_id: UUID, user_id: UUID) -> tuple[int, bool]:
        """Return (count, became_online)."""
        key = _conn_key(tenant_id, user_id)
        redis = await self._redis()
        if redis is None:
            previous = self._memory.get(key, 0)
            count = previous + 1
            self._memory[key] = count
            return count, previous == 0
        try:
            count = await redis.incr(key)
            await redis.expire(key, _CONN_TTL_SECONDS)
            return count, count == 1
        finally:
            await redis.close()

    async def decrement(self, tenant_id: UUID, user_id: UUID) -> tuple[int, bool]:
        """Return (count, became_offline)."""
        key = _conn_key(tenant_id, user_id)
        redis = await self._redis()
        if redis is None:
            previous = self._memory.get(key, 0)
            count = max(0, previous - 1)
            if count == 0:
                self._memory.pop(key, None)
            else:
                self._memory[key] = count
            return count, previous > 0 and count == 0
        try:
            count = await redis.decr(key)
            if count <= 0:
                await redis.delete(key)
                return 0, True
            await redis.expire(key, _CONN_TTL_SECONDS)
            return count, False
        finally:
            await redis.close()

    async def refresh(self, tenant_id: UUID, user_id: UUID) -> None:
        key = _conn_key(tenant_id, user_id)
        redis = await self._redis()
        if redis is None:
            if key in self._memory:
                return
            return
        try:
            if await redis.exists(key):
                await redis.expire(key, _CONN_TTL_SECONDS)
        finally:
            await redis.close()

    async def is_online(self, tenant_id: UUID, user_id: UUID) -> bool:
        key = _conn_key(tenant_id, user_id)
        redis = await self._redis()
        if redis is None:
            return self._memory.get(key, 0) > 0
        try:
            count = await redis.get(key)
            return bool(count and int(count) > 0)
        finally:
            await redis.close()

    async def list_online_user_ids(self, tenant_id: UUID, user_ids: list[UUID]) -> set[UUID]:
        online: set[UUID] = set()
        for user_id in user_ids:
            if await self.is_online(tenant_id, user_id):
                online.add(user_id)
        return online


_store: PresenceConnectionStore | None = None


def get_presence_connection_store(settings: Settings | None = None) -> PresenceConnectionStore:
    global _store
    if _store is None:
        _store = PresenceConnectionStore(settings)
    return _store


def reset_presence_connection_store_for_tests() -> None:
    global _store
    if _store is not None:
        _store._memory.clear()
    _store = None
