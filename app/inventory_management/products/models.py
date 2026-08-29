"""Product ORM model."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class Product(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """Sellable good or service."""

    __tablename__ = "products"
    __table_args__ = (
        Index(
            "uq_products_tenant_id_sku_active",
            "tenant_id",
            "sku",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    item_type: Mapped[str] = mapped_column(String(30), nullable=False)
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sales_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    selling_rate: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    tax_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("taxes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    hs_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    track_inventory: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
