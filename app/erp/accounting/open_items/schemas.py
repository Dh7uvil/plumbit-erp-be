"""Open-item picker and allocation request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.common.utils.currency import quantize_money
from app.core.enums import OpenItemType


class OpenItemRow(BaseModel):
    item_type: OpenItemType
    document_id: UUID
    document_number: str
    document_date: date
    due_date: date | None = None
    currency_id: UUID
    currency_code: str | None = None
    original_amount: Decimal
    balance: Decimal
    doc_amount: Decimal | None = None
    base_amount: Decimal | None = None
    base_balance: Decimal | None = None
    is_debit: bool
    exchange_rate: Decimal | None = None

    @model_validator(mode="after")
    def fill_money_fields(self) -> Self:
        if self.doc_amount is None:
            self.doc_amount = self.original_amount
        if self.exchange_rate is None:
            return self
        if self.base_amount is None:
            self.base_amount = quantize_money(self.original_amount * self.exchange_rate)
        if self.base_balance is None:
            self.base_balance = quantize_money(self.balance * self.exchange_rate)
        return self


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


class PaymentAllocationRecordResponse(BaseModel):
    id: UUID
    payment_type: str
    payment_id: UUID
    item_type: OpenItemType
    item_id: UUID
    item_document_number: str | None = None
    amount: Decimal
    journal_entry_id: UUID | None = None
    reversed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


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
