"""Attachment ORM model."""

from uuid import UUID

from sqlalchemy import BigInteger, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin


class Attachment(AuditUserMixin, SoftDeleteTenantModel):
    """Tenant-owned file metadata for a polymorphic parent row."""

    __tablename__ = "attachments"
    __table_args__ = (
        Index("ix_attachments_tenant_entity", "tenant_id", "entity_type", "entity_id"),
        Index(
            "ix_attachments_tenant_entity_category",
            "tenant_id",
            "entity_type",
            "entity_id",
            "category",
        ),
    )

    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(150), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    thumbnail_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
