"""Charge type routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    CHARGE_TYPE_CREATE,
    CHARGE_TYPE_DELETE,
    CHARGE_TYPE_READ,
    CHARGE_TYPE_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.erp.accounting.charge_types.dependencies import ChargeTypeServiceDependency
from app.erp.accounting.charge_types.schemas import (
    ChargeTypeCreate,
    ChargeTypeFilter,
    ChargeTypeResponse,
    ChargeTypeUpdate,
)

router = APIRouter(prefix="/charge-types", tags=["Charge Types"])


@router.get("", response_model=ApiResponse[list[ChargeTypeResponse]])
async def list_charge_types(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: ChargeTypeServiceDependency,
    filters: Annotated[ChargeTypeFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CHARGE_TYPE_READ))],
) -> ApiResponse[list[ChargeTypeResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
        applies_to=filters.applies_to.value if filters.applies_to else None,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[ChargeTypeResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_charge_type(
    payload: ChargeTypeCreate,
    tenant: TenantContextDependency,
    service: ChargeTypeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHARGE_TYPE_CREATE))],
) -> ApiResponse[ChargeTypeResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Charge type created successfully")


@router.get("/{charge_type_id}", response_model=ApiResponse[ChargeTypeResponse])
async def get_charge_type(
    charge_type_id: UUID,
    tenant: TenantContextDependency,
    service: ChargeTypeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHARGE_TYPE_READ))],
) -> ApiResponse[ChargeTypeResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, charge_type_id))


@router.patch("/{charge_type_id}", response_model=ApiResponse[ChargeTypeResponse])
async def update_charge_type(
    charge_type_id: UUID,
    payload: ChargeTypeUpdate,
    tenant: TenantContextDependency,
    service: ChargeTypeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHARGE_TYPE_UPDATE))],
) -> ApiResponse[ChargeTypeResponse]:
    row = await service.update(
        tenant.tenant_id, charge_type_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Charge type updated successfully")


@router.delete("/{charge_type_id}", response_model=ApiResponse[ChargeTypeResponse])
async def delete_charge_type(
    charge_type_id: UUID,
    tenant: TenantContextDependency,
    service: ChargeTypeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHARGE_TYPE_DELETE))],
) -> ApiResponse[ChargeTypeResponse]:
    row = await service.delete(tenant.tenant_id, charge_type_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Charge type deleted successfully")
