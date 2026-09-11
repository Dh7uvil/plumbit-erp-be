"""Landed cost request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.schemas.related_documents import RelatedDocumentRef
from app.core.enums import ExpenseCategory, LandedCostAllocationMethod, StockDocumentStatus


class LandedCostFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "document_number", "document_date", "status"}
    )
    status: StockDocumentStatus | None = None
    shipment_id: UUID | None = None
    goods_receipt_id: UUID | None = None
    purchase_invoice_id: UUID | None = None
    document_date_from: date | None = None
    document_date_to: date | None = None

    @model_validator(mode="after")
    def validate_document_date_range(self) -> "LandedCostFilter":
        if (
            self.document_date_from is not None
            and self.document_date_to is not None
            and self.document_date_from > self.document_date_to
        ):
            raise ValueError("document_date_from must be before or equal to document_date_to")
        return self


class LandedCostChargeInput(BaseModel):
    purchase_invoice_line_id: UUID
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)


class LandedCostAllocationInput(BaseModel):
    goods_receipt_line_id: UUID


class LandedCostChargeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    purchase_invoice_id: UUID
    purchase_invoice_line_id: UUID
    expense_category: ExpenseCategory
    bill_number: str
    amount: Decimal


class LandedCostAllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    goods_receipt_id: UUID
    goods_receipt_line_id: UUID
    allocation_base: Decimal
    allocated_amount: Decimal
    qty_remaining_at_post: Decimal | None = None
    qty_consumed_at_post: Decimal | None = None
    previous_landed_unit_cost: Decimal | None = None


class LandedCostCreate(BaseModel):
    document_date: date | None = None
    allocation_method: LandedCostAllocationMethod = LandedCostAllocationMethod.VALUE
    shipment_id: UUID | None = None
    branch_id: UUID | None = None
    notes: str | None = None
    charges: list[LandedCostChargeInput] = Field(min_length=1)
    allocations: list[LandedCostAllocationInput] = Field(min_length=1)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LandedCostUpdate(BaseModel):
    document_date: date | None = None
    allocation_method: LandedCostAllocationMethod | None = None
    shipment_id: UUID | None = None
    branch_id: UUID | None = None
    notes: str | None = None
    charges: list[LandedCostChargeInput] | None = Field(default=None, min_length=1)
    allocations: list[LandedCostAllocationInput] | None = Field(default=None, min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LandedCostCreateFromBills(BaseModel):
    purchase_invoice_line_ids: list[UUID] = Field(min_length=1)
    goods_receipt_ids: list[UUID] = Field(default_factory=list)
    shipment_id: UUID | None = None
    allocation_method: LandedCostAllocationMethod = LandedCostAllocationMethod.VALUE
    document_date: date | None = None
    branch_id: UUID | None = None
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LandedCostCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LandedCostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    document_number: str
    status: StockDocumentStatus
    version: int
    is_posted: bool
    document_date: date
    allocation_method: LandedCostAllocationMethod
    shipment_id: UUID | None
    branch_id: UUID | None
    journal_entry_id: UUID | None
    reversal_journal_entry_id: UUID | None
    notes: str | None
    total_charges: Decimal
    posted_at: datetime | None
    posted_by: UUID | None
    cancelled_at: datetime | None
    cancelled_by: UUID | None
    cancel_reason: str | None
    available_actions: list[str] = Field(default_factory=list)
    period_locked: bool = False
    related_documents: list[RelatedDocumentRef] = Field(default_factory=list)
    charges: list[LandedCostChargeResponse] = Field(default_factory=list)
    allocations: list[LandedCostAllocationResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class LandedCostEligibleLine(BaseModel):
    goods_receipt_id: UUID
    goods_receipt_line_id: UUID
    goods_receipt_number: str
    product_id: UUID | None
    description: str
    quantity: Decimal
    net_weight: Decimal | None
    landed_unit_cost: Decimal
    line_value: Decimal
    qty_remaining: Decimal


class LandedCostEligibleResponse(BaseModel):
    goods_receipt_id: UUID
    lines: list[LandedCostEligibleLine] = Field(default_factory=list)
