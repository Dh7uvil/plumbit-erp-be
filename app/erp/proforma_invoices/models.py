"""Proforma invoice ORM models."""

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


class ProformaInvoice(AuditUserMixin, SoftDeleteTenantModel):
    """Export-facing proforma invoice with snapshotted FX, addresses, and bank details."""

    __tablename__ = "proforma_invoices"
    __table_args__ = (
        Index(
            "uq_proforma_invoices_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_proforma_invoices_tenant_id_status", "tenant_id", "status"),
        Index("ix_proforma_invoices_tenant_id_proforma_date", "tenant_id", "proforma_date"),
        Index("ix_proforma_invoices_tenant_id_customer_id", "tenant_id", "customer_id"),
        Index(
            "ix_proforma_invoices_tenant_id_source_quotation_id",
            "tenant_id",
            "source_quotation_id",
        ),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'DRAFT'"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    proforma_date: Mapped[date] = mapped_column(Date, nullable=False)
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
    source_quotation_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("quotations.id", ondelete="SET NULL"),
        nullable=True,
    )
    incoterm: Mapped[str | None] = mapped_column(String(20), nullable=True)
    incoterm_place: Mapped[str | None] = mapped_column(String(120), nullable=True)
    port_of_loading: Mapped[str | None] = mapped_column(String(120), nullable=True)
    port_of_discharge: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(String(2), nullable=True)
    country_of_final_destination: Mapped[str | None] = mapped_column(String(2), nullable=True)
    expected_shipment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    partial_shipment_allowed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    transhipment_allowed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    bank_details_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    declined_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_document_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    converted_document_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )

    lines: Mapped[list["ProformaInvoiceLine"]] = relationship(
        back_populates="proforma_invoice",
        cascade="all, delete-orphan",
        order_by="ProformaInvoiceLine.line_number",
    )
    milestones: Mapped[list["ProformaInvoiceMilestone"]] = relationship(
        back_populates="proforma_invoice",
        cascade="all, delete-orphan",
        order_by="ProformaInvoiceMilestone.sequence",
    )


class ProformaInvoiceLine(TenantModel):
    """Proforma invoice line with snapshotted tax, amounts, and HS code."""

    __tablename__ = "proforma_invoice_lines"
    __table_args__ = (
        UniqueConstraint(
            "proforma_invoice_id",
            "line_number",
            name="uq_proforma_invoice_lines_header_line_number",
        ),
        Index("ix_proforma_invoice_lines_proforma_invoice_id", "proforma_invoice_id"),
    )

    proforma_invoice_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("proforma_invoices.id", ondelete="CASCADE"),
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
    source_quotation_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("quotation_lines.id", ondelete="SET NULL"),
        nullable=True,
    )
    hs_code: Mapped[str | None] = mapped_column(String(20), nullable=True)

    proforma_invoice: Mapped[ProformaInvoice] = relationship(back_populates="lines")


class ProformaInvoiceMilestone(TenantModel):
    """Structured advance / payment schedule row on a proforma invoice."""

    __tablename__ = "proforma_invoice_milestones"
    __table_args__ = (
        UniqueConstraint(
            "proforma_invoice_id",
            "sequence",
            name="uq_proforma_invoice_milestones_header_sequence",
        ),
        Index("ix_proforma_invoice_milestones_proforma_invoice_id", "proforma_invoice_id"),
    )

    proforma_invoice_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("proforma_invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)
    percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    net_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    computed_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    proforma_invoice: Mapped[ProformaInvoice] = relationship(back_populates="milestones")
