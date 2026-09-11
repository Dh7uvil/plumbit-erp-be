"""Sales invoice ORM models. AR document; stock already moved by the delivery note."""

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


class SalesInvoice(AuditUserMixin, SoftDeleteTenantModel):
    """Draft-or-posted sales invoice. Post writes AR/revenue/VAT, not stock."""

    __tablename__ = "sales_invoices"
    __table_args__ = (
        Index(
            "uq_sales_invoices_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_sales_invoices_tenant_id_status", "tenant_id", "status"),
        Index("ix_sales_invoices_tenant_id_invoice_date", "tenant_id", "invoice_date"),
        Index("ix_sales_invoices_tenant_id_customer_id", "tenant_id", "customer_id"),
        Index("ix_sales_invoices_tenant_id_sales_order_id", "tenant_id", "sales_order_id"),
        Index(
            "ix_sales_invoices_tenant_id_source_quotation_id",
            "tenant_id",
            "source_quotation_id",
        ),
        Index(
            "ix_sales_invoices_tenant_id_source_proforma_invoice_id",
            "tenant_id",
            "source_proforma_invoice_id",
        ),
        Index("ix_sales_invoices_tenant_id_payment_status", "tenant_id", "payment_status"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
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
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    salesperson_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    sales_order_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_quotation_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("quotations.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_proforma_invoice_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("proforma_invoices.id", ondelete="SET NULL"),
        nullable=True,
    )
    payment_terms_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payment_terms.id", ondelete="SET NULL"),
        nullable=True,
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tax_treatment: Mapped[str] = mapped_column(String(30), nullable=False)
    place_of_supply: Mapped[str] = mapped_column(String(30), nullable=False)
    is_export: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
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
    exchange_rate: Mapped[Decimal] = mapped_column(_RATE, nullable=False)
    discount_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    discount_value: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    discount_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    shipping_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    adjustment_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    subtotal: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    tax_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    round_off_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    grand_total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    foreign_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    base_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    bill_to_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    ship_to_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_and_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    bl_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    container_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    amount_paid: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    amount_credited: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    balance_due: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    payment_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'UNPAID'")
    )
    cogs_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    cogs_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'NOT_APPLICABLE'")
    )
    journal_entry_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    reversal_journal_entry_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    export_evidence_ok: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    export_evidence_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    lines: Mapped[list["SalesInvoiceLine"]] = relationship(
        back_populates="sales_invoice",
        cascade="all, delete-orphan",
        order_by="SalesInvoiceLine.line_number",
    )


class SalesInvoiceLine(TenantModel):
    """Sales invoice line with source-document links and COGS snapshot."""

    __tablename__ = "sales_invoice_lines"
    __table_args__ = (
        UniqueConstraint(
            "sales_invoice_id",
            "line_number",
            name="uq_sales_invoice_lines_header_line_number",
        ),
        Index("ix_sales_invoice_lines_sales_invoice_id", "sales_invoice_id"),
        Index("ix_sales_invoice_lines_sales_order_line_id", "sales_order_line_id"),
        Index("ix_sales_invoice_lines_delivery_note_line_id", "delivery_note_line_id"),
        Index("ix_sales_invoice_lines_source_quotation_line_id", "source_quotation_line_id"),
        Index(
            "ix_sales_invoice_lines_source_proforma_invoice_line_id",
            "source_proforma_invoice_line_id",
        ),
    )

    sales_invoice_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_invoices.id", ondelete="CASCADE"),
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
    sales_order_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_order_lines.id", ondelete="RESTRICT"),
        nullable=True,
    )
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
    delivery_note_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("delivery_notes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    delivery_note_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("delivery_note_lines.id", ondelete="RESTRICT"),
        nullable=True,
    )
    discount_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    discount_value: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    discount_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    tax_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("taxes.id", ondelete="SET NULL"),
        nullable=True,
    )
    tax_rate: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    tax_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    income_account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    cogs_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    cogs_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'NOT_APPLICABLE'")
    )
    qty_credited: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    carton_qty: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    packing_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cbm: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    weight: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    item_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

    sales_invoice: Mapped[SalesInvoice] = relationship(back_populates="lines")
