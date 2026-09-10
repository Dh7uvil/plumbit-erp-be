"""Ledger report request/response schemas."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class TrialBalanceLine(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    account_type: str
    is_group: bool
    opening_debit: Decimal
    opening_credit: Decimal
    period_debit: Decimal
    period_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal


class TrialBalanceResponse(BaseModel):
    from_date: date
    to_date: date
    is_balanced: bool
    total_opening_debit: Decimal
    total_opening_credit: Decimal
    total_period_debit: Decimal
    total_period_credit: Decimal
    total_closing_debit: Decimal
    total_closing_credit: Decimal
    lines: list[TrialBalanceLine] = Field(default_factory=list)


class GeneralLedgerLine(BaseModel):
    journal_entry_id: UUID
    journal_entry_line_id: UUID
    document_number: str
    entry_date: date
    source_type: str | None
    source_id: UUID | None
    account_id: UUID
    debit: Decimal
    credit: Decimal
    debit_base: Decimal
    credit_base: Decimal
    running_balance: Decimal
    party_id: UUID | None
    description: str | None
    narration: str | None


class GeneralLedgerResponse(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    from_date: date
    to_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    lines: list[GeneralLedgerLine] = Field(default_factory=list)


class AccountStatementLine(BaseModel):
    journal_entry_id: UUID
    document_number: str
    entry_date: date
    due_date: date | None
    external_reference: str | None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal
    description: str | None


class AccountStatementResponse(BaseModel):
    party_type: str
    party_id: UUID
    from_date: date
    to_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    lines: list[AccountStatementLine] = Field(default_factory=list)
