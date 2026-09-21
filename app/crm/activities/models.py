"""Activity ORM model."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin


class Activity(AuditUserMixin, SoftDeleteTenantModel):
    """User-scheduled CRM task, call, or meeting.

    Distinct from the audit-derived `/activity` feed in `app/common/activity/`.
    """

    __tablename__ = "crm_activities"
    __table_args__ = (
        Index(
            "ix_crm_activities_tenant_related",
            "tenant_id",
            "related_entity_type",
            "related_entity_id",
        ),
        Index("ix_crm_activities_tenant_owner_due", "tenant_id", "owner_id", "due_at"),
        Index("ix_crm_activities_tenant_id_status", "tenant_id", "status"),
    )

    activity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'OPEN'"))
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'MEDIUM'")
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    related_entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    related_entity_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
