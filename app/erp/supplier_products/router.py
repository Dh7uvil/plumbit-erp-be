"""Supplier product catalog routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.auth.catalog import (
    SUPPLIER_PRODUCT_CREATE,
    SUPPLIER_PRODUCT_DELETE,
    SUPPLIER_PRODUCT_LINK,
    SUPPLIER_PRODUCT_READ,
    SUPPLIER_PRODUCT_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.erp.supplier_products.dependencies import SupplierProductServiceDependency
from app.erp.supplier_products.schemas import (
    SupplierProductCreate,
    SupplierProductFilter,
    SupplierProductLinkRequest,
    SupplierProductResolveBatchRequest,
    SupplierProductResolveResponse,
    SupplierProductResponse,
    SupplierProductUpdate,
)

router = APIRouter(prefix="/supplier-products", tags=["Supplier Products"])


@router.get("", response_model=ApiResponse[list[SupplierProductResponse]])
async def list_supplier_products(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: SupplierProductServiceDependency,
    filters: Annotated[SupplierProductFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_PRODUCT_READ))],
) -> ApiResponse[list[SupplierProductResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        supplier_id=filters.supplier_id,
        product_id=filters.product_id,
        mapped=filters.mapped,
        is_active=filters.is_active,
        is_preferred=filters.is_preferred,
        is_preferred_supplier=filters.is_preferred_supplier,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[SupplierProductResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_supplier_product(
    payload: SupplierProductCreate,
    tenant: TenantContextDependency,
    service: SupplierProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_PRODUCT_CREATE))],
) -> ApiResponse[SupplierProductResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Supplier product created successfully")


@router.get("/resolve", response_model=ApiResponse[SupplierProductResolveResponse])
async def resolve_supplier_sku(
    tenant: TenantContextDependency,
    service: SupplierProductServiceDependency,
    supplier_id: Annotated[UUID, Query()],
    supplier_sku: Annotated[str, Query(min_length=1, max_length=80)],
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_PRODUCT_READ))],
) -> ApiResponse[SupplierProductResolveResponse]:
    return ApiResponse(
        data=await service.resolve(
            tenant.tenant_id, supplier_id=supplier_id, supplier_sku=supplier_sku
        )
    )


@router.post("/resolve", response_model=ApiResponse[list[SupplierProductResolveResponse]])
async def resolve_supplier_skus(
    payload: SupplierProductResolveBatchRequest,
    tenant: TenantContextDependency,
    service: SupplierProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_PRODUCT_READ))],
) -> ApiResponse[list[SupplierProductResolveResponse]]:
    rows = await service.resolve_batch(
        tenant.tenant_id,
        supplier_id=payload.supplier_id,
        supplier_skus=payload.supplier_skus,
    )
    return ApiResponse(data=rows)


@router.get("/{supplier_product_id}", response_model=ApiResponse[SupplierProductResponse])
async def get_supplier_product(
    supplier_product_id: UUID,
    tenant: TenantContextDependency,
    service: SupplierProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_PRODUCT_READ))],
) -> ApiResponse[SupplierProductResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, supplier_product_id))


@router.patch("/{supplier_product_id}", response_model=ApiResponse[SupplierProductResponse])
async def update_supplier_product(
    supplier_product_id: UUID,
    payload: SupplierProductUpdate,
    tenant: TenantContextDependency,
    service: SupplierProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_PRODUCT_UPDATE))],
) -> ApiResponse[SupplierProductResponse]:
    row = await service.update(
        tenant.tenant_id, supplier_product_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Supplier product updated successfully")


@router.delete("/{supplier_product_id}", response_model=ApiResponse[SupplierProductResponse])
async def delete_supplier_product(
    supplier_product_id: UUID,
    tenant: TenantContextDependency,
    service: SupplierProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_PRODUCT_DELETE))],
) -> ApiResponse[SupplierProductResponse]:
    row = await service.delete(tenant.tenant_id, supplier_product_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Supplier product deleted successfully")


@router.post(
    "/{supplier_product_id}/link",
    response_model=ApiResponse[SupplierProductResponse],
)
async def link_supplier_product(
    supplier_product_id: UUID,
    payload: SupplierProductLinkRequest,
    tenant: TenantContextDependency,
    service: SupplierProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_PRODUCT_LINK))],
) -> ApiResponse[SupplierProductResponse]:
    row = await service.link(
        tenant.tenant_id,
        supplier_product_id,
        payload.product_id,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Supplier product linked successfully")


@router.post(
    "/{supplier_product_id}/unlink",
    response_model=ApiResponse[SupplierProductResponse],
)
async def unlink_supplier_product(
    supplier_product_id: UUID,
    tenant: TenantContextDependency,
    service: SupplierProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_PRODUCT_LINK))],
) -> ApiResponse[SupplierProductResponse]:
    row = await service.unlink(tenant.tenant_id, supplier_product_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Supplier product unlinked successfully")
