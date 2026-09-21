"""Lost reason ORM model."""

from sqlalchemy import Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class LostReason(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Reason recorded when an opportunity is lost."""

    __tablename__ = "crm_lost_reasons"
    __table_args__ = (
        Index(
            "uq_crm_lost_reasons_tenant_id_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
