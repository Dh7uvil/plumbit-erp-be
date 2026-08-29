"""Unit of measure ORM model."""

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class Unit(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Unit of measure used on products and quote lines."""

    __tablename__ = "units"
    __table_args__ = (
        Index(
            "uq_units_tenant_id_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
