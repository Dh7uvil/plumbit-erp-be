"""Stock adjustment request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import StockAdjustmentReason, StockDocumentStatus


class StockAdjustmentFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "document_date", "status"}
    )
    status: StockDocumentStatus | None = None
    warehouse_id: UUID | None = None
    reason: StockAdjustmentReason | None = None
    branch_id: UUID | None = None
    product_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "StockAdjustmentFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self


class StockAdjustmentLineInput(BaseModel):
    product_id: UUID
    unit_id: UUID | None = None
    qty_delta: Decimal | None = Field(default=None, max_digits=18, decimal_places=6)
    qty_counted: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class StockAdjustmentLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    product_id: UUID
    unit_id: UUID | None
    qty_counted: Decimal | None
    qty_booked: Decimal | None
    qty_delta: Decimal | None
    notes: str | None


class StockAdjustmentCreate(BaseModel):
    warehouse_id: UUID
    document_date: date | None = None
    reason: StockAdjustmentReason
    branch_id: UUID | None = None
    reference: str | None = Field(default=None, max_length=100)
    notes: str | None = None
    lines: list[StockAdjustmentLineInput] = Field(min_length=1)

    @field_validator("reference", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class StockAdjustmentUpdate(BaseModel):
    warehouse_id: UUID | None = None
    document_date: date | None = None
    reason: StockAdjustmentReason | None = None
    branch_id: UUID | None = None
    reference: str | None = Field(default=None, max_length=100)
    notes: str | None = None
    lines: list[StockAdjustmentLineInput] | None = Field(default=None, min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reference", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class StockAdjustmentCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class StockAdjustmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: StockDocumentStatus
    version: int
    is_posted: bool
    document_date: date
    warehouse_id: UUID
    reason: StockAdjustmentReason
    branch_id: UUID | None
    reference: str | None
    notes: str | None
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    lines: list[StockAdjustmentLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
