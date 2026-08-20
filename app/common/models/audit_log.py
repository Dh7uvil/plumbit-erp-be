"""Append-only audit trail model."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantScopedMixin, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """Tenant-owned, append-only record of a meaningful state change or auth event."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_audit_logs_tenant_id_action", "tenant_id", "action"),
        Index("ix_audit_logs_tenant_id_module", "tenant_id", "module"),
        Index("ix_audit_logs_tenant_id_user_id", "tenant_id", "user_id"),
    )

    user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    module: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'SUCCESS'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
