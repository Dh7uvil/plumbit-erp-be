"""Supplier routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import SUPPLIER_CREATE, SUPPLIER_DELETE, SUPPLIER_READ, SUPPLIER_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.erp.suppliers.dependencies import SupplierServiceDependency
from app.erp.suppliers.schemas import (
    SupplierCreate,
    SupplierExtraAddressCreate,
    SupplierExtraAddressResponse,
    SupplierFilter,
    SupplierResponse,
    SupplierUpdate,
)

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


@router.get("", response_model=ApiResponse[list[SupplierResponse]])
async def list_suppliers(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: SupplierServiceDependency,
    filters: Annotated[SupplierFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_READ))],
) -> ApiResponse[list[SupplierResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        tax_treatment=filters.tax_treatment.value if filters.tax_treatment else None,
        currency_id=filters.currency_id,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[SupplierResponse], status_code=status.HTTP_201_CREATED)
async def create_supplier(
    payload: SupplierCreate,
    tenant: TenantContextDependency,
    service: SupplierServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_CREATE))],
) -> ApiResponse[SupplierResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Supplier created successfully")


@router.get("/{supplier_id}", response_model=ApiResponse[SupplierResponse])
async def get_supplier(
    supplier_id: UUID,
    tenant: TenantContextDependency,
    service: SupplierServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_READ))],
) -> ApiResponse[SupplierResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, supplier_id))


@router.patch("/{supplier_id}", response_model=ApiResponse[SupplierResponse])
async def update_supplier(
    supplier_id: UUID,
    payload: SupplierUpdate,
    tenant: TenantContextDependency,
    service: SupplierServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_UPDATE))],
) -> ApiResponse[SupplierResponse]:
    row = await service.update(tenant.tenant_id, supplier_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Supplier updated successfully")


@router.delete("/{supplier_id}", response_model=ApiResponse[SupplierResponse])
async def delete_supplier(
    supplier_id: UUID,
    tenant: TenantContextDependency,
    service: SupplierServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_DELETE))],
) -> ApiResponse[SupplierResponse]:
    row = await service.delete(tenant.tenant_id, supplier_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Supplier deleted successfully")


@router.post(
    "/{supplier_id}/addresses",
    response_model=ApiResponse[SupplierExtraAddressResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_supplier_address(
    supplier_id: UUID,
    payload: SupplierExtraAddressCreate,
    tenant: TenantContextDependency,
    service: SupplierServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_UPDATE))],
) -> ApiResponse[SupplierExtraAddressResponse]:
    row = await service.add_extra_address(
        tenant.tenant_id, supplier_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Supplier address added successfully")


@router.delete(
    "/{supplier_id}/addresses/{extra_id}",
    response_model=ApiResponse[SupplierExtraAddressResponse],
)
async def delete_supplier_address(
    supplier_id: UUID,
    extra_id: UUID,
    tenant: TenantContextDependency,
    service: SupplierServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_UPDATE))],
) -> ApiResponse[SupplierExtraAddressResponse]:
    row = await service.delete_extra_address(
        tenant.tenant_id, supplier_id, extra_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Supplier address deleted successfully")
