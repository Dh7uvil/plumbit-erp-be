"""Bank reconciliation request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.common.schemas.filters import BaseFilter
from app.core.enums import BankStatementMatchStatus, BankStatementStatus


class BankStatementFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "period_start", "period_end", "status"}
    )
    bank_account_id: UUID | None = None
    status: BankStatementStatus | None = None


class BankStatementLineInput(BaseModel):
    line_date: date
    description: str | None = None
    reference: str | None = None
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)


class BankStatementCreate(BaseModel):
    bank_account_id: UUID
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    import_reference: str | None = None
    notes: str | None = None
    lines: list[BankStatementLineInput] = Field(default_factory=list)


class BankStatementUpdate(BaseModel):
    period_start: date | None = None
    period_end: date | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    notes: str | None = None
    version: int


class BankStatementLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int
    line_date: date
    description: str | None
    reference: str | None
    debit: Decimal
    credit: Decimal
    match_status: BankStatementMatchStatus
    matched_journal_line_id: UUID | None


class BankStatementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    bank_account_id: UUID
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    status: BankStatementStatus
    import_reference: str | None
    notes: str | None
    version: int
    lines: list[BankStatementLineResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None


class BookEntryCandidate(BaseModel):
    journal_line_id: UUID
    journal_entry_id: UUID
    entry_date: date
    document_number: str | None
    narration: str | None
    reference: str | None
    debit: Decimal
    credit: Decimal
    is_matched: bool


class MatchSuggestion(BaseModel):
    statement_line_id: UUID
    journal_line_id: UUID
    score: int
    reason: str


class MatchRequest(BaseModel):
    statement_line_id: UUID
    journal_line_id: UUID
    version: int


class UnmatchRequest(BaseModel):
    statement_line_id: UUID
    version: int


class ExcludeLineRequest(BaseModel):
    statement_line_id: UUID
    version: int


class ReconciliationStatement(BaseModel):
    bank_account_id: UUID
    period_start: date
    period_end: date
    book_balance: Decimal
    statement_balance: Decimal
    unmatched_statement_total: Decimal
    unmatched_book_total: Decimal
    reconciled_balance: Decimal
    currency_id: UUID
