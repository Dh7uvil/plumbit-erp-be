"""Unit of measure routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import UNIT_CREATE, UNIT_DELETE, UNIT_READ, UNIT_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.inventory_management.units.dependencies import UnitServiceDependency
from app.inventory_management.units.schemas import UnitCreate, UnitFilter, UnitResponse, UnitUpdate

router = APIRouter(prefix="/units", tags=["Units"])


@router.get("", response_model=ApiResponse[list[UnitResponse]])
async def list_units(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: UnitServiceDependency,
    filters: Annotated[UnitFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(UNIT_READ))],
) -> ApiResponse[list[UnitResponse]]:
    rows, total = await service.list(
        tenant.tenant_id, page=page, common_filter=filters, is_active=filters.is_active
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[UnitResponse], status_code=status.HTTP_201_CREATED)
async def create_unit(
    payload: UnitCreate,
    tenant: TenantContextDependency,
    service: UnitServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(UNIT_CREATE))],
) -> ApiResponse[UnitResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Unit created successfully")


@router.get("/{unit_id}", response_model=ApiResponse[UnitResponse])
async def get_unit(
    unit_id: UUID,
    tenant: TenantContextDependency,
    service: UnitServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(UNIT_READ))],
) -> ApiResponse[UnitResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, unit_id))


@router.patch("/{unit_id}", response_model=ApiResponse[UnitResponse])
async def update_unit(
    unit_id: UUID,
    payload: UnitUpdate,
    tenant: TenantContextDependency,
    service: UnitServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(UNIT_UPDATE))],
) -> ApiResponse[UnitResponse]:
    row = await service.update(tenant.tenant_id, unit_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Unit updated successfully")


@router.delete("/{unit_id}", response_model=ApiResponse[UnitResponse])
async def delete_unit(
    unit_id: UUID,
    tenant: TenantContextDependency,
    service: UnitServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(UNIT_DELETE))],
) -> ApiResponse[UnitResponse]:
    row = await service.delete(tenant.tenant_id, unit_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Unit deleted successfully")
