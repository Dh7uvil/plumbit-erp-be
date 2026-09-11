"""Purchase return routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    PURCHASE_RETURN_CANCEL,
    PURCHASE_RETURN_CREATE,
    PURCHASE_RETURN_DELETE,
    PURCHASE_RETURN_POST,
    PURCHASE_RETURN_READ,
    PURCHASE_RETURN_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.inventory_management.purchase_returns.dependencies import PurchaseReturnServiceDependency
from app.inventory_management.purchase_returns.schemas import (
    PurchaseReturnCancelRequest,
    PurchaseReturnCreate,
    PurchaseReturnFilter,
    PurchaseReturnResponse,
    PurchaseReturnUpdate,
)

router = APIRouter(prefix="/purchase-returns", tags=["Purchase Returns"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[PurchaseReturnResponse]])
async def list_purchase_returns(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: PurchaseReturnServiceDependency,
    filters: Annotated[PurchaseReturnFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_RETURN_READ))],
) -> ApiResponse[list[PurchaseReturnResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        goods_receipt_id=filters.goods_receipt_id,
        purchase_order_id=filters.purchase_order_id,
        supplier_id=filters.supplier_id,
        warehouse_id=filters.warehouse_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[PurchaseReturnResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_purchase_return(
    payload: PurchaseReturnCreate,
    tenant: TenantContextDependency,
    service: PurchaseReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_RETURN_CREATE))],
) -> ApiResponse[PurchaseReturnResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Purchase return created successfully")


@router.get("/{return_id}", response_model=ApiResponse[PurchaseReturnResponse])
async def get_purchase_return(
    return_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_RETURN_READ))],
) -> ApiResponse[PurchaseReturnResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, return_id))


@router.patch("/{return_id}", response_model=ApiResponse[PurchaseReturnResponse])
async def update_purchase_return(
    return_id: UUID,
    payload: PurchaseReturnUpdate,
    tenant: TenantContextDependency,
    service: PurchaseReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_RETURN_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseReturnResponse]:
    row = await service.update(
        tenant.tenant_id,
        return_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Purchase return updated successfully")


@router.delete("/{return_id}", response_model=ApiResponse[PurchaseReturnResponse])
async def delete_purchase_return(
    return_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_RETURN_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseReturnResponse]:
    row = await service.delete(
        tenant.tenant_id,
        return_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Purchase return deleted successfully")


@router.post("/{return_id}/post", response_model=ApiResponse[PurchaseReturnResponse])
async def post_purchase_return(
    return_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: PurchaseReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_RETURN_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[PurchaseReturnResponse]:
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        return_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Purchase return posted successfully")


@router.post("/{return_id}/cancel", response_model=ApiResponse[PurchaseReturnResponse])
async def cancel_purchase_return(
    return_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_RETURN_CANCEL))],
    if_match: IfMatch = None,
    payload: Annotated[PurchaseReturnCancelRequest | None, Body()] = None,
) -> ApiResponse[PurchaseReturnResponse]:
    body_payload = payload or PurchaseReturnCancelRequest()
    row = await service.cancel(
        tenant.tenant_id,
        return_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=body_payload.version
        ),
        reason=body_payload.reason,
    )
    return ApiResponse(data=row, message="Purchase return cancelled")
