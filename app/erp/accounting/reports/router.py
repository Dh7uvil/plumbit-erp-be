"""Ledger, inventory, financial, and tax report routes."""

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.auth.catalog import (
    REPORT_AR_AP,
    REPORT_FINANCIAL,
    REPORT_INVENTORY,
    REPORT_LEDGER,
    REPORT_TAX,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.core.enums import PartyType
from app.erp.accounting.reports.csv_export import csv_response, rows_from_models, wants_csv
from app.erp.accounting.reports.dependencies import ReportServiceDependency
from app.erp.accounting.reports.schemas import (
    AccountStatementResponse,
    AgingResponse,
    BalanceSheetResponse,
    CashFlowResponse,
    ExportEvidenceExceptionResponse,
    GeneralLedgerResponse,
    InvoicedNotDispatchedResponse,
    PartyStatementResponse,
    ProfitAndLossResponse,
    PurchaseSuggestionResponse,
    StockAgingResponse,
    StockMovementReportResponse,
    StockValuationGlResponse,
    StockValuationResponse,
    TaxRegisterResponse,
    TrialBalanceResponse,
    Vat201Response,
)

router = APIRouter(prefix="/reports", tags=["Reports"])

FormatQuery = Annotated[str | None, Query(alias="format")]


def _maybe_csv(
    request: Request,
    format: str | None,
    data: BaseModel,
    *,
    filename: str,
    line_attr: str = "lines",
) -> Any:
    if not wants_csv(request, format):
        return ApiResponse(data=data)
    items = getattr(data, line_attr, None)
    if isinstance(items, list) and items:
        fields, rows = rows_from_models(items)
    else:
        dumped = data.model_dump(mode="json")
        fields = [key for key, value in dumped.items() if not isinstance(value, list)]
        rows = [{key: dumped.get(key) for key in fields}]
    return csv_response(filename, fields, rows)


@router.get("/trial-balance", response_model=ApiResponse[TrialBalanceResponse])
async def get_trial_balance(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_LEDGER))],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    branch_id: UUID | None = None,
    include_zero: bool = False,
) -> ApiResponse[TrialBalanceResponse]:
    return ApiResponse(
        data=await service.trial_balance(
            tenant.tenant_id,
            from_date=from_date,
            to_date=to_date,
            branch_id=branch_id,
            include_zero=include_zero,
        )
    )


@router.get("/general-ledger", response_model=ApiResponse[GeneralLedgerResponse])
async def get_general_ledger(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_LEDGER))],
    account_id: UUID,
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    party_id: UUID | None = None,
    branch_id: UUID | None = None,
) -> ApiResponse[GeneralLedgerResponse]:
    return ApiResponse(
        data=await service.general_ledger(
            tenant.tenant_id,
            account_id=account_id,
            from_date=from_date,
            to_date=to_date,
            party_id=party_id,
            branch_id=branch_id,
        )
    )


@router.get("/account-statement", response_model=ApiResponse[AccountStatementResponse])
async def get_account_statement(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_LEDGER))],
    party_type: PartyType,
    party_id: UUID,
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
) -> ApiResponse[AccountStatementResponse]:
    return ApiResponse(
        data=await service.account_statement(
            tenant.tenant_id,
            party_type=party_type,
            party_id=party_id,
            from_date=from_date,
            to_date=to_date,
        )
    )


@router.get(
    "/export-evidence-exceptions",
    response_model=ApiResponse[ExportEvidenceExceptionResponse],
)
async def get_export_evidence_exceptions(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_TAX))],
    as_of: date | None = None,
) -> ApiResponse[ExportEvidenceExceptionResponse]:
    return ApiResponse(data=await service.export_evidence_exceptions(tenant.tenant_id, as_of=as_of))


@router.get(
    "/invoiced-not-dispatched",
    response_model=ApiResponse[InvoicedNotDispatchedResponse],
)
async def get_invoiced_not_dispatched(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_TAX))],
) -> ApiResponse[InvoicedNotDispatchedResponse]:
    return ApiResponse(data=await service.invoiced_not_dispatched(tenant.tenant_id))


@router.get("/ar-aging", response_model=ApiResponse[AgingResponse])
async def get_ar_aging(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_AR_AP))],
    as_of: date,
) -> ApiResponse[AgingResponse]:
    return ApiResponse(data=await service.ar_aging(tenant.tenant_id, as_of=as_of))


@router.get("/ap-aging", response_model=ApiResponse[AgingResponse])
async def get_ap_aging(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_AR_AP))],
    as_of: date,
) -> ApiResponse[AgingResponse]:
    return ApiResponse(data=await service.ap_aging(tenant.tenant_id, as_of=as_of))


@router.get("/customer-statement", response_model=ApiResponse[PartyStatementResponse])
async def get_customer_statement(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_AR_AP))],
    customer_id: UUID,
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
) -> ApiResponse[PartyStatementResponse]:
    return ApiResponse(
        data=await service.customer_statement(
            tenant.tenant_id,
            customer_id,
            from_date=from_date,
            to_date=to_date,
        )
    )


@router.get("/supplier-statement", response_model=ApiResponse[PartyStatementResponse])
async def get_supplier_statement(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_AR_AP))],
    supplier_id: UUID,
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
) -> ApiResponse[PartyStatementResponse]:
    return ApiResponse(
        data=await service.supplier_statement(
            tenant.tenant_id,
            supplier_id,
            from_date=from_date,
            to_date=to_date,
        )
    )


@router.get("/stock-valuation", response_model=ApiResponse[StockValuationResponse])
async def get_stock_valuation(
    request: Request,
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_INVENTORY))],
    as_of: date | None = None,
    warehouse_id: UUID | None = None,
    product_id: UUID | None = None,
    category_id: UUID | None = None,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.stock_valuation(
        tenant.tenant_id,
        as_of=as_of,
        warehouse_id=warehouse_id,
        product_id=product_id,
        category_id=category_id,
    )
    return _maybe_csv(request, export_format, data, filename="stock-valuation.csv")


@router.get("/stock-valuation-gl", response_model=ApiResponse[StockValuationGlResponse])
async def get_stock_valuation_gl(
    request: Request,
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_INVENTORY))],
    as_of: date | None = None,
    warehouse_id: UUID | None = None,
    product_id: UUID | None = None,
    category_id: UUID | None = None,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.stock_valuation_gl(
        tenant.tenant_id,
        as_of=as_of,
        warehouse_id=warehouse_id,
        product_id=product_id,
        category_id=category_id,
    )
    return _maybe_csv(request, export_format, data, filename="stock-valuation-gl.csv")


@router.get("/stock-movement", response_model=ApiResponse[StockMovementReportResponse])
async def get_stock_movement_report(
    request: Request,
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_INVENTORY))],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    warehouse_id: UUID | None = None,
    product_id: UUID | None = None,
    category_id: UUID | None = None,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.stock_movement_report(
        tenant.tenant_id,
        from_date=from_date,
        to_date=to_date,
        warehouse_id=warehouse_id,
        product_id=product_id,
        category_id=category_id,
    )
    return _maybe_csv(request, export_format, data, filename="stock-movement.csv")


@router.get("/stock-aging", response_model=ApiResponse[StockAgingResponse])
async def get_stock_aging(
    request: Request,
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_INVENTORY))],
    as_of: date | None = None,
    warehouse_id: UUID | None = None,
    product_id: UUID | None = None,
    category_id: UUID | None = None,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.stock_aging(
        tenant.tenant_id,
        as_of=as_of,
        warehouse_id=warehouse_id,
        product_id=product_id,
        category_id=category_id,
    )
    return _maybe_csv(request, export_format, data, filename="stock-aging.csv")


@router.get("/purchase-suggestions", response_model=ApiResponse[PurchaseSuggestionResponse])
async def get_purchase_suggestions(
    request: Request,
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_INVENTORY))],
    warehouse_id: UUID | None = None,
    product_id: UUID | None = None,
    category_id: UUID | None = None,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.purchase_suggestions(
        tenant.tenant_id,
        warehouse_id=warehouse_id,
        product_id=product_id,
        category_id=category_id,
    )
    return _maybe_csv(request, export_format, data, filename="purchase-suggestions.csv")


@router.get("/profit-and-loss", response_model=ApiResponse[ProfitAndLossResponse])
async def get_profit_and_loss(
    request: Request,
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_FINANCIAL))],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    branch_id: UUID | None = None,
    include_ytd: bool = False,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.profit_and_loss(
        tenant.tenant_id,
        from_date=from_date,
        to_date=to_date,
        branch_id=branch_id,
        include_ytd=include_ytd,
    )
    return _maybe_csv(request, export_format, data, filename="profit-and-loss.csv")


@router.get("/balance-sheet", response_model=ApiResponse[BalanceSheetResponse])
async def get_balance_sheet(
    request: Request,
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_FINANCIAL))],
    as_of: date,
    branch_id: UUID | None = None,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.balance_sheet(tenant.tenant_id, as_of=as_of, branch_id=branch_id)
    return _maybe_csv(request, export_format, data, filename="balance-sheet.csv")


@router.get("/cash-flow", response_model=ApiResponse[CashFlowResponse])
async def get_cash_flow(
    request: Request,
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_FINANCIAL))],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    branch_id: UUID | None = None,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.cash_flow(
        tenant.tenant_id,
        from_date=from_date,
        to_date=to_date,
        branch_id=branch_id,
    )
    return _maybe_csv(request, export_format, data, filename="cash-flow.csv")


@router.get("/sales-register", response_model=ApiResponse[TaxRegisterResponse])
async def get_sales_register(
    request: Request,
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_TAX))],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    export_format: FormatQuery = None,
) -> Any:
    data = await service.sales_register(tenant.tenant_id, from_date=from_date, to_date=to_date)
    return _maybe_csv(request, export_format, data, filename="sales-register.csv")


@router.get("/purchase-register", response_model=ApiResponse[TaxRegisterResponse])
async def get_purchase_register(
    request: Request,
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_TAX))],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    export_format: FormatQuery = None,
) -> Any:
    data = await service.purchase_register(tenant.tenant_id, from_date=from_date, to_date=to_date)
    return _maybe_csv(request, export_format, data, filename="purchase-register.csv")


@router.get("/vat-201", response_model=ApiResponse[Vat201Response])
async def get_vat_201(
    request: Request,
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_TAX))],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    export_format: FormatQuery = None,
) -> Any:
    data = await service.vat_201(tenant.tenant_id, from_date=from_date, to_date=to_date)
    return _maybe_csv(request, export_format, data, filename="vat-201.csv", line_attr="boxes")
