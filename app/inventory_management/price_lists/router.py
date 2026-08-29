"""Price-list routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    PRICE_LIST_CREATE,
    PRICE_LIST_DELETE,
    PRICE_LIST_READ,
    PRICE_LIST_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.inventory_management.price_lists.dependencies import PriceListServiceDependency
from app.inventory_management.price_lists.schemas import (
    PriceListCreate,
    PriceListFilter,
    PriceListItemResponse,
    PriceListItemUpsert,
    PriceListResponse,
    PriceListUpdate,
)

router = APIRouter(prefix="/price-lists", tags=["Price Lists"])


@router.get("", response_model=ApiResponse[list[PriceListResponse]])
async def list_price_lists(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: PriceListServiceDependency,
    filters: Annotated[PriceListFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PRICE_LIST_READ))],
) -> ApiResponse[list[PriceListResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        currency_id=filters.currency_id,
        list_type=filters.list_type.value if filters.list_type else None,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[PriceListResponse], status_code=status.HTTP_201_CREATED)
async def create_price_list(
    payload: PriceListCreate,
    tenant: TenantContextDependency,
    service: PriceListServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRICE_LIST_CREATE))],
) -> ApiResponse[PriceListResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Price list created successfully")


@router.get("/{price_list_id}", response_model=ApiResponse[PriceListResponse])
async def get_price_list(
    price_list_id: UUID,
    tenant: TenantContextDependency,
    service: PriceListServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRICE_LIST_READ))],
) -> ApiResponse[PriceListResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, price_list_id))


@router.patch("/{price_list_id}", response_model=ApiResponse[PriceListResponse])
async def update_price_list(
    price_list_id: UUID,
    payload: PriceListUpdate,
    tenant: TenantContextDependency,
    service: PriceListServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRICE_LIST_UPDATE))],
) -> ApiResponse[PriceListResponse]:
    row = await service.update(
        tenant.tenant_id, price_list_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Price list updated successfully")


@router.delete("/{price_list_id}", response_model=ApiResponse[PriceListResponse])
async def delete_price_list(
    price_list_id: UUID,
    tenant: TenantContextDependency,
    service: PriceListServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRICE_LIST_DELETE))],
) -> ApiResponse[PriceListResponse]:
    row = await service.delete(tenant.tenant_id, price_list_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Price list deleted successfully")


@router.put(
    "/{price_list_id}/items",
    response_model=ApiResponse[PriceListItemResponse],
)
async def upsert_price_list_item(
    price_list_id: UUID,
    payload: PriceListItemUpsert,
    tenant: TenantContextDependency,
    service: PriceListServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRICE_LIST_UPDATE))],
) -> ApiResponse[PriceListItemResponse]:
    row = await service.upsert_item(
        tenant.tenant_id, price_list_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Price list item saved successfully")


@router.delete(
    "/{price_list_id}/items/{product_id}",
    response_model=ApiResponse[PriceListItemResponse],
)
async def delete_price_list_item(
    price_list_id: UUID,
    product_id: UUID,
    tenant: TenantContextDependency,
    service: PriceListServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRICE_LIST_UPDATE))],
) -> ApiResponse[PriceListItemResponse]:
    row = await service.delete_item(
        tenant.tenant_id, price_list_id, product_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Price list item deleted successfully")
