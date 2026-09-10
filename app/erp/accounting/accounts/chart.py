"""UAE default chart of accounts. Seeded only when the tenant has zero accounts."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import AccountSubtype, AccountSystemRole, AccountType


@dataclass(frozen=True, slots=True)
class ChartSeedRow:
    code: str
    name: str
    account_type: AccountType
    account_subtype: AccountSubtype
    parent_code: str | None
    is_group: bool
    system_role: AccountSystemRole | None = None


UAE_CHART: tuple[ChartSeedRow, ...] = (
    ChartSeedRow(
        "1000", "Current Assets", AccountType.ASSET, AccountSubtype.OTHER_CURRENT_ASSET, None, True
    ),
    ChartSeedRow(
        "1010",
        "Cash on Hand",
        AccountType.ASSET,
        AccountSubtype.CASH,
        "1000",
        False,
        AccountSystemRole.CASH_ON_HAND,
    ),
    ChartSeedRow(
        "1020",
        "Bank",
        AccountType.ASSET,
        AccountSubtype.BANK,
        "1000",
        False,
        AccountSystemRole.BANK,
    ),
    ChartSeedRow(
        "1100",
        "Accounts Receivable",
        AccountType.ASSET,
        AccountSubtype.ACCOUNTS_RECEIVABLE,
        "1000",
        False,
        AccountSystemRole.ACCOUNTS_RECEIVABLE,
    ),
    ChartSeedRow(
        "1110",
        "Advance to Supplier",
        AccountType.ASSET,
        AccountSubtype.OTHER_CURRENT_ASSET,
        "1000",
        False,
        AccountSystemRole.ADVANCE_TO_SUPPLIER,
    ),
    ChartSeedRow(
        "1200",
        "Inventory",
        AccountType.ASSET,
        AccountSubtype.STOCK,
        "1000",
        False,
        AccountSystemRole.INVENTORY,
    ),
    ChartSeedRow(
        "1300",
        "VAT Input",
        AccountType.ASSET,
        AccountSubtype.TAX_RECEIVABLE,
        "1000",
        False,
        AccountSystemRole.VAT_INPUT,
    ),
    ChartSeedRow(
        "1310",
        "VAT RCM Input",
        AccountType.ASSET,
        AccountSubtype.TAX_RECEIVABLE,
        "1000",
        False,
        AccountSystemRole.VAT_RCM_INPUT,
    ),
    ChartSeedRow(
        "1400",
        "Other Current Assets",
        AccountType.ASSET,
        AccountSubtype.OTHER_CURRENT_ASSET,
        "1000",
        False,
    ),
    ChartSeedRow(
        "1500", "Non-current Assets", AccountType.ASSET, AccountSubtype.FIXED_ASSET, None, True
    ),
    ChartSeedRow(
        "1510", "Fixed Assets", AccountType.ASSET, AccountSubtype.FIXED_ASSET, "1500", False
    ),
    ChartSeedRow(
        "2000",
        "Current Liabilities",
        AccountType.LIABILITY,
        AccountSubtype.OTHER_CURRENT_LIABILITY,
        None,
        True,
    ),
    ChartSeedRow(
        "2010",
        "Accounts Payable",
        AccountType.LIABILITY,
        AccountSubtype.ACCOUNTS_PAYABLE,
        "2000",
        False,
        AccountSystemRole.ACCOUNTS_PAYABLE,
    ),
    ChartSeedRow(
        "2020",
        "Advance from Customer",
        AccountType.LIABILITY,
        AccountSubtype.OTHER_CURRENT_LIABILITY,
        "2000",
        False,
        AccountSystemRole.ADVANCE_FROM_CUSTOMER,
    ),
    ChartSeedRow(
        "2100",
        "VAT Output",
        AccountType.LIABILITY,
        AccountSubtype.TAX_PAYABLE,
        "2000",
        False,
        AccountSystemRole.VAT_OUTPUT,
    ),
    ChartSeedRow(
        "2110",
        "VAT RCM Output",
        AccountType.LIABILITY,
        AccountSubtype.TAX_PAYABLE,
        "2000",
        False,
        AccountSystemRole.VAT_RCM_OUTPUT,
    ),
    ChartSeedRow(
        "2200",
        "Other Current Liabilities",
        AccountType.LIABILITY,
        AccountSubtype.OTHER_CURRENT_LIABILITY,
        "2000",
        False,
    ),
    ChartSeedRow("3000", "Equity", AccountType.EQUITY, AccountSubtype.EQUITY, None, True),
    ChartSeedRow(
        "3100",
        "Opening Balance Equity",
        AccountType.EQUITY,
        AccountSubtype.EQUITY,
        "3000",
        False,
        AccountSystemRole.OPENING_BALANCE_EQUITY,
    ),
    ChartSeedRow(
        "3200",
        "Retained Earnings",
        AccountType.EQUITY,
        AccountSubtype.EQUITY,
        "3000",
        False,
        AccountSystemRole.RETAINED_EARNINGS,
    ),
    ChartSeedRow("4000", "Income", AccountType.INCOME, AccountSubtype.INCOME, None, True),
    ChartSeedRow(
        "4100",
        "Sales Revenue",
        AccountType.INCOME,
        AccountSubtype.INCOME,
        "4000",
        False,
        AccountSystemRole.SALES_REVENUE,
    ),
    ChartSeedRow(
        "4200",
        "Sales Returns",
        AccountType.INCOME,
        AccountSubtype.INCOME,
        "4000",
        False,
        AccountSystemRole.SALES_RETURNS,
    ),
    ChartSeedRow(
        "4300", "Other Income", AccountType.INCOME, AccountSubtype.OTHER_INCOME, "4000", False
    ),
    ChartSeedRow(
        "4400",
        "FX Gain/Loss",
        AccountType.INCOME,
        AccountSubtype.OTHER_INCOME,
        "4000",
        False,
        AccountSystemRole.FX_GAIN_LOSS,
    ),
    ChartSeedRow(
        "4500",
        "Round Off",
        AccountType.INCOME,
        AccountSubtype.OTHER_INCOME,
        "4000",
        False,
        AccountSystemRole.ROUND_OFF,
    ),
    ChartSeedRow("5000", "Cost of Sales", AccountType.EXPENSE, AccountSubtype.COGS, None, True),
    ChartSeedRow(
        "5100",
        "Purchases",
        AccountType.EXPENSE,
        AccountSubtype.COGS,
        "5000",
        False,
        AccountSystemRole.PURCHASES,
    ),
    ChartSeedRow(
        "5200",
        "Cost of Goods Sold",
        AccountType.EXPENSE,
        AccountSubtype.COGS,
        "5000",
        False,
        AccountSystemRole.COGS,
    ),
    ChartSeedRow(
        "5300",
        "Inventory Adjustment",
        AccountType.EXPENSE,
        AccountSubtype.COGS,
        "5000",
        False,
        AccountSystemRole.INVENTORY_ADJUSTMENT,
    ),
    ChartSeedRow(
        "5400",
        "Stock Scrap",
        AccountType.EXPENSE,
        AccountSubtype.COGS,
        "5000",
        False,
        AccountSystemRole.STOCK_SCRAP,
    ),
    ChartSeedRow(
        "5500",
        "Freight In",
        AccountType.EXPENSE,
        AccountSubtype.COGS,
        "5000",
        False,
        AccountSystemRole.FREIGHT_IN,
    ),
    ChartSeedRow(
        "5600",
        "Customs Duty",
        AccountType.EXPENSE,
        AccountSubtype.COGS,
        "5000",
        False,
        AccountSystemRole.CUSTOMS_DUTY,
    ),
    ChartSeedRow(
        "5700",
        "Purchase Price Variance",
        AccountType.EXPENSE,
        AccountSubtype.COGS,
        "5000",
        False,
        AccountSystemRole.PURCHASE_PRICE_VARIANCE,
    ),
    ChartSeedRow(
        "6000",
        "Operating Expenses",
        AccountType.EXPENSE,
        AccountSubtype.EXPENSE,
        None,
        True,
    ),
    ChartSeedRow(
        "6100", "Other Expense", AccountType.EXPENSE, AccountSubtype.OTHER_EXPENSE, "6000", False
    ),
    ChartSeedRow(
        "9990",
        "Suspense",
        AccountType.ASSET,
        AccountSubtype.OTHER_CURRENT_ASSET,
        None,
        False,
        AccountSystemRole.SUSPENSE,
    ),
)
