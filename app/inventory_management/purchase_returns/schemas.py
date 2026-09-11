"""Purchase return request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import PurchaseReturnDisposition, PurchaseReturnReason, StockDocumentStatus


class PurchaseReturnFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "document_date", "status"}
    )
    status: StockDocumentStatus | None = None
    goods_receipt_id: UUID | None = None
    purchase_order_id: UUID | None = None
    supplier_id: UUID | None = None
    warehouse_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "PurchaseReturnFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self


class PurchaseReturnLineInput(BaseModel):
    goods_receipt_line_id: UUID
    product_id: UUID | None = None
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_id: UUID | None = None
    rate: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    disposition: PurchaseReturnDisposition = PurchaseReturnDisposition.RETURN_TO_SUPPLIER
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PurchaseReturnLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    goods_receipt_line_id: UUID
    product_id: UUID | None
    quantity: Decimal
    unit_id: UUID | None
    rate: Decimal
    disposition: PurchaseReturnDisposition
    notes: str | None


class PurchaseReturnCreate(BaseModel):
    goods_receipt_id: UUID
    document_date: date | None = None
    reason_code: PurchaseReturnReason
    notes: str | None = None
    lines: list[PurchaseReturnLineInput] = Field(min_length=1)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PurchaseReturnUpdate(BaseModel):
    document_date: date | None = None
    reason_code: PurchaseReturnReason | None = None
    notes: str | None = None
    lines: list[PurchaseReturnLineInput] | None = Field(default=None, min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PurchaseReturnCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PurchaseReturnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: StockDocumentStatus
    version: int
    is_posted: bool
    document_date: date
    goods_receipt_id: UUID
    purchase_order_id: UUID | None
    supplier_id: UUID
    warehouse_id: UUID
    reason_code: PurchaseReturnReason
    notes: str | None
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    period_locked: bool = False
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    lines: list[PurchaseReturnLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
