"""Payment reminder (dunning) ORM models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class DunningRule(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """When to email customers about open invoice balances."""

    __tablename__ = "dunning_rules"
    __table_args__ = (
        Index(
            "uq_dunning_rules_tenant_id_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    days_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    template_key: Mapped[str] = mapped_column(String(40), nullable=False)
    escalate: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class DunningLog(TenantModel):
    """One sent reminder per invoice and rule (idempotency guard)."""

    __tablename__ = "dunning_logs"
    __table_args__ = (
        Index(
            "uq_dunning_logs_tenant_invoice_rule",
            "tenant_id",
            "sales_invoice_id",
            "dunning_rule_id",
            unique=True,
        ),
        Index("ix_dunning_logs_tenant_invoice", "tenant_id", "sales_invoice_id"),
    )

    sales_invoice_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    dunning_rule_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("dunning_rules.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'EMAIL'"))
    recipient_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
