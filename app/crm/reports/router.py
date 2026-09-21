"""CRM report routes on the shared `/reports` prefix."""

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.auth.catalog import REPORT_CRM, REPORT_EXPORT
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.core.exceptions import PermissionDeniedError
from app.core.permissions import has_permission
from app.crm.reports.constants import (
    DEFAULT_ACTIVITY_GROUP,
    DEFAULT_LEAD_CONVERSION_GROUP,
    DEFAULT_PIPELINE_GROUP,
    DEFAULT_WIN_LOSS_GROUP,
)
from app.crm.reports.dependencies import CrmReportServiceDependency
from app.crm.reports.schemas import (
    CrmDashboardResponse,
    LeadConversionResponse,
    SalesActivityResponse,
    SalesFunnelResponse,
    SalesPipelineResponse,
    WinLossResponse,
)
from app.erp.accounting.reports.csv_export import (
    csv_response,
    rows_from_models,
    wants_csv,
    wants_excel,
)

router = APIRouter(prefix="/reports", tags=["Reports"])

FormatQuery = Annotated[str | None, Query(alias="format")]


def _maybe_csv(
    request: Request,
    format: str | None,
    data: BaseModel,
    user: CurrentUser,
    *,
    filename: str,
    line_attr: str = "lines",
) -> Any:
    if not wants_csv(request, format):
        return ApiResponse(data=data)
    if not has_permission(user.permissions, REPORT_EXPORT):
        raise PermissionDeniedError()
    items = getattr(data, line_attr, None)
    if isinstance(items, list) and items:
        fields, rows = rows_from_models(items)
    else:
        dumped = data.model_dump(mode="json")
        fields = [key for key, value in dumped.items() if not isinstance(value, list)]
        rows = [{key: dumped.get(key) for key in fields}]
    return csv_response(filename, fields, rows, excel=wants_excel(format))


@router.get("/sales-pipeline", response_model=ApiResponse[SalesPipelineResponse])
async def get_sales_pipeline(
    request: Request,
    tenant: TenantContextDependency,
    service: CrmReportServiceDependency,
    user: Annotated[CurrentUser, Depends(require_permission(REPORT_CRM))],
    group_by: str = DEFAULT_PIPELINE_GROUP,
    pipeline_id: UUID | None = None,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.sales_pipeline(
        tenant.tenant_id, group_by=group_by, pipeline_id=pipeline_id
    )
    return _maybe_csv(request, export_format, data, user, filename="sales-pipeline.csv")


@router.get("/sales-funnel", response_model=ApiResponse[SalesFunnelResponse])
async def get_sales_funnel(
    request: Request,
    tenant: TenantContextDependency,
    service: CrmReportServiceDependency,
    user: Annotated[CurrentUser, Depends(require_permission(REPORT_CRM))],
    pipeline_id: UUID | None = None,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.sales_funnel(tenant.tenant_id, pipeline_id=pipeline_id)
    return _maybe_csv(request, export_format, data, user, filename="sales-funnel.csv")


@router.get("/win-loss", response_model=ApiResponse[WinLossResponse])
async def get_win_loss(
    request: Request,
    tenant: TenantContextDependency,
    service: CrmReportServiceDependency,
    user: Annotated[CurrentUser, Depends(require_permission(REPORT_CRM))],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    group_by: str = DEFAULT_WIN_LOSS_GROUP,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.win_loss(
        tenant.tenant_id, from_date=from_date, to_date=to_date, group_by=group_by
    )
    return _maybe_csv(request, export_format, data, user, filename="win-loss.csv")


@router.get("/lead-conversion", response_model=ApiResponse[LeadConversionResponse])
async def get_lead_conversion(
    request: Request,
    tenant: TenantContextDependency,
    service: CrmReportServiceDependency,
    user: Annotated[CurrentUser, Depends(require_permission(REPORT_CRM))],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    group_by: str = DEFAULT_LEAD_CONVERSION_GROUP,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.lead_conversion(
        tenant.tenant_id, from_date=from_date, to_date=to_date, group_by=group_by
    )
    return _maybe_csv(request, export_format, data, user, filename="lead-conversion.csv")


@router.get("/sales-activity", response_model=ApiResponse[SalesActivityResponse])
async def get_sales_activity(
    request: Request,
    tenant: TenantContextDependency,
    service: CrmReportServiceDependency,
    user: Annotated[CurrentUser, Depends(require_permission(REPORT_CRM))],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    group_by: str = DEFAULT_ACTIVITY_GROUP,
    export_format: FormatQuery = None,
) -> Any:
    data = await service.sales_activity(
        tenant.tenant_id, from_date=from_date, to_date=to_date, group_by=group_by
    )
    return _maybe_csv(request, export_format, data, user, filename="sales-activity.csv")


@router.get("/crm-dashboard", response_model=ApiResponse[CrmDashboardResponse])
async def get_crm_dashboard(
    tenant: TenantContextDependency,
    service: CrmReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_CRM))],
) -> ApiResponse[CrmDashboardResponse]:
    return ApiResponse(data=await service.dashboard(tenant.tenant_id))
