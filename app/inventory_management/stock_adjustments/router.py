"""Stock adjustment routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    STOCK_ADJUSTMENT_CREATE,
    STOCK_ADJUSTMENT_DELETE,
    STOCK_ADJUSTMENT_POST,
    STOCK_ADJUSTMENT_READ,
    STOCK_ADJUSTMENT_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.inventory_management.stock_adjustments.dependencies import (
    StockAdjustmentServiceDependency,
)
from app.inventory_management.stock_adjustments.schemas import (
    StockAdjustmentCancelRequest,
    StockAdjustmentCreate,
    StockAdjustmentFilter,
    StockAdjustmentResponse,
    StockAdjustmentUpdate,
)

router = APIRouter(prefix="/stock-adjustments", tags=["Stock Adjustments"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[StockAdjustmentResponse]])
async def list_stock_adjustments(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: StockAdjustmentServiceDependency,
    filters: Annotated[StockAdjustmentFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_ADJUSTMENT_READ))],
) -> ApiResponse[list[StockAdjustmentResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        warehouse_id=filters.warehouse_id,
        reason=filters.reason.value if filters.reason else None,
        branch_id=filters.branch_id,
        product_id=filters.product_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[StockAdjustmentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_stock_adjustment(
    payload: StockAdjustmentCreate,
    tenant: TenantContextDependency,
    service: StockAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_ADJUSTMENT_CREATE))],
) -> ApiResponse[StockAdjustmentResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Stock adjustment created successfully")


@router.get("/{adjustment_id}", response_model=ApiResponse[StockAdjustmentResponse])
async def get_stock_adjustment(
    adjustment_id: UUID,
    tenant: TenantContextDependency,
    service: StockAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_ADJUSTMENT_READ))],
) -> ApiResponse[StockAdjustmentResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, adjustment_id))


@router.patch("/{adjustment_id}", response_model=ApiResponse[StockAdjustmentResponse])
async def update_stock_adjustment(
    adjustment_id: UUID,
    payload: StockAdjustmentUpdate,
    tenant: TenantContextDependency,
    service: StockAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_ADJUSTMENT_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[StockAdjustmentResponse]:
    row = await service.update(
        tenant.tenant_id,
        adjustment_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Stock adjustment updated successfully")


@router.delete("/{adjustment_id}", response_model=ApiResponse[StockAdjustmentResponse])
async def delete_stock_adjustment(
    adjustment_id: UUID,
    tenant: TenantContextDependency,
    service: StockAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_ADJUSTMENT_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[StockAdjustmentResponse]:
    row = await service.delete(
        tenant.tenant_id,
        adjustment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Stock adjustment deleted successfully")


@router.post("/{adjustment_id}/post", response_model=ApiResponse[StockAdjustmentResponse])
async def post_stock_adjustment(
    adjustment_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: StockAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_ADJUSTMENT_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[StockAdjustmentResponse]:
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        adjustment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Stock adjustment posted successfully")


@router.post("/{adjustment_id}/cancel", response_model=ApiResponse[StockAdjustmentResponse])
async def cancel_stock_adjustment(
    adjustment_id: UUID,
    tenant: TenantContextDependency,
    service: StockAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_ADJUSTMENT_UPDATE))],
    if_match: IfMatch = None,
    payload: Annotated[StockAdjustmentCancelRequest | None, Body()] = None,
) -> ApiResponse[StockAdjustmentResponse]:
    body = payload or StockAdjustmentCancelRequest()
    row = await service.cancel(
        tenant.tenant_id,
        adjustment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        reason=body.reason,
    )
    return ApiResponse(data=row, message="Stock adjustment cancelled")


@router.post("/{adjustment_id}/clone", response_model=ApiResponse[StockAdjustmentResponse])
async def clone_stock_adjustment(
    adjustment_id: UUID,
    tenant: TenantContextDependency,
    service: StockAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_ADJUSTMENT_CREATE))],
) -> ApiResponse[StockAdjustmentResponse]:
    row = await service.clone(tenant.tenant_id, adjustment_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Stock adjustment cloned as a new draft")
