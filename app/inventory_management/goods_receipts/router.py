"""Goods receipt routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Request, status

from app.auth.catalog import (
    GOODS_RECEIPT_CREATE,
    GOODS_RECEIPT_DELETE,
    GOODS_RECEIPT_POST,
    GOODS_RECEIPT_READ,
    GOODS_RECEIPT_UPDATE,
    LANDED_COST_READ,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.print.schemas import PrintDocumentResponse
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.landed_costs.dependencies import LandedCostServiceDependency
from app.erp.landed_costs.schemas import LandedCostEligibleResponse
from app.inventory_management.goods_receipts.dependencies import GoodsReceiptServiceDependency
from app.inventory_management.goods_receipts.schemas import (
    GoodsReceiptCancelRequest,
    GoodsReceiptCreate,
    GoodsReceiptCreateFromPurchaseOrder,
    GoodsReceiptFilter,
    GoodsReceiptResponse,
    GoodsReceiptUpdate,
)

router = APIRouter(prefix="/goods-receipts", tags=["Goods Receipts"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[GoodsReceiptResponse]])
async def list_goods_receipts(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: GoodsReceiptServiceDependency,
    filters: Annotated[GoodsReceiptFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(GOODS_RECEIPT_READ))],
) -> ApiResponse[list[GoodsReceiptResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        warehouse_id=filters.warehouse_id,
        supplier_id=filters.supplier_id,
        purchase_order_id=filters.purchase_order_id,
        qc_status=filters.qc_status.value if filters.qc_status else None,
        product_id=filters.product_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "/from-purchase-order",
    response_model=ApiResponse[GoodsReceiptResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_goods_receipt_from_purchase_order(
    payload: GoodsReceiptCreateFromPurchaseOrder,
    request: Request,
    tenant: TenantContextDependency,
    service: GoodsReceiptServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GOODS_RECEIPT_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[GoodsReceiptResponse]:
    body = await request.body()
    row = await service.create_from_purchase_order(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Goods receipt created from purchase order")


@router.post(
    "",
    response_model=ApiResponse[GoodsReceiptResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_goods_receipt(
    payload: GoodsReceiptCreate,
    tenant: TenantContextDependency,
    service: GoodsReceiptServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GOODS_RECEIPT_CREATE))],
) -> ApiResponse[GoodsReceiptResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Goods receipt created successfully")


@router.get("/{receipt_id}", response_model=ApiResponse[GoodsReceiptResponse])
async def get_goods_receipt(
    receipt_id: UUID,
    tenant: TenantContextDependency,
    service: GoodsReceiptServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GOODS_RECEIPT_READ))],
) -> ApiResponse[GoodsReceiptResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, receipt_id))


@router.get("/{receipt_id}/print", response_model=ApiResponse[PrintDocumentResponse])
async def print_goods_receipt(
    receipt_id: UUID,
    tenant: TenantContextDependency,
    service: GoodsReceiptServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GOODS_RECEIPT_READ))],
    template_family: Annotated[str, Query()] = "uae",
) -> ApiResponse[PrintDocumentResponse]:
    return ApiResponse(
        data=await service.print_document(
            tenant.tenant_id, receipt_id, template_family=template_family
        )
    )


@router.patch("/{receipt_id}", response_model=ApiResponse[GoodsReceiptResponse])
async def update_goods_receipt(
    receipt_id: UUID,
    payload: GoodsReceiptUpdate,
    tenant: TenantContextDependency,
    service: GoodsReceiptServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GOODS_RECEIPT_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[GoodsReceiptResponse]:
    row = await service.update(
        tenant.tenant_id,
        receipt_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Goods receipt updated successfully")


@router.delete("/{receipt_id}", response_model=ApiResponse[GoodsReceiptResponse])
async def delete_goods_receipt(
    receipt_id: UUID,
    tenant: TenantContextDependency,
    service: GoodsReceiptServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GOODS_RECEIPT_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[GoodsReceiptResponse]:
    row = await service.delete(
        tenant.tenant_id,
        receipt_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Goods receipt deleted successfully")


@router.post("/{receipt_id}/post", response_model=ApiResponse[GoodsReceiptResponse])
async def post_goods_receipt(
    receipt_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: GoodsReceiptServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GOODS_RECEIPT_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[GoodsReceiptResponse]:
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        receipt_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Goods receipt posted successfully")


@router.post("/{receipt_id}/cancel", response_model=ApiResponse[GoodsReceiptResponse])
async def cancel_goods_receipt(
    receipt_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: GoodsReceiptServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GOODS_RECEIPT_UPDATE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[GoodsReceiptCancelRequest | None, Body()] = None,
) -> ApiResponse[GoodsReceiptResponse]:
    body_payload = payload or GoodsReceiptCancelRequest()
    body = await request.body()
    row = await service.cancel(
        tenant.tenant_id,
        receipt_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=body_payload.version
        ),
        reason=body_payload.reason,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Goods receipt cancelled")


@router.get(
    "/{receipt_id}/landed-cost-eligible",
    response_model=ApiResponse[LandedCostEligibleResponse],
)
async def get_landed_cost_eligible(
    receipt_id: UUID,
    tenant: TenantContextDependency,
    landed_costs: LandedCostServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LANDED_COST_READ))],
) -> ApiResponse[LandedCostEligibleResponse]:
    return ApiResponse(
        data=await landed_costs.eligible_for_goods_receipt(tenant.tenant_id, receipt_id)
    )
