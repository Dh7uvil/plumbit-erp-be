"""Stock transfer routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    STOCK_TRANSFER_CREATE,
    STOCK_TRANSFER_DELETE,
    STOCK_TRANSFER_POST,
    STOCK_TRANSFER_READ,
    STOCK_TRANSFER_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.inventory_management.stock_transfers.dependencies import StockTransferServiceDependency
from app.inventory_management.stock_transfers.schemas import (
    StockTransferCancelRequest,
    StockTransferCreate,
    StockTransferFilter,
    StockTransferResponse,
    StockTransferUpdate,
)

router = APIRouter(prefix="/stock-transfers", tags=["Stock Transfers"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[StockTransferResponse]])
async def list_stock_transfers(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: StockTransferServiceDependency,
    filters: Annotated[StockTransferFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_TRANSFER_READ))],
) -> ApiResponse[list[StockTransferResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        from_warehouse_id=filters.from_warehouse_id,
        to_warehouse_id=filters.to_warehouse_id,
        branch_id=filters.branch_id,
        product_id=filters.product_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[StockTransferResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_stock_transfer(
    payload: StockTransferCreate,
    tenant: TenantContextDependency,
    service: StockTransferServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_TRANSFER_CREATE))],
) -> ApiResponse[StockTransferResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Stock transfer created successfully")


@router.get("/{transfer_id}", response_model=ApiResponse[StockTransferResponse])
async def get_stock_transfer(
    transfer_id: UUID,
    tenant: TenantContextDependency,
    service: StockTransferServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_TRANSFER_READ))],
) -> ApiResponse[StockTransferResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, transfer_id))


@router.patch("/{transfer_id}", response_model=ApiResponse[StockTransferResponse])
async def update_stock_transfer(
    transfer_id: UUID,
    payload: StockTransferUpdate,
    tenant: TenantContextDependency,
    service: StockTransferServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_TRANSFER_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[StockTransferResponse]:
    row = await service.update(
        tenant.tenant_id,
        transfer_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Stock transfer updated successfully")


@router.delete("/{transfer_id}", response_model=ApiResponse[StockTransferResponse])
async def delete_stock_transfer(
    transfer_id: UUID,
    tenant: TenantContextDependency,
    service: StockTransferServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_TRANSFER_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[StockTransferResponse]:
    row = await service.delete(
        tenant.tenant_id,
        transfer_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Stock transfer deleted successfully")


@router.post("/{transfer_id}/post", response_model=ApiResponse[StockTransferResponse])
async def post_stock_transfer(
    transfer_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: StockTransferServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_TRANSFER_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[StockTransferResponse]:
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        transfer_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Stock transfer posted successfully")


@router.post("/{transfer_id}/cancel", response_model=ApiResponse[StockTransferResponse])
async def cancel_stock_transfer(
    transfer_id: UUID,
    tenant: TenantContextDependency,
    service: StockTransferServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_TRANSFER_UPDATE))],
    if_match: IfMatch = None,
    payload: Annotated[StockTransferCancelRequest | None, Body()] = None,
) -> ApiResponse[StockTransferResponse]:
    body = payload or StockTransferCancelRequest()
    row = await service.cancel(
        tenant.tenant_id,
        transfer_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        reason=body.reason,
    )
    return ApiResponse(data=row, message="Stock transfer cancelled")


@router.post("/{transfer_id}/clone", response_model=ApiResponse[StockTransferResponse])
async def clone_stock_transfer(
    transfer_id: UUID,
    tenant: TenantContextDependency,
    service: StockTransferServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(STOCK_TRANSFER_CREATE))],
) -> ApiResponse[StockTransferResponse]:
    row = await service.clone(tenant.tenant_id, transfer_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Stock transfer cloned as a new draft")
