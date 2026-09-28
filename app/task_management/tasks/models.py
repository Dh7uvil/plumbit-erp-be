"""Task ORM models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin


class TaskNumberCounter(TenantModel):
    """Per-tenant counter for TASK-##### allocation."""

    __tablename__ = "task_number_counters"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_task_number_counters_tenant_id"),)

    next_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )


class Task(AuditUserMixin, SoftDeleteTenantModel):
    """Org-wide task with optional link to any ERP/CRM record."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index(
            "uq_tasks_tenant_id_task_number_active",
            "tenant_id",
            "task_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_tasks_tenant_status_sort", "tenant_id", "status", "sort_order"),
        Index("ix_tasks_tenant_assignee_due", "tenant_id", "assignee_id", "due_at"),
        Index(
            "ix_tasks_tenant_related",
            "tenant_id",
            "related_entity_type",
            "related_entity_id",
        ),
        Index("ix_tasks_tenant_parent", "tenant_id", "parent_id"),
        Index("ix_tasks_tenant_type", "tenant_id", "task_type"),
    )

    task_number: Mapped[str] = mapped_column(String(20), nullable=False)
    task_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'TASK'")
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'TODO'"))
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'MEDIUM'")
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignee_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    related_entity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    related_entity_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )


class TaskChecklistItem(TenantModel):
    """Checklist row on a task."""

    __tablename__ = "task_checklist_items"
    __table_args__ = (Index("ix_task_checklist_items_tenant_task", "tenant_id", "task_id"),)

    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class TaskComment(AuditUserMixin, SoftDeleteTenantModel):
    """Comment on a task."""

    __tablename__ = "task_comments"
    __table_args__ = (Index("ix_task_comments_tenant_task", "tenant_id", "task_id"),)

    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)


class TaskWatcher(TenantModel):
    """User watching a task."""

    __tablename__ = "task_watchers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "task_id",
            "user_id",
            name="uq_task_watchers_tenant_task_user",
        ),
    )

    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )


class TaskLabelLink(TenantModel):
    """Many-to-many link between tasks and labels."""

    __tablename__ = "task_label_links"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "task_id",
            "label_id",
            name="uq_task_label_links_tenant_task_label",
        ),
    )

    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    label_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("task_labels.id", ondelete="CASCADE"),
        nullable=False,
    )
