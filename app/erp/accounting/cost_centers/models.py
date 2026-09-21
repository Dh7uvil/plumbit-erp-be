"""Cost center ORM model."""

from sqlalchemy import Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class CostCenter(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Reporting dimension (cost center / department tag) for journal lines."""

    __tablename__ = "cost_centers"
    __table_args__ = (
        Index(
            "uq_cost_centers_tenant_id_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
