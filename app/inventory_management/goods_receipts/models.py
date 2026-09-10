"""Goods receipt (GRN) document models."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
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

from app.core.constants import MONEY_PRECISION, MONEY_SCALE, QUANTITY_PRECISION, QUANTITY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin

_QTY = Numeric(QUANTITY_PRECISION, QUANTITY_SCALE)
_MONEY = Numeric(MONEY_PRECISION, MONEY_SCALE)
_RATE = Numeric(MONEY_PRECISION, 6)


class GoodsReceipt(AuditUserMixin, SoftDeleteTenantModel):
    """Draft-or-posted purchase receive. Posted rows raise stock and FIFO layers."""

    __tablename__ = "goods_receipts"
    __table_args__ = (
        Index(
            "uq_goods_receipts_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_goods_receipts_tenant_id_status", "tenant_id", "status"),
        Index("ix_goods_receipts_tenant_id_document_date", "tenant_id", "document_date"),
        Index("ix_goods_receipts_tenant_id_supplier_id", "tenant_id", "supplier_id"),
        Index(
            "ix_goods_receipts_tenant_id_supplier_id_document_date",
            "tenant_id",
            "supplier_id",
            "document_date",
        ),
        Index("ix_goods_receipts_purchase_order_id", "purchase_order_id"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    purchase_order_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tax_treatment: Mapped[str] = mapped_column(String(30), nullable=False)
    place_of_supply: Mapped[str] = mapped_column(String(30), nullable=False)
    currency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    base_currency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exchange_rate: Mapped[Decimal] = mapped_column(_RATE, nullable=False)
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    delivery_challan_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bill_of_entry_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bill_of_entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    container_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bl_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    qc_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'NOT_REQUIRED'")
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    lines: Mapped[list["GoodsReceiptLine"]] = relationship(
        back_populates="goods_receipt",
        cascade="all, delete-orphan",
        order_by="GoodsReceiptLine.line_number",
    )


class GoodsReceiptLine(TenantModel):
    """Received quantity, rate, weights, and QC buckets."""

    __tablename__ = "goods_receipt_lines"
    __table_args__ = (
        UniqueConstraint(
            "goods_receipt_id",
            "line_number",
            name="uq_goods_receipt_lines_header_line_number",
        ),
        Index("ix_goods_receipt_lines_goods_receipt_id", "goods_receipt_id"),
        Index("ix_goods_receipt_lines_purchase_order_line_id", "purchase_order_line_id"),
        Index("ix_goods_receipt_lines_tenant_id_product_id", "tenant_id", "product_id"),
    )

    goods_receipt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipts.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    purchase_order_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("purchase_order_lines.id", ondelete="SET NULL"),
        nullable=True,
    )
    product_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    supplier_product_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("supplier_products.id", ondelete="SET NULL"),
        nullable=True,
    )
    supplier_sku: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    unit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("units.id", ondelete="RESTRICT"),
        nullable=True,
    )
    rate: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    net_weight: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    gross_weight: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    qty_accepted: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_rejected: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_on_hold: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_billed: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))

    goods_receipt: Mapped[GoodsReceipt] = relationship(back_populates="lines")
