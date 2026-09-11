"""Package (carton) document models. Packing metadata only — no stock writes."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import QUANTITY_PRECISION, QUANTITY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin

_QTY = Numeric(QUANTITY_PRECISION, QUANTITY_SCALE)


class Package(AuditUserMixin, SoftDeleteTenantModel):
    """Optional carton grouped under a sales order and at most one delivery note."""

    __tablename__ = "packages"
    __table_args__ = (
        Index(
            "uq_packages_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_packages_tenant_id_status", "tenant_id", "status"),
        Index("ix_packages_sales_order_id", "sales_order_id"),
        Index("ix_packages_delivery_note_id", "delivery_note_id"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    sales_order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    delivery_note_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("delivery_notes.id", ondelete="SET NULL"),
        nullable=True,
    )
    package_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    length: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    width: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    height: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    dimension_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)
    gross_weight: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    net_weight: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    weight_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)
    shipping_marks: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    lines: Mapped[list["PackageLine"]] = relationship(
        back_populates="package",
        cascade="all, delete-orphan",
        order_by="PackageLine.line_number",
    )


class PackageLine(TenantModel):
    """Packed quantity against one sales order line."""

    __tablename__ = "package_lines"
    __table_args__ = (
        UniqueConstraint(
            "package_id",
            "line_number",
            name="uq_package_lines_header_line_number",
        ),
        Index("ix_package_lines_package_id", "package_id"),
        Index("ix_package_lines_sales_order_line_id", "sales_order_line_id"),
    )

    package_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("packages.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sales_order_line_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_order_lines.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=True,
    )
    quantity: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    unit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("units.id", ondelete="RESTRICT"),
        nullable=True,
    )
    carton_qty: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    packing_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cbm: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    weight: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    item_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

    package: Mapped[Package] = relationship(back_populates="lines")
