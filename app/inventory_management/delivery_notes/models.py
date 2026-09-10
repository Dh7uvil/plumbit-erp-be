"""Delivery note document models."""

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


class DeliveryNote(AuditUserMixin, SoftDeleteTenantModel):
    """Draft-or-posted sales dispatch. Posted rows consume stock and FIFO layers."""

    __tablename__ = "delivery_notes"
    __table_args__ = (
        Index(
            "uq_delivery_notes_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_delivery_notes_tenant_id_status", "tenant_id", "status"),
        Index("ix_delivery_notes_tenant_id_document_date", "tenant_id", "document_date"),
        Index("ix_delivery_notes_tenant_id_customer_id", "tenant_id", "customer_id"),
        Index("ix_delivery_notes_sales_order_id", "sales_order_id"),
        Index("ix_delivery_notes_shipment_id", "shipment_id"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    sales_order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    customer_id: Mapped[UUID] = mapped_column(
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
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    shipment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True,
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
    vehicle_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    driver_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    driver_contact: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    lines: Mapped[list["DeliveryNoteLine"]] = relationship(
        back_populates="delivery_note",
        cascade="all, delete-orphan",
        order_by="DeliveryNoteLine.line_number",
    )


class DeliveryNoteLine(TenantModel):
    """Dispatched quantity against one sales order line."""

    __tablename__ = "delivery_note_lines"
    __table_args__ = (
        UniqueConstraint(
            "delivery_note_id",
            "line_number",
            name="uq_delivery_note_lines_header_line_number",
        ),
        Index("ix_delivery_note_lines_delivery_note_id", "delivery_note_id"),
        Index("ix_delivery_note_lines_sales_order_line_id", "sales_order_line_id"),
        Index("ix_delivery_note_lines_tenant_id_product_id", "tenant_id", "product_id"),
    )

    delivery_note_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("delivery_notes.id", ondelete="CASCADE"),
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
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    unit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("units.id", ondelete="RESTRICT"),
        nullable=True,
    )
    rate: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    qty_invoiced: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))

    delivery_note: Mapped[DeliveryNote] = relationship(back_populates="lines")
