"""Transaction lock and books-close request/response schemas."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.common.utils.validators import blank_to_none, normalize_required_text

REASON_MIN_LENGTH = 10
PREVIEW_CAP = 50


class PeriodLockResponse(BaseModel):
    lock_date: date | None
    hard_lock_date: date | None
    lock_reason: str | None
    hard_lock_reason: str | None


class PeriodLockUpdate(BaseModel):
    lock_date: date | None = None
    hard_lock_date: date | None = None
    reason: str | None = Field(default=None, max_length=500)
    acknowledge_negative_stock: bool = False

    @field_validator("reason", mode="before")
    @classmethod
    def coerce_reason(cls, value: object) -> object:
        return blank_to_none(value)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="reason")


class PeriodLockNegativeBalance(BaseModel):
    warehouse_id: UUID
    warehouse_code: str
    product_id: UUID
    sku: str
    qty_on_hand: Decimal


class PeriodLockUnpostedDocument(BaseModel):
    id: UUID
    document_type: str
    document_number: str
    document_date: date
    status: str


class PeriodLockPreviewResponse(BaseModel):
    allow_negative_stock: bool
    negative_balances: list[PeriodLockNegativeBalance]
    negative_balances_total_count: int
    negative_balances_are_current: bool = True
    unposted_documents: list[PeriodLockUnpostedDocument]
    unposted_documents_total_count: int
    blocked: bool
    requires_acknowledgement: bool
