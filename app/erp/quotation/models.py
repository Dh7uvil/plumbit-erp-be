"""Quotation ORM models."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import MONEY_PRECISION, MONEY_SCALE, QUANTITY_PRECISION, QUANTITY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin


class Quotation(AuditUserMixin, SoftDeleteTenantModel):
    """Commercial quotation header with snapshotted FX and address text."""

    __tablename__ = "quotations"
    __table_args__ = (
        Index(
            "uq_quotations_tenant_id_quote_number_active",
            "tenant_id",
            "quote_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_quotations_tenant_id_status", "tenant_id", "status"),
        Index("ix_quotations_tenant_id_quote_date", "tenant_id", "quote_date"),
    )

    quote_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'DRAFT'"),
    )
    quote_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
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
    discount_value: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=True,
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    shipping_amount: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    adjustment_amount: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    grand_total: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    foreign_amount: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    base_amount: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    converted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    converted_document_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    converted_document_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )

    lines: Mapped[list["QuotationLine"]] = relationship(
        back_populates="quotation",
        cascade="all, delete-orphan",
        order_by="QuotationLine.line_number",
    )


class QuotationLine(TenantModel):
    """Quotation line with snapshotted tax and computed amounts."""

    __tablename__ = "quotation_lines"
    __table_args__ = (Index("ix_quotation_lines_quotation_id", "quotation_id"),)

    quotation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("quotations.id", ondelete="CASCADE"),
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
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(QUANTITY_PRECISION, QUANTITY_SCALE),
        nullable=False,
    )
    unit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
    )
    rate: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
    )
    discount_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    discount_value: Mapped[Decimal | None] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=True,
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    tax_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("taxes.id", ondelete="SET NULL"),
        nullable=True,
    )
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE),
        nullable=False,
        server_default=text("0"),
    )

    quotation: Mapped[Quotation] = relationship(back_populates="lines")
