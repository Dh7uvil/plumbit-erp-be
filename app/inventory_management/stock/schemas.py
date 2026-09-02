"""Stock inquiry and reorder schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import StockMovementType


class StockFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "qty_on_hand",
            "qty_reserved",
            "qty_available",
            "last_movement_at",
        }
    )
    warehouse_id: UUID | None = None
    product_id: UUID | None = None
    category_id: UUID | None = None
    negative_only: bool = False
    below_reorder: bool = False


class StockMovementFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_date", "occurred_at", "qty"}
    )
    sort_by: str = "occurred_at"
    warehouse_id: UUID | None = None
    product_id: UUID | None = None
    category_id: UUID | None = None
    movement_type: StockMovementType | None = None
    source_type: str | None = None
    source_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "StockMovementFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self


class StockReorderUpdate(BaseModel):
    reorder_level: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    reorder_qty: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)

    @model_validator(mode="after")
    def require_one_field(self) -> "StockReorderUpdate":
        if self.reorder_level is None and self.reorder_qty is None:
            raise ValueError("reorder_level or reorder_qty is required")
        return self


class StockBalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    warehouse_id: UUID
    warehouse_code: str
    warehouse_name: str
    product_id: UUID
    sku: str
    product_name: str
    qty_on_hand: Decimal
    qty_reserved: Decimal
    qty_available: Decimal
    qty_incoming: Decimal
    qty_outgoing: Decimal
    qty_in_transit: Decimal
    reorder_level: Decimal | None
    reorder_qty: Decimal | None
    last_movement_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    movement_type: StockMovementType
    warehouse_id: UUID
    warehouse_code: str
    warehouse_name: str
    product_id: UUID
    sku: str
    product_name: str
    unit_id: UUID | None
    qty: Decimal
    qty_before: Decimal
    qty_after: Decimal
    source_type: str
    source_id: UUID
    source_line_id: UUID | None
    document_date: date
    occurred_at: datetime
    notes: str | None
    created_at: datetime
