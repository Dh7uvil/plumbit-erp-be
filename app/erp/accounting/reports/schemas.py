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


class ExportEvidenceExceptionLine(BaseModel):
    sales_invoice_id: UUID
    document_number: str
    invoice_date: date
    customer_id: UUID
    customer_name: str
    grand_total: Decimal
    days_elapsed: int
    window_days: int
    overdue: bool


class ExportEvidenceExceptionResponse(BaseModel):
    as_of: date
    window_days: int
    lines: list[ExportEvidenceExceptionLine] = Field(default_factory=list)


class InvoicedNotDispatchedLine(BaseModel):
    sales_invoice_id: UUID
    sales_invoice_line_id: UUID
    document_number: str
    invoice_date: date
    customer_id: UUID
    customer_name: str
    product_id: UUID | None
    description: str
    quantity: Decimal
    amount: Decimal
    cogs_status: str


class InvoicedNotDispatchedResponse(BaseModel):
    lines: list[InvoicedNotDispatchedLine] = Field(default_factory=list)


class AgingBucketTotals(BaseModel):
    current: Decimal = Decimal("0")
    days_1_30: Decimal = Decimal("0")
    days_31_60: Decimal = Decimal("0")
    days_61_90: Decimal = Decimal("0")
    days_91_plus: Decimal = Decimal("0")
    unapplied_credits: Decimal = Decimal("0")
    total: Decimal = Decimal("0")


class AgingPartyRow(AgingBucketTotals):
    party_id: UUID
    party_name: str
    currency_id: UUID | None = None


class AgingResponse(BaseModel):
    as_of: date
    rows: list[AgingPartyRow] = Field(default_factory=list)
    totals: AgingBucketTotals


class PartyStatementLine(BaseModel):
    document_type: str
    document_id: UUID
    document_number: str
    document_date: date
    due_date: date | None = None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal
    description: str | None = None


class PartyStatementResponse(BaseModel):
    party_type: str
    party_id: UUID
    party_name: str
    from_date: date
    to_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    lines: list[PartyStatementLine] = Field(default_factory=list)


class OutstandingSummary(BaseModel):
    party_id: UUID
    balance_due: Decimal
    overdue: Decimal
    unapplied_credits: Decimal
    credit_limit: Decimal | None = None
    available_credit: Decimal | None = None
