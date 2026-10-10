"""Salesman targets routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.catalog import SALESMAN_READ, SALESMAN_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.erp.salesmen.dependencies import SalesmanServiceDependency
from app.erp.salesmen.schemas import SalesmanOverviewRow, SalesmanTargetsUpdate

router = APIRouter(prefix="/salesmen", tags=["Salesmen"])


@router.get("", response_model=ApiResponse[list[SalesmanOverviewRow]])
async def list_salesmen(
    tenant: TenantContextDependency,
    service: SalesmanServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALESMAN_READ))],
    fiscal_year: Annotated[int | None, Query()] = None,
) -> ApiResponse[list[SalesmanOverviewRow]]:
    return ApiResponse(data=await service.list_overview(tenant.tenant_id, fiscal_year=fiscal_year))


@router.put("/{employee_id}/targets", response_model=ApiResponse[SalesmanOverviewRow])
async def update_salesman_targets(
    employee_id: UUID,
    payload: SalesmanTargetsUpdate,
    tenant: TenantContextDependency,
    service: SalesmanServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALESMAN_UPDATE))],
) -> ApiResponse[SalesmanOverviewRow]:
    row = await service.update_targets(tenant.tenant_id, employee_id, payload)
    return ApiResponse(data=row, message="Sales targets updated")
