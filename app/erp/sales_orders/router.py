"""Sales order routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Request, status

from app.auth.catalog import (
    PURCHASE_ORDER_CREATE,
    SALES_ORDER_ACKNOWLEDGE,
    SALES_ORDER_APPROVE,
    SALES_ORDER_CLOSE,
    SALES_ORDER_CONFIRM,
    SALES_ORDER_CREATE,
    SALES_ORDER_DELETE,
    SALES_ORDER_READ,
    SALES_ORDER_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.purchase_orders.dependencies import PurchaseOrderServiceDependency
from app.erp.purchase_orders.schemas import (
    PurchaseOrderFromSalesOrderRequest,
    PurchaseOrderPlanResponse,
    PurchaseOrderResponse,
    SalesOrderCoverageResponse,
)
from app.erp.sales_orders.dependencies import SalesOrderServiceDependency
from app.erp.sales_orders.schemas import (
    CustomerPoDuplicate,
    OrderTrackerResponse,
    SalesOrderCancelRequest,
    SalesOrderComposeDefaults,
    SalesOrderCreate,
    SalesOrderFilter,
    SalesOrderRejectRequest,
    SalesOrderResponse,
    SalesOrderUpdate,
)
from app.inventory_management.delivery_notes.dependencies import DeliveryNoteServiceDependency
from app.inventory_management.delivery_notes.schemas import DeliverableLineResponse
from app.inventory_management.packages.dependencies import PackageServiceDependency
from app.inventory_management.packages.schemas import PackableLineResponse

router = APIRouter(prefix="/sales-orders", tags=["Sales Orders"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("/compose-defaults", response_model=ApiResponse[SalesOrderComposeDefaults])
async def compose_defaults(
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    customer_id: Annotated[UUID, Query()],
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_READ))],
) -> ApiResponse[SalesOrderComposeDefaults]:
    data = await service.compose_defaults(tenant.tenant_id, customer_id)
    return ApiResponse(data=data)


@router.get("/check-customer-po", response_model=ApiResponse[list[CustomerPoDuplicate]])
async def check_customer_po(
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    customer_id: Annotated[UUID, Query()],
    customer_po_number: Annotated[str, Query()],
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_READ))],
    exclude_id: Annotated[UUID | None, Query()] = None,
) -> ApiResponse[list[CustomerPoDuplicate]]:
    rows = await service.find_duplicate_customer_po(
        tenant.tenant_id,
        customer_id=customer_id,
        customer_po_number=customer_po_number,
        exclude_sales_order_id=exclude_id,
    )
    return ApiResponse(data=rows)


@router.get("", response_model=ApiResponse[list[SalesOrderResponse]])
async def list_sales_orders(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: SalesOrderServiceDependency,
    filters: Annotated[SalesOrderFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_READ))],
) -> ApiResponse[list[SalesOrderResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        fulfillment_status=filters.fulfillment_status.value if filters.fulfillment_status else None,
        billing_status=filters.billing_status.value if filters.billing_status else None,
        customer_id=filters.customer_id,
        branch_id=filters.branch_id,
        warehouse_id=filters.warehouse_id,
        currency_id=filters.currency_id,
        salesperson_id=filters.salesperson_id,
        source_quotation_id=filters.source_quotation_id,
        source_proforma_invoice_id=filters.source_proforma_invoice_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "", response_model=ApiResponse[SalesOrderResponse], status_code=status.HTTP_201_CREATED
)
async def create_sales_order(
    payload: SalesOrderCreate,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_CREATE))],
) -> ApiResponse[SalesOrderResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Sales order created successfully")


@router.get("/{sales_order_id}", response_model=ApiResponse[SalesOrderResponse])
async def get_sales_order(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_READ))],
) -> ApiResponse[SalesOrderResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, sales_order_id))


@router.patch("/{sales_order_id}", response_model=ApiResponse[SalesOrderResponse])
async def update_sales_order(
    sales_order_id: UUID,
    payload: SalesOrderUpdate,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesOrderResponse]:
    row = await service.update(
        tenant.tenant_id,
        sales_order_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Sales order updated successfully")


@router.delete("/{sales_order_id}", response_model=ApiResponse[SalesOrderResponse])
async def delete_sales_order(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesOrderResponse]:
    row = await service.delete(
        tenant.tenant_id,
        sales_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Sales order deleted successfully")


@router.post("/{sales_order_id}/submit", response_model=ApiResponse[SalesOrderResponse])
async def submit_sales_order(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesOrderResponse]:
    row = await service.submit(
        tenant.tenant_id,
        sales_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Sales order submitted for approval")


@router.post("/{sales_order_id}/approve", response_model=ApiResponse[SalesOrderResponse])
async def approve_sales_order(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_APPROVE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesOrderResponse]:
    row = await service.approve(
        tenant.tenant_id,
        sales_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Sales order approved successfully")


@router.post("/{sales_order_id}/reject", response_model=ApiResponse[SalesOrderResponse])
async def reject_sales_order(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_APPROVE))],
    if_match: IfMatch = None,
    payload: Annotated[SalesOrderRejectRequest | None, Body()] = None,
) -> ApiResponse[SalesOrderResponse]:
    body = payload or SalesOrderRejectRequest()
    row = await service.reject(
        tenant.tenant_id,
        sales_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        reason=body.reason,
    )
    return ApiResponse(data=row, message="Sales order rejected")


@router.post("/{sales_order_id}/reopen", response_model=ApiResponse[SalesOrderResponse])
async def reopen_sales_order(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesOrderResponse]:
    row = await service.reopen(
        tenant.tenant_id,
        sales_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Sales order reopened")


@router.post("/{sales_order_id}/confirm", response_model=ApiResponse[SalesOrderResponse])
async def confirm_sales_order(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_CONFIRM))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesOrderResponse]:
    row = await service.confirm(
        tenant.tenant_id,
        sales_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Sales order confirmed")


@router.post("/{sales_order_id}/close", response_model=ApiResponse[SalesOrderResponse])
async def close_sales_order(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_CLOSE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesOrderResponse]:
    row = await service.close(
        tenant.tenant_id,
        sales_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Sales order closed")


@router.post("/{sales_order_id}/cancel", response_model=ApiResponse[SalesOrderResponse])
async def cancel_sales_order(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_UPDATE))],
    if_match: IfMatch = None,
    payload: Annotated[SalesOrderCancelRequest | None, Body()] = None,
) -> ApiResponse[SalesOrderResponse]:
    body = payload or SalesOrderCancelRequest()
    row = await service.cancel(
        tenant.tenant_id,
        sales_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        reason=body.reason,
    )
    return ApiResponse(data=row, message="Sales order cancelled")


@router.post("/{sales_order_id}/clone", response_model=ApiResponse[SalesOrderResponse])
async def clone_sales_order(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_CREATE))],
) -> ApiResponse[SalesOrderResponse]:
    row = await service.clone(tenant.tenant_id, sales_order_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Sales order cloned as a new draft")


@router.post("/{sales_order_id}/acknowledge", response_model=ApiResponse[SalesOrderResponse])
async def acknowledge_sales_order(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_ACKNOWLEDGE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesOrderResponse]:
    row = await service.acknowledge(
        tenant.tenant_id,
        sales_order_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Sales order acknowledged")


@router.get(
    "/{sales_order_id}/purchase-order-plan",
    response_model=ApiResponse[PurchaseOrderPlanResponse],
)
async def get_purchase_order_plan(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    purchase_orders: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_READ))],
    __: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_CREATE))],
) -> ApiResponse[PurchaseOrderPlanResponse]:
    data = await purchase_orders.plan_from_sales_order(tenant.tenant_id, sales_order_id)
    return ApiResponse(data=data)


@router.get("/{sales_order_id}/coverage", response_model=ApiResponse[SalesOrderCoverageResponse])
async def get_sales_order_coverage(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    purchase_orders: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_READ))],
) -> ApiResponse[SalesOrderCoverageResponse]:
    data = await purchase_orders.coverage_for_sales_order(tenant.tenant_id, sales_order_id)
    return ApiResponse(data=data)


@router.get(
    "/{sales_order_id}/deliverable-lines",
    response_model=ApiResponse[list[DeliverableLineResponse]],
)
async def get_deliverable_lines(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    delivery_notes: DeliveryNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_READ))],
) -> ApiResponse[list[DeliverableLineResponse]]:
    rows = await delivery_notes.deliverable_lines(tenant.tenant_id, sales_order_id)
    return ApiResponse(data=rows)


@router.get(
    "/{sales_order_id}/packable-lines",
    response_model=ApiResponse[list[PackableLineResponse]],
)
async def get_packable_lines(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    packages: PackageServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_READ))],
) -> ApiResponse[list[PackableLineResponse]]:
    rows = await packages.packable_lines(tenant.tenant_id, sales_order_id)
    return ApiResponse(data=rows)


@router.get("/{sales_order_id}/tracker", response_model=ApiResponse[OrderTrackerResponse])
async def get_sales_order_tracker(
    sales_order_id: UUID,
    tenant: TenantContextDependency,
    service: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_READ))],
) -> ApiResponse[OrderTrackerResponse]:
    data = await service.tracker(tenant.tenant_id, sales_order_id)
    return ApiResponse(data=data)


@router.post(
    "/{sales_order_id}/purchase-orders",
    response_model=ApiResponse[list[PurchaseOrderResponse]],
    status_code=status.HTTP_201_CREATED,
)
async def create_purchase_orders_from_sales_order(
    sales_order_id: UUID,
    payload: PurchaseOrderFromSalesOrderRequest,
    request: Request,
    tenant: TenantContextDependency,
    purchase_orders: PurchaseOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_ORDER_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[list[PurchaseOrderResponse]]:
    raw_body = await request.body()
    rows = await purchase_orders.create_from_sales_order(
        tenant.tenant_id,
        sales_order_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=raw_body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=rows, message="Purchase orders created from sales order")
