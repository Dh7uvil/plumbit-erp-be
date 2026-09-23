"""Budget routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status

from app.auth.catalog import (
    BUDGET_ACTIVATE,
    BUDGET_CLOSE,
    BUDGET_CREATE,
    BUDGET_DELETE,
    BUDGET_READ,
    BUDGET_UPDATE,
    REPORT_FINANCIAL,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.accounting.budgets.dependencies import BudgetServiceDependency
from app.erp.accounting.budgets.schemas import (
    BudgetCreate,
    BudgetFilter,
    BudgetResponse,
    BudgetUpdate,
    BudgetVsActualResponse,
)
from app.erp.accounting.reports.dependencies import ReportServiceDependency

router = APIRouter(prefix="/budgets", tags=["Budgets"])
IfMatch = Annotated[str | None, Header(alias="If-Match")]


@router.get("", response_model=ApiResponse[list[BudgetResponse]])
async def list_budgets(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: BudgetServiceDependency,
    filters: Annotated[BudgetFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(BUDGET_READ))],
) -> ApiResponse[list[BudgetResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        fiscal_year=filters.fiscal_year,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[BudgetResponse], status_code=status.HTTP_201_CREATED)
async def create_budget(
    payload: BudgetCreate,
    tenant: TenantContextDependency,
    service: BudgetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BUDGET_CREATE))],
) -> ApiResponse[BudgetResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Budget created successfully")


@router.get("/{budget_id}", response_model=ApiResponse[BudgetResponse])
async def get_budget(
    budget_id: UUID,
    tenant: TenantContextDependency,
    service: BudgetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BUDGET_READ))],
) -> ApiResponse[BudgetResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, budget_id))


@router.get("/{budget_id}/vs-actual", response_model=ApiResponse[BudgetVsActualResponse])
async def budget_vs_actual(
    budget_id: UUID,
    tenant: TenantContextDependency,
    reports: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_FINANCIAL))],
    __: Annotated[CurrentUser, Depends(require_permission(BUDGET_READ))],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> ApiResponse[BudgetVsActualResponse]:
    start = from_date or date(date.today().year, 1, 1)
    end = to_date or date.today()
    data = await reports.budget_vs_actual(tenant.tenant_id, budget_id, from_date=start, to_date=end)
    return ApiResponse(data=data)


@router.patch("/{budget_id}", response_model=ApiResponse[BudgetResponse])
async def update_budget(
    budget_id: UUID,
    payload: BudgetUpdate,
    tenant: TenantContextDependency,
    service: BudgetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BUDGET_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[BudgetResponse]:
    expected = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.update(
        tenant.tenant_id,
        budget_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=expected,
    )
    return ApiResponse(data=row, message="Budget updated successfully")


@router.delete("/{budget_id}", response_model=ApiResponse[BudgetResponse])
async def delete_budget(
    budget_id: UUID,
    tenant: TenantContextDependency,
    service: BudgetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BUDGET_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[BudgetResponse]:
    expected = require_document_version(if_match=if_match)
    row = await service.delete(
        tenant.tenant_id, budget_id, actor_user_id=tenant.user_id, expected_version=expected
    )
    return ApiResponse(data=row, message="Budget deleted successfully")


@router.post("/{budget_id}/activate", response_model=ApiResponse[BudgetResponse])
async def activate_budget(
    budget_id: UUID,
    tenant: TenantContextDependency,
    service: BudgetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BUDGET_ACTIVATE))],
    if_match: IfMatch = None,
) -> ApiResponse[BudgetResponse]:
    expected = require_document_version(if_match=if_match)
    row = await service.activate(
        tenant.tenant_id, budget_id, actor_user_id=tenant.user_id, expected_version=expected
    )
    return ApiResponse(data=row, message="Budget activated successfully")


@router.post("/{budget_id}/close", response_model=ApiResponse[BudgetResponse])
async def close_budget(
    budget_id: UUID,
    tenant: TenantContextDependency,
    service: BudgetServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BUDGET_CLOSE))],
    if_match: IfMatch = None,
) -> ApiResponse[BudgetResponse]:
    expected = require_document_version(if_match=if_match)
    row = await service.close(
        tenant.tenant_id, budget_id, actor_user_id=tenant.user_id, expected_version=expected
    )
    return ApiResponse(data=row, message="Budget closed successfully")
