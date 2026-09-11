"""Open-item picker and allocation request/response schemas."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.enums import OpenItemType


class OpenItemRow(BaseModel):
    item_type: OpenItemType
    document_id: UUID
    document_number: str
    document_date: date
    due_date: date | None = None
    currency_id: UUID
    original_amount: Decimal
    balance: Decimal
    is_debit: bool
    exchange_rate: Decimal | None = None


class PaymentAllocationInput(BaseModel):
    item_type: OpenItemType
    item_id: UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=4)


class ApplyCreditsRequest(BaseModel):
    allocations: list[PaymentAllocationInput] | None = None
    version: int | None = Field(default=None, ge=1)


class PaymentAllocateRequest(BaseModel):
    allocations: list[PaymentAllocationInput] = Field(min_length=1)
    version: int | None = Field(default=None, ge=1)


class PaymentCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
