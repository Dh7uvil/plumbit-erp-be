"""Charge type ORM model."""

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class ChargeType(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Import/export charge taxonomy with GL default and inventoriable toggle."""

    __tablename__ = "charge_types"
    __table_args__ = (
        Index(
            "uq_charge_types_tenant_id_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_inventoriable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    default_account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    allocation_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    default_tax_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("taxes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    applies_to: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'BOTH'")
    )
