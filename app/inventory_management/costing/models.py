"""FIFO cost layer and consumption ledger."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MONEY_PRECISION, MONEY_SCALE, QUANTITY_PRECISION, QUANTITY_SCALE
from app.db.base import TenantModel

_QTY = Numeric(QUANTITY_PRECISION, QUANTITY_SCALE)
_MONEY = Numeric(MONEY_PRECISION, MONEY_SCALE)


class StockCostLayer(TenantModel):
    """One inbound FIFO lot. qty_remaining may be negative for negative-stock layers."""

    __tablename__ = "stock_cost_layers"
    __table_args__ = (
        Index(
            "ix_stock_cost_layers_fifo",
            "tenant_id",
            "product_id",
            "warehouse_id",
            "document_date",
            "created_at",
        ),
        Index(
            "ix_stock_cost_layers_tenant_source",
            "tenant_id",
            "source_type",
            "source_id",
        ),
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
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    source_line_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    qty_received: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    qty_remaining: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    landed_unit_cost: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    is_estimated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_negative: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class StockCostConsumption(TenantModel):
    """Qty taken from a layer by one stock movement. Required for later returns/revalue."""

    __tablename__ = "stock_cost_consumptions"
    __table_args__ = (
        Index("ix_stock_cost_consumptions_movement_id", "movement_id"),
        Index("ix_stock_cost_consumptions_layer_id", "layer_id"),
        CheckConstraint(
            "qty_restored >= 0 AND qty_restored <= qty",
            name="ck_stock_cost_consumptions_qty_restored",
        ),
    )

    movement_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("stock_movements.id", ondelete="RESTRICT"),
        nullable=False,
    )
    layer_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("stock_cost_layers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    qty: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    qty_restored: Mapped[Decimal] = mapped_column(_QTY, nullable=False, server_default=text("0"))
    unit_cost: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
