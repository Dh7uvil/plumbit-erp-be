"""Sales order ORM models."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
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


class SalesOrder(AuditUserMixin, SoftDeleteTenantModel):
    """Sales order header with snapshotted FX and address text."""

    __tablename__ = "sales_orders"
    __table_args__ = (
        Index(
            "uq_sales_orders_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_sales_orders_tenant_id_status", "tenant_id", "status"),
        Index("ix_sales_orders_tenant_id_order_date", "tenant_id", "order_date"),
        Index("ix_sales_orders_tenant_id_customer_id", "tenant_id", "customer_id"),
        Index(
            "ix_sales_orders_tenant_id_customer_id_customer_po_number",
            "tenant_id",
            "customer_id",
            "customer_po_number",
        ),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'DRAFT'"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    reference_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_shipment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    warehouse_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_trn: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_treatment: Mapped[str] = mapped_column(String(30), nullable=False)
    place_of_supply: Mapped[str] = mapped_column(String(30), nullable=False)
    currency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    base_currency_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("currencies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, 6),
        nullable=False,
    )
    price_list_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("price_lists.id", ondelete="SET NULL"),
        nullable=True,
    )
    payment_terms_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payment_terms.id", ondelete="SET NULL"),
        nullable=True,
    )
    salesperson_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_and_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    bill_to_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    ship_to_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    discount_value: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    discount_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    shipping_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    adjustment_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    subtotal: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    tax_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    grand_total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    foreign_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    base_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    fulfillment_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'NOT_DELIVERED'"),
    )
    billing_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'NOT_INVOICED'"),
    )
    source_quotation_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("quotations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_proforma_invoice_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("proforma_invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_po_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    customer_po_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[UUID | None] = mapped_column(
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
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    lines: Mapped[list["SalesOrderLine"]] = relationship(
        back_populates="sales_order",
        cascade="all, delete-orphan",
        order_by="SalesOrderLine.line_number",
    )


class SalesOrderLine(TenantModel):
    """Sales order line with snapshotted tax and fulfillment quantities."""

    __tablename__ = "sales_order_lines"
    __table_args__ = (
        UniqueConstraint(
            "sales_order_id",
            "line_number",
            name="uq_sales_order_lines_header_line_number",
        ),
        Index("ix_sales_order_lines_sales_order_id", "sales_order_id"),
    )

    sales_order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    unit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
    )
    rate: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    discount_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    discount_value: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    discount_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    tax_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("taxes.id", ondelete="SET NULL"),
        nullable=True,
    )
    tax_rate: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    tax_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    qty_delivered: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_returned: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_reserved: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_invoiced: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    source_quotation_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("quotation_lines.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_proforma_invoice_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("proforma_invoice_lines.id", ondelete="SET NULL"),
        nullable=True,
    )

    sales_order: Mapped[SalesOrder] = relationship(back_populates="lines")
