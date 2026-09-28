"""Task label ORM model."""

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class TaskLabel(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Tenant-scoped label for tasks."""

    __tablename__ = "task_labels"
    __table_args__ = (
        Index(
            "uq_task_labels_tenant_id_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'gray'"))
