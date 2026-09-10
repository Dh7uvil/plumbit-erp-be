"""Opening-balance go-live request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class OpeningBalanceGLLine(BaseModel):
    account_id: UUID
    debit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    credit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    description: str | None = Field(default=None, max_length=500)


class OpeningBalanceOpenItem(BaseModel):
    party_id: UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    due_date: date
    external_reference: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("external_reference", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class OpeningBalanceStockLine(BaseModel):
    warehouse_id: UUID
    product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_cost: Decimal = Field(ge=0, max_digits=18, decimal_places=4)


class OpeningBalancePayload(BaseModel):
    books_start_date: date
    gl_lines: list[OpeningBalanceGLLine] = Field(default_factory=list)
    ar_items: list[OpeningBalanceOpenItem] = Field(default_factory=list)
    ap_items: list[OpeningBalanceOpenItem] = Field(default_factory=list)
    stock_lines: list[OpeningBalanceStockLine] = Field(default_factory=list)


class OpeningBalancePreviewLine(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    party_id: UUID | None = None
    due_date: date | None = None
    external_reference: str | None = None
    description: str | None = None


class OpeningBalancePreviewResponse(BaseModel):
    books_start_date: date
    entry_date: date
    opening_balance_equity_account_id: UUID
    difference: Decimal
    total_debit: Decimal
    total_credit: Decimal
    inventory_value: Decimal
    lines: list[OpeningBalancePreviewLine]


class OpeningBalanceStateResponse(BaseModel):
    committed: bool
    books_start_date: date | None
    hard_lock_date: date | None
    journal_entry_id: UUID | None = None
    document_number: str | None = None
    committed_at: datetime | None = None
    can_reset: bool = False
