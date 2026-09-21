"""Cost center routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    COST_CENTER_CREATE,
    COST_CENTER_DELETE,
    COST_CENTER_READ,
    COST_CENTER_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.erp.accounting.cost_centers.dependencies import CostCenterServiceDependency
from app.erp.accounting.cost_centers.schemas import (
    CostCenterCreate,
    CostCenterFilter,
    CostCenterResponse,
    CostCenterUpdate,
)

router = APIRouter(prefix="/cost-centers", tags=["Cost Centers"])


@router.get("", response_model=ApiResponse[list[CostCenterResponse]])
async def list_cost_centers(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CostCenterServiceDependency,
    filters: Annotated[CostCenterFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(COST_CENTER_READ))],
) -> ApiResponse[list[CostCenterResponse]]:
    rows, total = await service.list(
        tenant.tenant_id, page=page, common_filter=filters, is_active=filters.is_active
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[CostCenterResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_cost_center(
    payload: CostCenterCreate,
    tenant: TenantContextDependency,
    service: CostCenterServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_CENTER_CREATE))],
) -> ApiResponse[CostCenterResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Cost center created successfully")


@router.get("/{cost_center_id}", response_model=ApiResponse[CostCenterResponse])
async def get_cost_center(
    cost_center_id: UUID,
    tenant: TenantContextDependency,
    service: CostCenterServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_CENTER_READ))],
) -> ApiResponse[CostCenterResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, cost_center_id))


@router.patch("/{cost_center_id}", response_model=ApiResponse[CostCenterResponse])
async def update_cost_center(
    cost_center_id: UUID,
    payload: CostCenterUpdate,
    tenant: TenantContextDependency,
    service: CostCenterServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_CENTER_UPDATE))],
) -> ApiResponse[CostCenterResponse]:
    row = await service.update(
        tenant.tenant_id, cost_center_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Cost center updated successfully")


@router.delete("/{cost_center_id}", response_model=ApiResponse[CostCenterResponse])
async def delete_cost_center(
    cost_center_id: UUID,
    tenant: TenantContextDependency,
    service: CostCenterServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(COST_CENTER_DELETE))],
) -> ApiResponse[CostCenterResponse]:
    row = await service.delete(tenant.tenant_id, cost_center_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Cost center deleted successfully")
