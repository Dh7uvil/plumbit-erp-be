"""Purchase order routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, status

from app.auth.catalog import (
    PURCHASE_ORDER_APPROVE,
    PURCHASE_ORDER_CLOSE,
    PURCHASE_ORDER_CREATE,
    PURCHASE_ORDER_DELETE,
    PURCHASE_ORDER_ISSUE,
    PURCHASE_ORDER_READ,
    PURCHASE_ORDER_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.purchase_orders.dependencies import PurchaseOrderServiceDependency
from app.erp.purchase_orders.schemas import (
    PurchaseOrderCancelRequest,
    PurchaseOrderComposeDefaults,
    PurchaseOrderCreate,
    PurchaseOrderFilter,
    PurchaseOrderRejectRequest,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
)

router = APIRouter(prefix="/purchase-orders", tags=["Purchase Orders"])

IfMatch = Annotated[str | None, Header()]


@router.get("/compose-defaults", response_model=ApiResponse[PurchaseOrderComposeDefaults])
async def compose_defaults(
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    supplier_id: Annotated[UUID, Query()],
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_READ))],
) -> ApiResponse[PurchaseOrderComposeDefaults]:
    data = await service.compose_defaults(tenant.tenant_id, supplier_id)
    return ApiResponse(data=data)


@router.get("", response_model=ApiResponse[list[PurchaseOrderResponse]])
async def list_purchase_orders(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: PurchaseOrderServiceDependency,
    filters: Annotated[PurchaseOrderFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_READ))],
) -> ApiResponse[list[PurchaseOrderResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        receipt_status=filters.receipt_status.value if filters.receipt_status else None,
        billing_status=filters.billing_status.value if filters.billing_status else None,
        supplier_id=filters.supplier_id,
        branch_id=filters.branch_id,
        warehouse_id=filters.warehouse_id,
        currency_id=filters.currency_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[PurchaseOrderResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_CREATE))],
) -> ApiResponse[PurchaseOrderResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Purchase order created successfully")


@router.get("/{purchase_order_id}", response_model=ApiResponse[PurchaseOrderResponse])
async def get_purchase_order(
    purchase_order_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_READ))],
) -> ApiResponse[PurchaseOrderResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, purchase_order_id))


@router.patch("/{purchase_order_id}", response_model=ApiResponse[PurchaseOrderResponse])
async def update_purchase_order(
    purchase_order_id: UUID,
    payload: PurchaseOrderUpdate,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseOrderResponse]:
    row = await service.update(
        tenant.tenant_id,
        purchase_order_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Purchase order updated successfully")


@router.delete("/{purchase_order_id}", response_model=ApiResponse[PurchaseOrderResponse])
async def delete_purchase_order(
    purchase_order_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseOrderResponse]:
    row = await service.delete(
        tenant.tenant_id,
        purchase_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Purchase order deleted successfully")


@router.post("/{purchase_order_id}/submit", response_model=ApiResponse[PurchaseOrderResponse])
async def submit_purchase_order(
    purchase_order_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseOrderResponse]:
    row = await service.submit(
        tenant.tenant_id,
        purchase_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Purchase order submitted for approval")


@router.post("/{purchase_order_id}/approve", response_model=ApiResponse[PurchaseOrderResponse])
async def approve_purchase_order(
    purchase_order_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_APPROVE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseOrderResponse]:
    row = await service.approve(
        tenant.tenant_id,
        purchase_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Purchase order approved successfully")


@router.post("/{purchase_order_id}/reject", response_model=ApiResponse[PurchaseOrderResponse])
async def reject_purchase_order(
    purchase_order_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_APPROVE))],
    if_match: IfMatch = None,
    payload: Annotated[PurchaseOrderRejectRequest | None, Body()] = None,
) -> ApiResponse[PurchaseOrderResponse]:
    body = payload or PurchaseOrderRejectRequest()
    row = await service.reject(
        tenant.tenant_id,
        purchase_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        reason=body.reason,
    )
    return ApiResponse(data=row, message="Purchase order rejected")


@router.post("/{purchase_order_id}/reopen", response_model=ApiResponse[PurchaseOrderResponse])
async def reopen_purchase_order(
    purchase_order_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseOrderResponse]:
    row = await service.reopen(
        tenant.tenant_id,
        purchase_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Purchase order reopened")


@router.post("/{purchase_order_id}/issue", response_model=ApiResponse[PurchaseOrderResponse])
async def issue_purchase_order(
    purchase_order_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_ISSUE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseOrderResponse]:
    row = await service.issue(
        tenant.tenant_id,
        purchase_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Purchase order issued")


@router.post("/{purchase_order_id}/close", response_model=ApiResponse[PurchaseOrderResponse])
async def close_purchase_order(
    purchase_order_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_CLOSE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseOrderResponse]:
    row = await service.close(
        tenant.tenant_id,
        purchase_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Purchase order closed")


@router.post("/{purchase_order_id}/cancel", response_model=ApiResponse[PurchaseOrderResponse])
async def cancel_purchase_order(
    purchase_order_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_UPDATE))],
    if_match: IfMatch = None,
    payload: Annotated[PurchaseOrderCancelRequest | None, Body()] = None,
) -> ApiResponse[PurchaseOrderResponse]:
    body = payload or PurchaseOrderCancelRequest()
    row = await service.cancel(
        tenant.tenant_id,
        purchase_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        reason=body.reason,
    )
    return ApiResponse(data=row, message="Purchase order cancelled")


@router.post("/{purchase_order_id}/clone", response_model=ApiResponse[PurchaseOrderResponse])
async def clone_purchase_order(
    purchase_order_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_CREATE))],
) -> ApiResponse[PurchaseOrderResponse]:
    row = await service.clone(tenant.tenant_id, purchase_order_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Purchase order cloned as a new draft")
