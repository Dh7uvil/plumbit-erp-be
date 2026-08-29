"""Warehouse routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    WAREHOUSE_CREATE,
    WAREHOUSE_DELETE,
    WAREHOUSE_READ,
    WAREHOUSE_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.inventory_management.warehouses.dependencies import WarehouseServiceDependency
from app.inventory_management.warehouses.schemas import (
    WarehouseCreate,
    WarehouseFilter,
    WarehouseResponse,
    WarehouseUpdate,
)

router = APIRouter(prefix="/warehouses", tags=["Warehouses"])


@router.get("", response_model=ApiResponse[list[WarehouseResponse]])
async def list_warehouses(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: WarehouseServiceDependency,
    filters: Annotated[WarehouseFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(WAREHOUSE_READ))],
) -> ApiResponse[list[WarehouseResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
        is_default=filters.is_default,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[WarehouseResponse], status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    payload: WarehouseCreate,
    tenant: TenantContextDependency,
    service: WarehouseServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(WAREHOUSE_CREATE))],
) -> ApiResponse[WarehouseResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Warehouse created successfully")


@router.get("/{warehouse_id}", response_model=ApiResponse[WarehouseResponse])
async def get_warehouse(
    warehouse_id: UUID,
    tenant: TenantContextDependency,
    service: WarehouseServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(WAREHOUSE_READ))],
) -> ApiResponse[WarehouseResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, warehouse_id))


@router.patch("/{warehouse_id}", response_model=ApiResponse[WarehouseResponse])
async def update_warehouse(
    warehouse_id: UUID,
    payload: WarehouseUpdate,
    tenant: TenantContextDependency,
    service: WarehouseServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(WAREHOUSE_UPDATE))],
) -> ApiResponse[WarehouseResponse]:
    row = await service.update(
        tenant.tenant_id, warehouse_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Warehouse updated successfully")


@router.delete("/{warehouse_id}", response_model=ApiResponse[WarehouseResponse])
async def delete_warehouse(
    warehouse_id: UUID,
    tenant: TenantContextDependency,
    service: WarehouseServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(WAREHOUSE_DELETE))],
) -> ApiResponse[WarehouseResponse]:
    row = await service.delete(tenant.tenant_id, warehouse_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Warehouse deleted successfully")
