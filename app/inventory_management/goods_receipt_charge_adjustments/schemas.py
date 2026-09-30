"""GRN charge adjustment request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import StockDocumentStatus


class GoodsReceiptChargeAdjustmentFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "document_date", "status"}
    )
    status: StockDocumentStatus | None = None
    goods_receipt_id: UUID | None = None
    branch_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "GoodsReceiptChargeAdjustmentFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self


class GoodsReceiptChargeAdjustmentLineInput(BaseModel):
    goods_receipt_charge_id: UUID
    adjustment_amount: Decimal = Field(max_digits=18, decimal_places=4)
    notes: str | None = None

    @field_validator("adjustment_amount")
    @classmethod
    def non_zero(cls, value: Decimal) -> Decimal:
        if value == Decimal("0"):
            raise ValueError("adjustment_amount must be non-zero")
        return value

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class GoodsReceiptChargeAdjustmentLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    goods_receipt_charge_id: UUID
    adjustment_amount: Decimal
    base_adjustment_amount: Decimal
    notes: str | None


class GoodsReceiptChargeAdjustmentCreate(BaseModel):
    goods_receipt_id: UUID
    document_date: date | None = None
    branch_id: UUID | None = None
    notes: str | None = None
    lines: list[GoodsReceiptChargeAdjustmentLineInput] = Field(min_length=1)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class GoodsReceiptChargeAdjustmentUpdate(BaseModel):
    document_date: date | None = None
    branch_id: UUID | None = None
    notes: str | None = None
    lines: list[GoodsReceiptChargeAdjustmentLineInput] | None = Field(default=None, min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class GoodsReceiptChargeAdjustmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: StockDocumentStatus
    version: int
    is_posted: bool
    document_date: date
    goods_receipt_id: UUID
    branch_id: UUID | None
    notes: str | None
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    period_locked: bool = False
    lines: list[GoodsReceiptChargeAdjustmentLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None


class GoodsReceiptChargeAdjustmentCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
