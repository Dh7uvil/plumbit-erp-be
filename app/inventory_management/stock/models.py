"""Stock balance and movement ORM models."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import QUANTITY_PRECISION, QUANTITY_SCALE
from app.db.base import TenantModel

_QTY = Numeric(QUANTITY_PRECISION, QUANTITY_SCALE)


class StockBalance(TenantModel):
    """On-hand and reserved quantity per warehouse and product. Not soft-deleted."""

    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "warehouse_id",
            "product_id",
            name="uq_stock_balances_tenant_warehouse_product",
        ),
        CheckConstraint("qty_reserved >= 0", name="ck_stock_balances_qty_reserved_non_negative"),
        CheckConstraint("qty_incoming >= 0", name="ck_stock_balances_qty_incoming_non_negative"),
        CheckConstraint("qty_outgoing >= 0", name="ck_stock_balances_qty_outgoing_non_negative"),
        CheckConstraint(
            "qty_in_transit >= 0", name="ck_stock_balances_qty_in_transit_non_negative"
        ),
        Index("ix_stock_balances_tenant_id_product_id", "tenant_id", "product_id"),
        Index("ix_stock_balances_tenant_id_warehouse_id", "tenant_id", "warehouse_id"),
    )

    warehouse_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    qty_on_hand: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_reserved: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_incoming: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_outgoing: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    qty_in_transit: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    reorder_level: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    reorder_qty: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    last_movement_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StockMovement(TenantModel):
    """Append-only signed stock ledger. Never updated or deleted."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        Index(
            "ix_stock_movements_tenant_product_warehouse_date",
            "tenant_id",
            "product_id",
            "warehouse_id",
            "document_date",
        ),
        Index(
            "ix_stock_movements_tenant_source",
            "tenant_id",
            "source_type",
            "source_id",
        ),
    )

    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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
    qty_before: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    qty_after: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    source_line_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
