"""Recurring template ORM models."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin


class RecurringTemplate(AuditUserMixin, SoftDeleteTenantModel):
    """Schedule that generates draft sales invoices or purchase bills."""

    __tablename__ = "recurring_templates"
    __table_args__ = (
        Index("ix_recurring_templates_tenant_id_status", "tenant_id", "status"),
        Index("ix_recurring_templates_tenant_id_next_run", "tenant_id", "next_run_date"),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    document_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    interval: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    schedule_day: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    next_run_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    max_occurrences: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurrences_generated: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    template_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    last_document_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    last_document_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecurringGeneration(TenantModel):
    """One draft produced from a template. Drafts are never auto-posted."""

    __tablename__ = "recurring_generations"
    __table_args__ = (
        Index(
            "uq_recurring_generations_template_run",
            "tenant_id",
            "template_id",
            "run_date",
            unique=True,
        ),
    )

    template_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("recurring_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    document_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    document_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
