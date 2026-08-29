"""Product routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import PRODUCT_CREATE, PRODUCT_DELETE, PRODUCT_READ, PRODUCT_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.inventory_management.products.dependencies import ProductServiceDependency
from app.inventory_management.products.schemas import (
    ProductCreate,
    ProductFilter,
    ProductResponse,
    ProductUpdate,
)

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("", response_model=ApiResponse[list[ProductResponse]])
async def list_products(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: ProductServiceDependency,
    filters: Annotated[ProductFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_READ))],
) -> ApiResponse[list[ProductResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        item_type=filters.item_type.value if filters.item_type else None,
        category_id=filters.category_id,
        unit_id=filters.unit_id,
        tax_id=filters.tax_id,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[ProductResponse], status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    tenant: TenantContextDependency,
    service: ProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_CREATE))],
) -> ApiResponse[ProductResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Product created successfully")


@router.get("/{product_id}", response_model=ApiResponse[ProductResponse])
async def get_product(
    product_id: UUID,
    tenant: TenantContextDependency,
    service: ProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_READ))],
) -> ApiResponse[ProductResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, product_id))


@router.patch("/{product_id}", response_model=ApiResponse[ProductResponse])
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    tenant: TenantContextDependency,
    service: ProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_UPDATE))],
) -> ApiResponse[ProductResponse]:
    row = await service.update(tenant.tenant_id, product_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Product updated successfully")


@router.delete("/{product_id}", response_model=ApiResponse[ProductResponse])
async def delete_product(
    product_id: UUID,
    tenant: TenantContextDependency,
    service: ProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_DELETE))],
) -> ApiResponse[ProductResponse]:
    row = await service.delete(tenant.tenant_id, product_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Product deleted successfully")
