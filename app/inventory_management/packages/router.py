"""Package routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from app.auth.catalog import PACKAGE_CREATE, PACKAGE_DELETE, PACKAGE_READ, PACKAGE_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.inventory_management.packages.dependencies import PackageServiceDependency
from app.inventory_management.packages.schemas import (
    PackageCreate,
    PackageFilter,
    PackageResponse,
    PackageUpdate,
)

router = APIRouter(prefix="/packages", tags=["Packages"])

IfMatch = Annotated[str | None, Header()]


@router.get("", response_model=ApiResponse[list[PackageResponse]])
async def list_packages(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: PackageServiceDependency,
    filters: Annotated[PackageFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_READ))],
) -> ApiResponse[list[PackageResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        sales_order_id=filters.sales_order_id,
        delivery_note_id=filters.delivery_note_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[PackageResponse], status_code=status.HTTP_201_CREATED)
async def create_package(
    payload: PackageCreate,
    tenant: TenantContextDependency,
    service: PackageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_CREATE))],
) -> ApiResponse[PackageResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Package created successfully")


@router.get("/{package_id}", response_model=ApiResponse[PackageResponse])
async def get_package(
    package_id: UUID,
    tenant: TenantContextDependency,
    service: PackageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_READ))],
) -> ApiResponse[PackageResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, package_id))


@router.patch("/{package_id}", response_model=ApiResponse[PackageResponse])
async def update_package(
    package_id: UUID,
    payload: PackageUpdate,
    tenant: TenantContextDependency,
    service: PackageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[PackageResponse]:
    row = await service.update(
        tenant.tenant_id,
        package_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Package updated successfully")


@router.delete("/{package_id}", response_model=ApiResponse[PackageResponse])
async def delete_package(
    package_id: UUID,
    tenant: TenantContextDependency,
    service: PackageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[PackageResponse]:
    row = await service.delete(
        tenant.tenant_id,
        package_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Package deleted successfully")


@router.post("/{package_id}/pack", response_model=ApiResponse[PackageResponse])
async def pack_package(
    package_id: UUID,
    tenant: TenantContextDependency,
    service: PackageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[PackageResponse]:
    row = await service.pack(
        tenant.tenant_id,
        package_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Package packed")


@router.post("/{package_id}/cancel", response_model=ApiResponse[PackageResponse])
async def cancel_package(
    package_id: UUID,
    tenant: TenantContextDependency,
    service: PackageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[PackageResponse]:
    row = await service.cancel(
        tenant.tenant_id,
        package_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Package cancelled")
