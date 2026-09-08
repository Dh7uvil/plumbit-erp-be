"""Stock transfer request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import StockDocumentStatus


class StockTransferFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "document_date", "status"}
    )
    status: StockDocumentStatus | None = None
    from_warehouse_id: UUID | None = None
    to_warehouse_id: UUID | None = None
    branch_id: UUID | None = None
    product_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "StockTransferFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self


class StockTransferLineInput(BaseModel):
    product_id: UUID
    unit_id: UUID | None = None
    qty: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class StockTransferLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    product_id: UUID
    unit_id: UUID | None
    qty: Decimal
    qty_transferred: Decimal
    qty_source_before: Decimal | None
    qty_dest_before: Decimal | None
    notes: str | None


class StockTransferCreate(BaseModel):
    from_warehouse_id: UUID
    to_warehouse_id: UUID
    document_date: date | None = None
    branch_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=200)
    reference: str | None = Field(default=None, max_length=100)
    notes: str | None = None
    lines: list[StockTransferLineInput] = Field(min_length=1)

    @field_validator("reason", "reference", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def warehouses_must_differ(self) -> "StockTransferCreate":
        if self.from_warehouse_id == self.to_warehouse_id:
            raise ValueError("Source and destination warehouses must differ")
        return self


class StockTransferUpdate(BaseModel):
    from_warehouse_id: UUID | None = None
    to_warehouse_id: UUID | None = None
    document_date: date | None = None
    branch_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=200)
    reference: str | None = Field(default=None, max_length=100)
    notes: str | None = None
    lines: list[StockTransferLineInput] | None = Field(default=None, min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason", "reference", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class StockTransferCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class StockTransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: StockDocumentStatus
    version: int
    is_posted: bool
    document_date: date
    from_warehouse_id: UUID
    to_warehouse_id: UUID
    branch_id: UUID | None
    reason: str | None
    reference: str | None
    notes: str | None
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    lines: list[StockTransferLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
