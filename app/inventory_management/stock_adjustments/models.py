"""Stock adjustment document models."""

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

from app.core.constants import QUANTITY_PRECISION, QUANTITY_SCALE
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin

_QTY = Numeric(QUANTITY_PRECISION, QUANTITY_SCALE)


class StockAdjustment(AuditUserMixin, SoftDeleteTenantModel):
    """Draft-or-posted inventory quantity adjustment."""

    __tablename__ = "stock_adjustments"
    __table_args__ = (
        Index(
            "uq_stock_adjustments_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_stock_adjustments_tenant_id_status", "tenant_id", "status"),
        Index("ix_stock_adjustments_tenant_id_document_date", "tenant_id", "document_date"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    branch_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
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

    lines: Mapped[list["StockAdjustmentLine"]] = relationship(
        back_populates="adjustment",
        cascade="all, delete-orphan",
        order_by="StockAdjustmentLine.line_number",
    )


class StockAdjustmentLine(TenantModel):
    """Adjustment line. qty_booked / qty_delta are filled at post."""

    __tablename__ = "stock_adjustment_lines"
    __table_args__ = (
        UniqueConstraint(
            "stock_adjustment_id",
            "line_number",
            name="uq_stock_adjustment_lines_header_line_number",
        ),
        UniqueConstraint(
            "stock_adjustment_id",
            "product_id",
            name="uq_stock_adjustment_lines_header_product",
        ),
        Index("ix_stock_adjustment_lines_stock_adjustment_id", "stock_adjustment_id"),
    )

    stock_adjustment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("stock_adjustments.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    unit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("units.id", ondelete="RESTRICT"),
        nullable=True,
    )
    qty_counted: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    qty_booked: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    qty_delta: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    adjustment: Mapped[StockAdjustment] = relationship(back_populates="lines")
