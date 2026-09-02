"""Stock transfer document models."""

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


class StockTransfer(AuditUserMixin, SoftDeleteTenantModel):
    """Immediate warehouse-to-warehouse transfer. Save is draft; post moves stock."""

    __tablename__ = "stock_transfers"
    __table_args__ = (
        Index(
            "uq_stock_transfers_tenant_id_document_number_active",
            "tenant_id",
            "document_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_stock_transfers_tenant_id_status", "tenant_id", "status"),
        Index("ix_stock_transfers_tenant_id_document_date", "tenant_id", "document_date"),
    )

    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    from_warehouse_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    to_warehouse_id: Mapped[UUID] = mapped_column(
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
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
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

    lines: Mapped[list["StockTransferLine"]] = relationship(
        back_populates="transfer",
        cascade="all, delete-orphan",
        order_by="StockTransferLine.line_number",
    )


class StockTransferLine(TenantModel):
    """Transfer line. Source/dest snapshots and qty_transferred are set at post."""

    __tablename__ = "stock_transfer_lines"
    __table_args__ = (
        UniqueConstraint(
            "stock_transfer_id",
            "line_number",
            name="uq_stock_transfer_lines_header_line_number",
        ),
        UniqueConstraint(
            "stock_transfer_id",
            "product_id",
            name="uq_stock_transfer_lines_header_product",
        ),
        Index("ix_stock_transfer_lines_stock_transfer_id", "stock_transfer_id"),
    )

    stock_transfer_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("stock_transfers.id", ondelete="CASCADE"),
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
    qty: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    qty_transferred: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_source_before: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    qty_dest_before: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    transfer: Mapped[StockTransfer] = relationship(back_populates="lines")
