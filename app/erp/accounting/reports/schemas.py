"""Ledger report request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReportWarning(BaseModel):
    code: str
    message: str
    document_id: UUID | None = None
    document_number: str | None = None


class ReportCurrencyMixin(BaseModel):
    currency_code: str = Field(
        description="ISO currency code for all monetary amounts (tenant base currency).",
    )


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
    closing_net_debit: Decimal = Decimal("0")
    closing_net_credit: Decimal = Decimal("0")


class TrialBalanceResponse(ReportCurrencyMixin):
    from_date: date
    to_date: date
    is_balanced: bool
    total_opening_debit: Decimal
    total_opening_credit: Decimal
    total_period_debit: Decimal
    total_period_credit: Decimal
    total_closing_debit: Decimal
    total_closing_credit: Decimal
    total_closing_net_debit: Decimal = Decimal("0")
    total_closing_net_credit: Decimal = Decimal("0")
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


class GeneralLedgerResponse(ReportCurrencyMixin):
    account_id: UUID
    account_code: str
    account_name: str
    from_date: date
    to_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    page: int = 1
    page_size: int | None = None
    total_lines: int = 0
    lines: list[GeneralLedgerLine] = Field(default_factory=list)


class DayBookLine(BaseModel):
    row_type: str
    account_id: UUID | None = None
    account_code: str | None = None
    account_name: str | None = None
    entry_date: date | None = None
    journal_entry_id: UUID | None = None
    journal_entry_line_id: UUID | None = None
    document_number: str | None = None
    source_type: str | None = None
    source_id: UUID | None = None
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    running_balance: Decimal
    party_id: UUID | None = None
    description: str | None = None
    narration: str | None = None


class DayBookAccountSection(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    opening_balance: Decimal
    closing_balance: Decimal
    lines: list[DayBookLine] = Field(default_factory=list)


class DayBookResponse(ReportCurrencyMixin):
    book_kind: str
    from_date: date
    to_date: date
    account_id: UUID | None = None
    combined_opening_balance: Decimal
    combined_closing_balance: Decimal
    sections: list[DayBookAccountSection] = Field(default_factory=list)
    lines: list[DayBookLine] = Field(default_factory=list)


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


class AccountStatementResponse(ReportCurrencyMixin):
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


class ExportEvidenceExceptionResponse(ReportCurrencyMixin):
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


class InvoicedNotDispatchedResponse(ReportCurrencyMixin):
    lines: list[InvoicedNotDispatchedLine] = Field(default_factory=list)


class AgingBucketTotals(BaseModel):
    current: Decimal = Decimal("0")
    days_1_30: Decimal = Decimal("0")
    days_31_60: Decimal = Decimal("0")
    days_61_90: Decimal = Decimal("0")
    days_91_plus: Decimal = Decimal("0")
    unapplied_credits: Decimal = Decimal("0")
    total: Decimal = Decimal("0")


class AgingDocument(BaseModel):
    item_type: str
    document_id: UUID
    document_number: str
    document_date: date
    due_date: date | None = None
    currency_code: str | None = None
    exchange_rate: Decimal | None = None
    document_balance: Decimal | None = Field(
        default=None,
        description="Original document-currency balance (informational only).",
    )
    balance: Decimal
    bucket: str


class AgingPartyRow(AgingBucketTotals):
    party_id: UUID
    party_name: str
    documents: list[AgingDocument] = Field(default_factory=list)


class AgingResponse(ReportCurrencyMixin):
    as_of: date
    rows: list[AgingPartyRow] = Field(default_factory=list)
    totals: AgingBucketTotals
    warnings: list[ReportWarning] = Field(default_factory=list)


class PartyStatementLine(BaseModel):
    document_type: str
    document_id: UUID
    document_number: str
    document_date: date
    due_date: date | None = None
    currency_code: str | None = None
    exchange_rate: Decimal | None = None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal
    description: str | None = None


class PartyStatementResponse(ReportCurrencyMixin):
    party_type: str
    party_id: UUID
    party_name: str
    from_date: date
    to_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    lines: list[PartyStatementLine] = Field(default_factory=list)


class OutstandingSummary(ReportCurrencyMixin):
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


class StockWarehouseTotal(BaseModel):
    warehouse_id: UUID
    warehouse_code: str
    warehouse_name: str
    total_qty: Decimal
    total_value: Decimal


class StockValuationResponse(ReportCurrencyMixin):
    as_of: date
    total_qty: Decimal
    total_value: Decimal
    warehouse_totals: list[StockWarehouseTotal] = Field(default_factory=list)
    lines: list[StockValuationLine] = Field(default_factory=list)


class StockValuationGlResponse(ReportCurrencyMixin):
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


class StockMovementReportResponse(ReportCurrencyMixin):
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


class StockAgingResponse(ReportCurrencyMixin):
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


class PurchaseSuggestionResponse(ReportCurrencyMixin):
    as_of: date
    lines: list[PurchaseSuggestionLine] = Field(default_factory=list)


class PeriodAmount(BaseModel):
    label: str
    from_date: date
    to_date: date
    amount: Decimal


class ProfitAndLossLine(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    account_type: str
    account_subtype: str
    amount: Decimal
    comparative_amount: Decimal | None = None
    ytd_amount: Decimal | None = None
    budget_amount: Decimal | None = None
    variance_amount: Decimal | None = None
    group_label: str | None = None
    source_type: str | None = None
    source_id: UUID | None = None
    periods: list[PeriodAmount] = Field(default_factory=list)


class ProfitAndLossResponse(ReportCurrencyMixin):
    from_date: date
    to_date: date
    comparative_from: date | None = None
    comparative_to: date | None = None
    ytd_from: date | None = None
    total_income: Decimal
    total_cogs: Decimal = Decimal("0")
    total_operating_expense: Decimal = Decimal("0")
    total_expense: Decimal
    gross_profit: Decimal = Decimal("0")
    net_profit: Decimal
    comparative_gross_profit: Decimal | None = None
    comparative_net_profit: Decimal | None = None
    ytd_gross_profit: Decimal | None = None
    ytd_net_profit: Decimal | None = None
    period_count: int = 1
    budget_id: UUID | None = None
    lines: list[ProfitAndLossLine] = Field(default_factory=list)


class CostCenterProfitSection(BaseModel):
    cost_center_id: UUID | None = None
    cost_center_code: str
    cost_center_name: str
    total_income: Decimal
    total_expense: Decimal
    net_profit: Decimal
    lines: list[ProfitAndLossLine] = Field(default_factory=list)


class CostCenterProfitAndLossResponse(ReportCurrencyMixin):
    from_date: date
    to_date: date
    sections: list[CostCenterProfitSection] = Field(default_factory=list)


class ReportExportCreate(BaseModel):
    report: str = Field(min_length=1, max_length=60)
    export_format: str = Field(pattern="^(csv|xlsx|pdf)$")
    params: dict[str, str] = Field(default_factory=dict)


class ReportExportJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_key: str
    export_format: str
    status: str
    filename: str | None = None
    error: str | None = None
    created_at: datetime


class BalanceSheetLine(BaseModel):
    account_id: UUID | None = None
    account_code: str
    account_name: str
    account_type: str
    account_subtype: str
    amount: Decimal
    comparative_amount: Decimal | None = None
    group_label: str | None = None
    source_type: str | None = None
    source_id: UUID | None = None


class BalanceSheetResponse(ReportCurrencyMixin):
    as_of: date
    comparative_as_of: date | None = None
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    current_earnings: Decimal
    comparative_total_assets: Decimal | None = None
    comparative_total_liabilities: Decimal | None = None
    comparative_total_equity: Decimal | None = None
    is_balanced: bool
    lines: list[BalanceSheetLine] = Field(default_factory=list)


class CashFlowLine(BaseModel):
    key: str
    label: str
    amount: Decimal
    comparative_amount: Decimal | None = None
    account_id: UUID | None = None
    source_type: str | None = None
    source_id: UUID | None = None


class CashFlowResponse(ReportCurrencyMixin):
    from_date: date
    to_date: date
    comparative_from: date | None = None
    comparative_to: date | None = None
    net_profit: Decimal
    cash_opening: Decimal
    cash_closing: Decimal
    net_change: Decimal
    comparative_net_change: Decimal | None = None
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


class TaxRegisterResponse(ReportCurrencyMixin):
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


class Vat201Response(ReportCurrencyMixin):
    from_date: date
    to_date: date
    boxes: list[Vat201Box] = Field(default_factory=list)
    recoverable_input_vat: Decimal
    net_vat: Decimal
    export_evidence_exceptions: int


class ThreeWayMatchLine(BaseModel):
    purchase_order_id: UUID
    purchase_order_line_id: UUID
    document_number: str
    order_date: date
    supplier_id: UUID
    supplier_name: str
    product_id: UUID | None
    description: str
    ordered_qty: Decimal
    received_qty: Decimal
    billed_qty: Decimal
    ordered_value: Decimal
    received_value: Decimal
    billed_value: Decimal
    status: str


class ThreeWayMatchResponse(ReportCurrencyMixin):
    lines: list[ThreeWayMatchLine] = Field(default_factory=list)


class ReceivedNotBilledLine(BaseModel):
    goods_receipt_id: UUID
    goods_receipt_line_id: UUID
    document_number: str
    document_date: date
    supplier_id: UUID
    supplier_name: str
    product_id: UUID | None
    description: str
    quantity: Decimal
    qty_billed: Decimal
    outstanding_qty: Decimal
    amount: Decimal


class ReceivedNotBilledResponse(ReportCurrencyMixin):
    lines: list[ReceivedNotBilledLine] = Field(default_factory=list)


class DashboardUnpostedCount(BaseModel):
    document_type: str
    count: int


class DashboardCreditBreach(BaseModel):
    customer_id: UUID
    customer_name: str
    credit_limit: Decimal
    outstanding: Decimal


class DashboardResponse(ReportCurrencyMixin):
    as_of: date
    open_ar: Decimal
    open_ap: Decimal
    overdue_ar_count: int
    overdue_ap_count: int
    stock_valuation: Decimal
    unposted: list[DashboardUnpostedCount] = Field(default_factory=list)
    deliveries_today: int
    receipts_today: int
    credit_limit_breaches: list[DashboardCreditBreach] = Field(default_factory=list)


class VatGlReconLine(BaseModel):
    key: str
    label: str
    vat_201_amount: Decimal
    gl_amount: Decimal
    difference: Decimal
    account_id: UUID | None = None


class VatGlReconResponse(ReportCurrencyMixin):
    from_date: date
    to_date: date
    lines: list[VatGlReconLine] = Field(default_factory=list)


class OutstandingDocument(BaseModel):
    item_type: str
    document_id: UUID
    document_number: str
    document_date: date
    due_date: date | None = None
    party_id: UUID
    party_name: str
    currency_code: str | None = None
    exchange_rate: Decimal | None = None
    document_balance: Decimal | None = None
    balance: Decimal
    bucket: str
    days_overdue: int = 0


class OutstandingDocumentsResponse(ReportCurrencyMixin):
    as_of: date
    party_type: str
    total_balance: Decimal
    lines: list[OutstandingDocument] = Field(default_factory=list)
    warnings: list[ReportWarning] = Field(default_factory=list)


class SalesPurchaseAnalysisLine(BaseModel):
    group_key: str
    group_label: str
    document_count: int
    net_amount: Decimal
    tax_amount: Decimal
    grand_total: Decimal
    account_id: UUID | None = None
    party_id: UUID | None = None
    product_id: UUID | None = None
    salesperson_id: UUID | None = None


class SalesPurchaseAnalysisResponse(ReportCurrencyMixin):
    from_date: date
    to_date: date
    group_by: str
    document_count: int
    total_net: Decimal
    total_tax: Decimal
    total_grand: Decimal
    warnings: list[str] = Field(default_factory=list)
    lines: list[SalesPurchaseAnalysisLine] = Field(default_factory=list)
