"""Sales return request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import ReturnDisposition, SalesReturnReason, StockDocumentStatus


class SalesReturnFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "document_date", "status"}
    )
    status: StockDocumentStatus | None = None
    delivery_note_id: UUID | None = None
    sales_order_id: UUID | None = None
    customer_id: UUID | None = None
    warehouse_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "SalesReturnFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self


class SalesReturnLineInput(BaseModel):
    delivery_note_line_id: UUID
    product_id: UUID | None = None
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_id: UUID | None = None
    rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    disposition: ReturnDisposition
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SalesReturnLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    delivery_note_line_id: UUID
    product_id: UUID | None
    quantity: Decimal
    unit_id: UUID | None
    rate: Decimal
    disposition: ReturnDisposition
    notes: str | None


class SalesReturnCreate(BaseModel):
    delivery_note_id: UUID
    document_date: date | None = None
    reason_code: SalesReturnReason
    notes: str | None = None
    lines: list[SalesReturnLineInput] = Field(min_length=1)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SalesReturnUpdate(BaseModel):
    document_date: date | None = None
    reason_code: SalesReturnReason | None = None
    notes: str | None = None
    lines: list[SalesReturnLineInput] | None = Field(default=None, min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SalesReturnCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SalesReturnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: StockDocumentStatus
    version: int
    is_posted: bool
    document_date: date
    delivery_note_id: UUID
    sales_order_id: UUID
    customer_id: UUID
    warehouse_id: UUID
    reason_code: SalesReturnReason
    notes: str | None
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    period_locked: bool = False
    lines: list[SalesReturnLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
