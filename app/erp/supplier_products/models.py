"""Supplier product catalog ORM models."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE
from app.db.base import SoftDeleteTenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin


class SupplierProduct(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    """One supplier SKU, optionally mapped to a product, with a stored catalog price."""

    __tablename__ = "supplier_products"
    __table_args__ = (
        Index(
            "uq_supplier_products_tenant_supplier_sku_active",
            "tenant_id",
            "supplier_id",
            "supplier_sku_normalized",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_supplier_products_tenant_supplier_product_preferred",
            "tenant_id",
            "supplier_id",
            "product_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND is_preferred IS TRUE"),
        ),
        Index(
            "uq_supplier_products_tenant_product_preferred_supplier",
            "tenant_id",
            "product_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND is_preferred_supplier IS TRUE"),
        ),
        Index("ix_supplier_products_tenant_id_product_id", "tenant_id", "product_id"),
    )

    supplier_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    supplier_sku: Mapped[str] = mapped_column(String(80), nullable=False)
    supplier_sku_normalized: Mapped[str] = mapped_column(String(80), nullable=False)
    supplier_item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=True,
    )
    currency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    price_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_preferred: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_preferred_supplier: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
