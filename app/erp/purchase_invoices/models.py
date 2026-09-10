"""Purchase invoice ORM models. AP document; stock already moved by the GRN."""

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


class PurchaseInvoice(AuditUserMixin, SoftDeleteTenantModel):
    """Draft-or-posted supplier bill. Post writes AP/GRNI/VAT, not stock."""

    __tablename__ = "purchase_invoices"
    __table_args__ = (
        Index(
            "uq_purchase_invoices_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_purchase_invoices_tenant_id_status", "tenant_id", "status"),
        Index("ix_purchase_invoices_tenant_id_invoice_date", "tenant_id", "invoice_date"),
        Index("ix_purchase_invoices_tenant_id_supplier_id", "tenant_id", "supplier_id"),
        Index("ix_purchase_invoices_tenant_id_purchase_order_id", "tenant_id", "purchase_order_id"),
        Index("ix_purchase_invoices_tenant_id_payment_status", "tenant_id", "payment_status"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    bill_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'GOODS'"))
    supplier_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    supplier_trn: Mapped[str | None] = mapped_column(String(50), nullable=True)
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    purchase_order_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    goods_receipt_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipts.id", ondelete="SET NULL"),
        nullable=True,
    )
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    supplier_invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_terms_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payment_terms.id", ondelete="SET NULL"),
        nullable=True,
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tax_treatment: Mapped[str] = mapped_column(String(30), nullable=False)
    place_of_supply: Mapped[str] = mapped_column(String(30), nullable=False)
    is_reverse_charge: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    rcm_taxable_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    rcm_tax_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
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
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_paid: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    amount_debited: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    balance_due: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    payment_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'UNPAID'")
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

    lines: Mapped[list["PurchaseInvoiceLine"]] = relationship(
        back_populates="purchase_invoice",
        cascade="all, delete-orphan",
        order_by="PurchaseInvoiceLine.line_number",
    )


class PurchaseInvoiceLine(TenantModel):
    """Supplier bill line: product (clears GRNI) or expense (freight/duty)."""

    __tablename__ = "purchase_invoice_lines"
    __table_args__ = (
        UniqueConstraint(
            "purchase_invoice_id",
            "line_number",
            name="uq_purchase_invoice_lines_header_line_number",
        ),
        Index("ix_purchase_invoice_lines_purchase_invoice_id", "purchase_invoice_id"),
        Index("ix_purchase_invoice_lines_purchase_order_line_id", "purchase_order_line_id"),
        Index("ix_purchase_invoice_lines_goods_receipt_line_id", "goods_receipt_line_id"),
    )

    purchase_invoice_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("purchase_invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    line_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'PRODUCT'")
    )
    product_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("1"))
    unit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
    )
    rate: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    purchase_order_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"),
        nullable=True,
    )
    goods_receipt_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    goods_receipt_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipt_lines.id", ondelete="RESTRICT"),
        nullable=True,
    )
    supplier_product_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("supplier_products.id", ondelete="SET NULL"),
        nullable=True,
    )
    supplier_sku: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expense_account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    expense_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
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
    purchase_account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    grn_unit_cost: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    qty_debited: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))

    purchase_invoice: Mapped[PurchaseInvoice] = relationship(back_populates="lines")
