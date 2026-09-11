"""Package routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile, status

from app.auth.catalog import (
    PACKAGE_CREATE,
    PACKAGE_DELETE,
    PACKAGE_EXPORT,
    PACKAGE_IMPORT,
    PACKAGE_READ,
    PACKAGE_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import require_idempotency_key
from app.common.imex.commercial import COMMERCIAL_EXPORT_HEADERS
from app.common.imex.http import parse_mapping_json, read_upload
from app.common.imex.schemas import ImportPreviewResponse, ImportResult
from app.common.imex.service import export_response, preview_file, template_response
from app.common.print.schemas import PrintDocumentResponse
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
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


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


@router.get("/import/template")
async def package_import_template(
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_IMPORT))],
):
    return template_response("package")


@router.post("/import/preview", response_model=ApiResponse[ImportPreviewResponse])
async def package_import_preview(
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_IMPORT))],
    file: Annotated[UploadFile, File()],
) -> ApiResponse[ImportPreviewResponse]:
    filename, content = await read_upload(file)
    return ApiResponse(data=preview_file("package", filename=filename, content=content))


@router.post(
    "/import",
    response_model=ApiResponse[ImportResult],
    status_code=status.HTTP_201_CREATED,
)
async def package_import(
    tenant: TenantContextDependency,
    service: PackageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_IMPORT))],
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str | None, Form()] = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[ImportResult]:
    require_idempotency_key(idempotency_key)
    filename, content = await read_upload(file)
    result = await service.import_drafts(
        tenant.tenant_id,
        filename=filename,
        content=content,
        mapping=parse_mapping_json(mapping),
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=result, message="Package drafts imported")


@router.get("/export")
async def package_export(
    tenant: TenantContextDependency,
    service: PackageServiceDependency,
    filters: Annotated[PackageFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_EXPORT))],
):
    rows = await service.export_rows(
        tenant.tenant_id,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        sales_order_id=filters.sales_order_id,
        delivery_note_id=filters.delivery_note_id,
    )
    return export_response("package", COMMERCIAL_EXPORT_HEADERS, rows)


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


@router.get("/{package_id}/print", response_model=ApiResponse[PrintDocumentResponse])
async def print_package(
    package_id: UUID,
    tenant: TenantContextDependency,
    service: PackageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PACKAGE_READ))],
    template_family: Annotated[str, Query()] = "china",
) -> ApiResponse[PrintDocumentResponse]:
    return ApiResponse(
        data=await service.print_document(
            tenant.tenant_id, package_id, template_family=template_family
        )
    )


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
