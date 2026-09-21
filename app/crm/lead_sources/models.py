"""Lead source ORM model."""

from sqlalchemy import Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class LeadSource(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """CRM lead attribution source master."""

    __tablename__ = "crm_lead_sources"
    __table_args__ = (
        Index(
            "uq_crm_lead_sources_tenant_id_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
