"""Reserve, replay, and store idempotent POST responses."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.idempotency.models import IdempotencyKey
from app.core.exceptions import IdempotencyConflictError, ValidationError


def require_idempotency_key(value: str | None) -> str:
    """Require a non-empty Idempotency-Key header."""

    if value is None:
        raise ValidationError("Idempotency-Key is required")
    key = value.strip()
    if not key:
        raise ValidationError("Idempotency-Key is required")
    if len(key) > 255:
        raise ValidationError("Idempotency-Key must be 255 characters or fewer")
    return key


def hash_request(*, method: str, path: str, body: bytes) -> str:
    """Fingerprint method, path, and raw body for conflict detection."""

    digest = hashlib.sha256()
    digest.update(method.upper().encode())
    digest.update(b"\n")
    digest.update(path.encode())
    digest.update(b"\n")
    digest.update(body)
    return digest.hexdigest()


class IdempotencyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def begin(
        self,
        tenant_id: UUID,
        key: str,
        request_hash: str,
        *,
        endpoint: str | None = None,
    ) -> dict[str, Any] | None:
        """Reserve the key or return a stored response.

        Returns ``None`` when this request owns the key. Returns the stored
        JSON body on replay. Raises ``IdempotencyConflictError`` when the key
        was used with a different body or is still in flight.
        """

        insert_stmt = (
            pg_insert(IdempotencyKey)
            .values(
                tenant_id=tenant_id,
                key=key,
                request_hash=request_hash,
                endpoint=endpoint,
                response_body=None,
            )
            .on_conflict_do_nothing(constraint="uq_idempotency_keys_tenant_id_key")
        )
        result = await self.session.execute(insert_stmt)
        if getattr(result, "rowcount", 0) == 1:
            return None

        existing = await self._lock(tenant_id, key)
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError()
        if existing.response_body is None:
            raise IdempotencyConflictError()
        return dict(existing.response_body)

    async def store(
        self,
        tenant_id: UUID,
        key: str,
        response_body: dict[str, Any],
    ) -> None:
        row = await self._lock(tenant_id, key)
        if row is None:
            return
        row.response_body = response_body
        await self.session.flush()

    async def _lock(self, tenant_id: UUID, key: str) -> IdempotencyKey | None:
        statement = (
            select(IdempotencyKey)
            .where(
                IdempotencyKey.tenant_id == tenant_id,
                IdempotencyKey.key == key,
            )
            .with_for_update()
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()
