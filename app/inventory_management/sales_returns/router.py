"""Sales return routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    SALES_RETURN_CREATE,
    SALES_RETURN_DELETE,
    SALES_RETURN_POST,
    SALES_RETURN_READ,
    SALES_RETURN_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.inventory_management.sales_returns.dependencies import SalesReturnServiceDependency
from app.inventory_management.sales_returns.schemas import (
    SalesReturnCancelRequest,
    SalesReturnCreate,
    SalesReturnFilter,
    SalesReturnResponse,
    SalesReturnUpdate,
)

router = APIRouter(prefix="/sales-returns", tags=["Sales Returns"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[SalesReturnResponse]])
async def list_sales_returns(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: SalesReturnServiceDependency,
    filters: Annotated[SalesReturnFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(SALES_RETURN_READ))],
) -> ApiResponse[list[SalesReturnResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        delivery_note_id=filters.delivery_note_id,
        sales_order_id=filters.sales_order_id,
        customer_id=filters.customer_id,
        warehouse_id=filters.warehouse_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[SalesReturnResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_sales_return(
    payload: SalesReturnCreate,
    tenant: TenantContextDependency,
    service: SalesReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_RETURN_CREATE))],
) -> ApiResponse[SalesReturnResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Sales return created successfully")


@router.get("/{return_id}", response_model=ApiResponse[SalesReturnResponse])
async def get_sales_return(
    return_id: UUID,
    tenant: TenantContextDependency,
    service: SalesReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_RETURN_READ))],
) -> ApiResponse[SalesReturnResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, return_id))


@router.patch("/{return_id}", response_model=ApiResponse[SalesReturnResponse])
async def update_sales_return(
    return_id: UUID,
    payload: SalesReturnUpdate,
    tenant: TenantContextDependency,
    service: SalesReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_RETURN_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesReturnResponse]:
    row = await service.update(
        tenant.tenant_id,
        return_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Sales return updated successfully")


@router.delete("/{return_id}", response_model=ApiResponse[SalesReturnResponse])
async def delete_sales_return(
    return_id: UUID,
    tenant: TenantContextDependency,
    service: SalesReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_RETURN_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesReturnResponse]:
    row = await service.delete(
        tenant.tenant_id,
        return_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Sales return deleted successfully")


@router.post("/{return_id}/post", response_model=ApiResponse[SalesReturnResponse])
async def post_sales_return(
    return_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: SalesReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_RETURN_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[SalesReturnResponse]:
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
    return ApiResponse(data=row, message="Sales return posted successfully")


@router.post("/{return_id}/cancel", response_model=ApiResponse[SalesReturnResponse])
async def cancel_sales_return(
    return_id: UUID,
    tenant: TenantContextDependency,
    service: SalesReturnServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_RETURN_UPDATE))],
    if_match: IfMatch = None,
    payload: Annotated[SalesReturnCancelRequest | None, Body()] = None,
) -> ApiResponse[SalesReturnResponse]:
    body_payload = payload or SalesReturnCancelRequest()
    row = await service.cancel(
        tenant.tenant_id,
        return_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=body_payload.version
        ),
        reason=body_payload.reason,
    )
    return ApiResponse(data=row, message="Sales return cancelled")
