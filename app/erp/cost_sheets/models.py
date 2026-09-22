"""Cost sheet ORM models."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Date,
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


class CostSheet(AuditUserMixin, SoftDeleteTenantModel):
    """Planning worksheet for import/export landed cost and margin — never posts to GL."""

    __tablename__ = "cost_sheets"
    __table_args__ = (
        Index(
            "uq_cost_sheets_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_cost_sheets_tenant_id_status", "tenant_id", "status"),
        Index("ix_cost_sheets_tenant_id_sheet_type", "tenant_id", "sheet_type"),
        Index("ix_cost_sheets_tenant_id_document_date", "tenant_id", "document_date"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    sheet_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    shipment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    purchase_order_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    supplier_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    proforma_invoice_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("proforma_invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(MONEY_PRECISION, 6), nullable=False)
    incoterm: Mapped[str | None] = mapped_column(String(10), nullable=True)
    port_of_loading: Mapped[str | None] = mapped_column(String(120), nullable=True)
    port_of_discharge: Mapped[str | None] = mapped_column(String(120), nullable=True)
    allocation_method: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'VALUE'")
    )
    landed_cost_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("landed_costs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    lines: Mapped[list["CostSheetLine"]] = relationship(
        back_populates="cost_sheet",
        cascade="all, delete-orphan",
        order_by="CostSheetLine.line_number",
    )
    charges: Mapped[list["CostSheetCharge"]] = relationship(
        back_populates="cost_sheet",
        cascade="all, delete-orphan",
        order_by="CostSheetCharge.line_number",
    )


class CostSheetLine(TenantModel):
    """Goods line on a cost sheet."""

    __tablename__ = "cost_sheet_lines"
    __table_args__ = (
        UniqueConstraint("cost_sheet_id", "line_number", name="uq_cost_sheet_lines_header_line"),
        Index("ix_cost_sheet_lines_cost_sheet_id", "cost_sheet_id"),
    )

    cost_sheet_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cost_sheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    unit_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("units.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    base_rate: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    target_selling_price: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    goods_receipt_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipt_lines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    cost_sheet: Mapped[CostSheet] = relationship(back_populates="lines")


class CostSheetCharge(TenantModel):
    """Charge row (estimate vs actual) on a cost sheet."""

    __tablename__ = "cost_sheet_charges"
    __table_args__ = (
        UniqueConstraint("cost_sheet_id", "line_number", name="uq_cost_sheet_charges_header_line"),
        Index("ix_cost_sheet_charges_cost_sheet_id", "cost_sheet_id"),
        Index("ix_cost_sheet_charges_charge_type_id", "charge_type_id"),
    )

    cost_sheet_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cost_sheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    charge_type_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("charge_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    estimated_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    actual_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    allocation_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    purchase_invoice_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("purchase_invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    purchase_invoice_line_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("purchase_invoice_lines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    cost_sheet: Mapped[CostSheet] = relationship(back_populates="charges")
