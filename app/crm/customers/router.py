"""Customer routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import CUSTOMER_CREATE, CUSTOMER_DELETE, CUSTOMER_READ, CUSTOMER_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.crm.customers.dependencies import CustomerServiceDependency
from app.crm.customers.schemas import (
    CustomerCreate,
    CustomerExtraAddressCreate,
    CustomerExtraAddressResponse,
    CustomerFilter,
    CustomerResponse,
    CustomerUpdate,
)

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=ApiResponse[list[CustomerResponse]])
async def list_customers(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CustomerServiceDependency,
    filters: Annotated[CustomerFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_READ))],
) -> ApiResponse[list[CustomerResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        tax_treatment=filters.tax_treatment.value if filters.tax_treatment else None,
        currency_id=filters.currency_id,
        company_type=filters.company_type.value if filters.company_type else None,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[CustomerResponse], status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_CREATE))],
) -> ApiResponse[CustomerResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Customer created successfully")


@router.get("/{customer_id}", response_model=ApiResponse[CustomerResponse])
async def get_customer(
    customer_id: UUID,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_READ))],
) -> ApiResponse[CustomerResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, customer_id))


@router.patch("/{customer_id}", response_model=ApiResponse[CustomerResponse])
async def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_UPDATE))],
) -> ApiResponse[CustomerResponse]:
    row = await service.update(tenant.tenant_id, customer_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Customer updated successfully")


@router.delete("/{customer_id}", response_model=ApiResponse[CustomerResponse])
async def delete_customer(
    customer_id: UUID,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_DELETE))],
) -> ApiResponse[CustomerResponse]:
    row = await service.delete(tenant.tenant_id, customer_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Customer deleted successfully")


@router.post(
    "/{customer_id}/addresses",
    response_model=ApiResponse[CustomerExtraAddressResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_customer_address(
    customer_id: UUID,
    payload: CustomerExtraAddressCreate,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_UPDATE))],
) -> ApiResponse[CustomerExtraAddressResponse]:
    row = await service.add_extra_address(
        tenant.tenant_id, customer_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Customer address added successfully")


@router.delete(
    "/{customer_id}/addresses/{extra_id}",
    response_model=ApiResponse[CustomerExtraAddressResponse],
)
async def delete_customer_address(
    customer_id: UUID,
    extra_id: UUID,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_UPDATE))],
) -> ApiResponse[CustomerExtraAddressResponse]:
    row = await service.delete_extra_address(
        tenant.tenant_id, customer_id, extra_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Customer address deleted successfully")
