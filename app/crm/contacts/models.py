"""Customer contact ORM model."""

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class Contact(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Person belonging to a customer."""

    __tablename__ = "contacts"
    __table_args__ = (
        Index(
            "uq_contacts_tenant_id_customer_primary_active",
            "tenant_id",
            "customer_id",
            unique=True,
            postgresql_where=text("is_primary IS TRUE AND deleted_at IS NULL"),
        ),
    )

    customer_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
