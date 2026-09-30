"""Year-end closing request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class YearEndPreviewLine(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    account_type: str
    debit: Decimal
    credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal


class YearEndPreviewResponse(BaseModel):
    fiscal_year: int
    from_date: date
    to_date: date
    entry_date: date
    retained_earnings_account_id: UUID
    net_profit: Decimal
    total_debit: Decimal
    total_credit: Decimal
    lines: list[YearEndPreviewLine]


class YearEndCommitRequest(BaseModel):
    fiscal_year: int = Field(ge=1900, le=9999)


class YearEndReopenRequest(BaseModel):
    fiscal_year: int = Field(ge=1900, le=9999)


class YearEndStateResponse(BaseModel):
    fiscal_year: int
    from_date: date
    to_date: date
    is_closed: bool
    journal_entry_id: UUID | None = None
    document_number: str | None = None
    committed_at: datetime | None = None
    lock_date: date | None = None
