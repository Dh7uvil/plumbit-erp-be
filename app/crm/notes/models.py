"""Note ORM model."""

from uuid import UUID

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin


class Note(AuditUserMixin, SoftDeleteTenantModel):
    """User note attached to a CRM record."""

    __tablename__ = "crm_notes"
    __table_args__ = (
        Index(
            "ix_crm_notes_tenant_related",
            "tenant_id",
            "related_entity_type",
            "related_entity_id",
        ),
    )

    body: Mapped[str] = mapped_column(Text, nullable=False)
    related_entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    related_entity_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
