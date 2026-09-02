"""Idempotency key storage."""

from typing import Any

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantModel


class IdempotencyKey(TenantModel):
    """Tenant-scoped replay record for Idempotency-Key headers."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_idempotency_keys_tenant_id_key"),
    )

    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
