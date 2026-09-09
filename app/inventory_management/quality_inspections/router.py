"""Quality inspection routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    QUALITY_INSPECTION_APPROVE,
    QUALITY_INSPECTION_CREATE,
    QUALITY_INSPECTION_READ,
    QUALITY_INSPECTION_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.inventory_management.quality_inspections.dependencies import (
    QualityInspectionServiceDependency,
)
from app.inventory_management.quality_inspections.schemas import (
    QualityInspectionCancelRequest,
    QualityInspectionCreate,
    QualityInspectionFilter,
    QualityInspectionResponse,
    QualityInspectionUpdate,
)

router = APIRouter(prefix="/quality-inspections", tags=["Quality Inspections"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[QualityInspectionResponse]])
async def list_quality_inspections(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: QualityInspectionServiceDependency,
    filters: Annotated[QualityInspectionFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(QUALITY_INSPECTION_READ))],
) -> ApiResponse[list[QualityInspectionResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        goods_receipt_id=filters.goods_receipt_id,
        inspection_date_from=filters.inspection_date_from,
        inspection_date_to=filters.inspection_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[QualityInspectionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_quality_inspection(
    payload: QualityInspectionCreate,
    tenant: TenantContextDependency,
    service: QualityInspectionServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUALITY_INSPECTION_CREATE))],
) -> ApiResponse[QualityInspectionResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Quality inspection created successfully")


@router.get("/{inspection_id}", response_model=ApiResponse[QualityInspectionResponse])
async def get_quality_inspection(
    inspection_id: UUID,
    tenant: TenantContextDependency,
    service: QualityInspectionServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUALITY_INSPECTION_READ))],
) -> ApiResponse[QualityInspectionResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, inspection_id))


@router.patch("/{inspection_id}", response_model=ApiResponse[QualityInspectionResponse])
async def update_quality_inspection(
    inspection_id: UUID,
    payload: QualityInspectionUpdate,
    tenant: TenantContextDependency,
    service: QualityInspectionServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUALITY_INSPECTION_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[QualityInspectionResponse]:
    row = await service.update(
        tenant.tenant_id,
        inspection_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Quality inspection updated successfully")


@router.delete("/{inspection_id}", response_model=ApiResponse[QualityInspectionResponse])
async def delete_quality_inspection(
    inspection_id: UUID,
    tenant: TenantContextDependency,
    service: QualityInspectionServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUALITY_INSPECTION_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[QualityInspectionResponse]:
    row = await service.delete(
        tenant.tenant_id,
        inspection_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Quality inspection deleted successfully")


@router.post("/{inspection_id}/approve", response_model=ApiResponse[QualityInspectionResponse])
async def approve_quality_inspection(
    inspection_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: QualityInspectionServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUALITY_INSPECTION_APPROVE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[QualityInspectionResponse]:
    body = await request.body()
    row = await service.approve(
        tenant.tenant_id,
        inspection_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Quality inspection approved")


@router.post("/{inspection_id}/cancel", response_model=ApiResponse[QualityInspectionResponse])
async def cancel_quality_inspection(
    inspection_id: UUID,
    tenant: TenantContextDependency,
    service: QualityInspectionServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUALITY_INSPECTION_UPDATE))],
    if_match: IfMatch = None,
    payload: Annotated[QualityInspectionCancelRequest | None, Body()] = None,
) -> ApiResponse[QualityInspectionResponse]:
    body = payload or QualityInspectionCancelRequest()
    row = await service.cancel(
        tenant.tenant_id,
        inspection_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        reason=body.reason,
    )
    return ApiResponse(data=row, message="Quality inspection cancelled")
