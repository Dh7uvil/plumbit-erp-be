"""Landed cost document models."""

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


class LandedCost(AuditUserMixin, SoftDeleteTenantModel):
    """Draft-or-posted allocation of expense bills onto GRN cost layers."""

    __tablename__ = "landed_costs"
    __table_args__ = (
        Index(
            "uq_landed_costs_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_landed_costs_tenant_id_status", "tenant_id", "status"),
        Index("ix_landed_costs_tenant_id_document_date", "tenant_id", "document_date"),
        Index("ix_landed_costs_tenant_id_shipment_id", "tenant_id", "shipment_id"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    allocation_method: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'VALUE'")
    )
    shipment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    charges: Mapped[list["LandedCostCharge"]] = relationship(
        back_populates="landed_cost",
        cascade="all, delete-orphan",
        order_by="LandedCostCharge.line_number",
    )
    allocations: Mapped[list["LandedCostAllocation"]] = relationship(
        back_populates="landed_cost",
        cascade="all, delete-orphan",
        order_by="LandedCostAllocation.line_number",
    )


class LandedCostCharge(TenantModel):
    """Posted expense bill line allocated by this landed cost."""

    __tablename__ = "landed_cost_charges"
    __table_args__ = (
        UniqueConstraint(
            "landed_cost_id",
            "line_number",
            name="uq_landed_cost_charges_header_line_number",
        ),
        UniqueConstraint(
            "landed_cost_id",
            "purchase_invoice_line_id",
            name="uq_landed_cost_charges_header_bill_line",
        ),
        Index("ix_landed_cost_charges_landed_cost_id", "landed_cost_id"),
        Index("ix_landed_cost_charges_purchase_invoice_line_id", "purchase_invoice_line_id"),
    )

    landed_cost_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("landed_costs.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    purchase_invoice_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("purchase_invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    purchase_invoice_line_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("purchase_invoice_lines.id", ondelete="RESTRICT"),
        nullable=False,
    )
    expense_category: Mapped[str] = mapped_column(String(30), nullable=False)
    bill_number: Mapped[str] = mapped_column(String(40), nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)

    landed_cost: Mapped[LandedCost] = relationship(back_populates="charges")


class LandedCostAllocation(TenantModel):
    """Posted GRN line receiving a share of landed-cost charges."""

    __tablename__ = "landed_cost_allocations"
    __table_args__ = (
        UniqueConstraint(
            "landed_cost_id",
            "line_number",
            name="uq_landed_cost_allocations_header_line_number",
        ),
        UniqueConstraint(
            "landed_cost_id",
            "goods_receipt_line_id",
            name="uq_landed_cost_allocations_header_grn_line",
        ),
        Index("ix_landed_cost_allocations_landed_cost_id", "landed_cost_id"),
        Index("ix_landed_cost_allocations_goods_receipt_line_id", "goods_receipt_line_id"),
    )

    landed_cost_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("landed_costs.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    goods_receipt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    goods_receipt_line_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("goods_receipt_lines.id", ondelete="RESTRICT"),
        nullable=False,
    )
    allocation_base: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    allocated_amount: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, server_default=text("0")
    )
    qty_remaining_at_post: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    qty_consumed_at_post: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    previous_landed_unit_cost: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)

    landed_cost: Mapped[LandedCost] = relationship(back_populates="allocations")
