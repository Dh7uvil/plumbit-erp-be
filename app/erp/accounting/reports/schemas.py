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


class StockValuationLine(BaseModel):
    warehouse_id: UUID
    warehouse_code: str
    warehouse_name: str
    product_id: UUID
    sku: str
    product_name: str
    category_id: UUID | None = None
    qty_remaining: Decimal
    landed_unit_cost: Decimal
    stock_value: Decimal
    document_date: date
    layer_id: UUID


class StockValuationResponse(BaseModel):
    as_of: date
    total_qty: Decimal
    total_value: Decimal
    lines: list[StockValuationLine] = Field(default_factory=list)


class StockValuationGlResponse(BaseModel):
    as_of: date
    inventory_account_id: UUID | None = None
    valuation_total: Decimal
    gl_balance: Decimal
    difference: Decimal


class StockMovementReportLine(BaseModel):
    warehouse_id: UUID
    warehouse_code: str
    warehouse_name: str
    product_id: UUID
    sku: str
    product_name: str
    opening_qty: Decimal
    opening_value: Decimal
    qty_in: Decimal
    value_in: Decimal
    qty_out: Decimal
    value_out: Decimal
    closing_qty: Decimal
    closing_value: Decimal


class StockMovementReportResponse(BaseModel):
    from_date: date
    to_date: date
    lines: list[StockMovementReportLine] = Field(default_factory=list)
    total_opening_qty: Decimal
    total_opening_value: Decimal
    total_closing_qty: Decimal
    total_closing_value: Decimal


class StockAgingLine(BaseModel):
    warehouse_id: UUID
    warehouse_code: str
    warehouse_name: str
    product_id: UUID
    sku: str
    product_name: str
    layer_id: UUID
    document_date: date
    days: int
    bucket: str
    qty_remaining: Decimal
    stock_value: Decimal


class StockAgingBucketTotals(BaseModel):
    days_0_30: Decimal = Decimal("0")
    days_31_60: Decimal = Decimal("0")
    days_61_90: Decimal = Decimal("0")
    days_91_plus: Decimal = Decimal("0")
    total: Decimal = Decimal("0")


class StockAgingResponse(BaseModel):
    as_of: date
    lines: list[StockAgingLine] = Field(default_factory=list)
    totals: StockAgingBucketTotals


class PurchaseSuggestionLine(BaseModel):
    warehouse_id: UUID
    warehouse_code: str
    warehouse_name: str
    product_id: UUID
    sku: str
    product_name: str
    qty_on_hand: Decimal
    qty_available: Decimal
    reorder_level: Decimal | None = None
    reorder_qty: Decimal | None = None
    suggested_qty: Decimal
    preferred_supplier_id: UUID | None = None
    preferred_supplier_name: str | None = None


class PurchaseSuggestionResponse(BaseModel):
    as_of: date
    lines: list[PurchaseSuggestionLine] = Field(default_factory=list)


class ProfitAndLossLine(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    account_type: str
    account_subtype: str
    amount: Decimal
    comparative_amount: Decimal | None = None
    ytd_amount: Decimal | None = None


class ProfitAndLossResponse(BaseModel):
    from_date: date
    to_date: date
    comparative_from: date | None = None
    comparative_to: date | None = None
    ytd_from: date | None = None
    total_income: Decimal
    total_expense: Decimal
    net_profit: Decimal
    comparative_net_profit: Decimal | None = None
    ytd_net_profit: Decimal | None = None
    lines: list[ProfitAndLossLine] = Field(default_factory=list)


class BalanceSheetLine(BaseModel):
    account_id: UUID | None = None
    account_code: str
    account_name: str
    account_type: str
    account_subtype: str
    amount: Decimal


class BalanceSheetResponse(BaseModel):
    as_of: date
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    current_earnings: Decimal
    is_balanced: bool
    lines: list[BalanceSheetLine] = Field(default_factory=list)


class CashFlowLine(BaseModel):
    key: str
    label: str
    amount: Decimal
    account_id: UUID | None = None


class CashFlowResponse(BaseModel):
    from_date: date
    to_date: date
    net_profit: Decimal
    cash_opening: Decimal
    cash_closing: Decimal
    net_change: Decimal
    lines: list[CashFlowLine] = Field(default_factory=list)


class TaxRegisterLine(BaseModel):
    document_type: str
    document_id: UUID
    document_number: str
    document_date: date
    party_id: UUID
    party_name: str
    party_trn: str | None = None
    tax_treatment: str
    tax_category: str | None = None
    place_of_supply: str
    net_amount: Decimal
    tax_amount: Decimal
    grand_total: Decimal
    is_export: bool = False
    is_reverse_charge: bool = False
    is_designated_zone: bool = False


class TaxRegisterResponse(BaseModel):
    from_date: date
    to_date: date
    total_net: Decimal
    total_tax: Decimal
    total_grand: Decimal
    lines: list[TaxRegisterLine] = Field(default_factory=list)


class Vat201Box(BaseModel):
    code: str
    label: str
    net_amount: Decimal
    tax_amount: Decimal


class Vat201Response(BaseModel):
    from_date: date
    to_date: date
    boxes: list[Vat201Box] = Field(default_factory=list)
    recoverable_input_vat: Decimal
    net_vat: Decimal
    export_evidence_exceptions: int
