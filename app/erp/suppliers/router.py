"""Supplier routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.auth.catalog import (
    SUPPLIER_CREATE,
    SUPPLIER_DELETE,
    SUPPLIER_HISTORY,
    SUPPLIER_READ,
    SUPPLIER_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.erp.accounting.open_items.dependencies import OpenItemsServiceDependency
from app.erp.accounting.open_items.schemas import OpenItemRow
from app.erp.accounting.reports.dependencies import ReportServiceDependency
from app.erp.accounting.reports.schemas import OutstandingSummary
from app.erp.suppliers.dependencies import SupplierServiceDependency
from app.erp.suppliers.schemas import (
    SupplierCreate,
    SupplierExtraAddressCreate,
    SupplierExtraAddressResponse,
    SupplierFilter,
    SupplierResponse,
    SupplierUpdate,
)
from app.inventory_management.history.dependencies import HistoryServiceDependency
from app.inventory_management.history.schemas import TradingHistoryFilter, TradingHistoryLine

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


@router.get(
    "/{supplier_id}/purchase-history",
    response_model=ApiResponse[list[TradingHistoryLine]],
)
async def list_supplier_purchase_history(
    supplier_id: UUID,
    tenant: TenantContextDependency,
    page: PaginationDependency,
    history: HistoryServiceDependency,
    filters: Annotated[TradingHistoryFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_HISTORY))],
) -> ApiResponse[list[TradingHistoryLine]]:
    rows, total = await history.supplier_purchase_history(
        tenant.tenant_id,
        supplier_id,
        page=page,
        product_id=filters.product_id,
        warehouse_id=filters.warehouse_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.get("/{supplier_id}/open-items", response_model=ApiResponse[list[OpenItemRow]])
async def list_supplier_open_items(
    supplier_id: UUID,
    tenant: TenantContextDependency,
    service: SupplierServiceDependency,
    open_items: OpenItemsServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_READ))],
) -> ApiResponse[list[OpenItemRow]]:
    await service.get(tenant.tenant_id, supplier_id)
    rows = await open_items.list_ap_open_items(tenant.tenant_id, supplier_id)
    return ApiResponse(data=rows)


@router.get("/{supplier_id}/outstanding-summary", response_model=ApiResponse[OutstandingSummary])
async def get_supplier_outstanding_summary(
    supplier_id: UUID,
    tenant: TenantContextDependency,
    reports: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_READ))],
    as_of: Annotated[date | None, Query()] = None,
) -> ApiResponse[OutstandingSummary]:
    return ApiResponse(
        data=await reports.supplier_outstanding(tenant.tenant_id, supplier_id, as_of=as_of)
    )
