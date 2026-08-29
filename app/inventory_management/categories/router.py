"""Category routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import CATEGORY_CREATE, CATEGORY_DELETE, CATEGORY_READ, CATEGORY_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.inventory_management.categories.dependencies import CategoryServiceDependency
from app.inventory_management.categories.schemas import (
    CategoryCreate,
    CategoryFilter,
    CategoryResponse,
    CategoryUpdate,
)

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.get("", response_model=ApiResponse[list[CategoryResponse]])
async def list_categories(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CategoryServiceDependency,
    filters: Annotated[CategoryFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CATEGORY_READ))],
) -> ApiResponse[list[CategoryResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        parent_id=filters.parent_id,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[CategoryResponse], status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    tenant: TenantContextDependency,
    service: CategoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CATEGORY_CREATE))],
) -> ApiResponse[CategoryResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Category created successfully")


@router.get("/{category_id}", response_model=ApiResponse[CategoryResponse])
async def get_category(
    category_id: UUID,
    tenant: TenantContextDependency,
    service: CategoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CATEGORY_READ))],
) -> ApiResponse[CategoryResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, category_id))


@router.patch("/{category_id}", response_model=ApiResponse[CategoryResponse])
async def update_category(
    category_id: UUID,
    payload: CategoryUpdate,
    tenant: TenantContextDependency,
    service: CategoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CATEGORY_UPDATE))],
) -> ApiResponse[CategoryResponse]:
    row = await service.update(tenant.tenant_id, category_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Category updated successfully")


@router.delete("/{category_id}", response_model=ApiResponse[CategoryResponse])
async def delete_category(
    category_id: UUID,
    tenant: TenantContextDependency,
    service: CategoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CATEGORY_DELETE))],
) -> ApiResponse[CategoryResponse]:
    row = await service.delete(tenant.tenant_id, category_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Category deleted successfully")
