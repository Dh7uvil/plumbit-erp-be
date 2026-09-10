"""Credit note ORM models. AR document; does not move stock."""

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


class CreditNote(AuditUserMixin, SoftDeleteTenantModel):
    """Draft-or-posted credit note. Post reverses AR/revenue/VAT, not stock."""

    __tablename__ = "credit_notes"
    __table_args__ = (
        Index(
            "uq_credit_notes_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_credit_notes_tenant_id_status", "tenant_id", "status"),
        Index("ix_credit_notes_tenant_id_credit_note_date", "tenant_id", "credit_note_date"),
        Index("ix_credit_notes_tenant_id_customer_id", "tenant_id", "customer_id"),
        Index("ix_credit_notes_tenant_id_sales_invoice_id", "tenant_id", "sales_invoice_id"),
        Index("ix_credit_notes_tenant_id_sales_return_id", "tenant_id", "sales_return_id"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    credit_note_date: Mapped[date] = mapped_column(Date, nullable=False)
    customer_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sales_invoice_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_invoices.id", ondelete="RESTRICT"),
        nullable=True,
    )
    sales_return_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_returns.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
    round_off_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    grand_total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    foreign_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    base_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_applied: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    amount_unapplied: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
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

    lines: Mapped[list["CreditNoteLine"]] = relationship(
        back_populates="credit_note",
        cascade="all, delete-orphan",
        order_by="CreditNoteLine.line_number",
    )


class CreditNoteLine(TenantModel):
    """Credit note line with optional invoice and return links. No COGS."""

    __tablename__ = "credit_note_lines"
    __table_args__ = (
        UniqueConstraint(
            "credit_note_id",
            "line_number",
            name="uq_credit_note_lines_header_line_number",
        ),
        Index("ix_credit_note_lines_credit_note_id", "credit_note_id"),
        Index("ix_credit_note_lines_sales_invoice_line_id", "sales_invoice_line_id"),
        Index("ix_credit_note_lines_sales_return_line_id", "sales_return_line_id"),
    )

    credit_note_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("credit_notes.id", ondelete="CASCADE"),
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
    sales_invoice_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_invoice_lines.id", ondelete="RESTRICT"),
        nullable=True,
    )
    sales_return_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("sales_return_lines.id", ondelete="RESTRICT"),
        nullable=True,
    )
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
    income_account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    credit_note: Mapped[CreditNote] = relationship(back_populates="lines")
