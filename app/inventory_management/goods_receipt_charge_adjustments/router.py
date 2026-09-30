"""GRN charge adjustment routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    GRN_CHARGE_ADJUSTMENT_CREATE,
    GRN_CHARGE_ADJUSTMENT_DELETE,
    GRN_CHARGE_ADJUSTMENT_POST,
    GRN_CHARGE_ADJUSTMENT_READ,
    GRN_CHARGE_ADJUSTMENT_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.accounting.ledger.schemas import JournalEntryResponse
from app.inventory_management.goods_receipt_charge_adjustments.dependencies import (
    GoodsReceiptChargeAdjustmentServiceDependency,
)
from app.inventory_management.goods_receipt_charge_adjustments.schemas import (
    GoodsReceiptChargeAdjustmentCreate,
    GoodsReceiptChargeAdjustmentFilter,
    GoodsReceiptChargeAdjustmentResponse,
    GoodsReceiptChargeAdjustmentUpdate,
)

router = APIRouter(
    prefix="/goods-receipt-charge-adjustments",
    tags=["GRN Charge Adjustments"],
)

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[GoodsReceiptChargeAdjustmentResponse]])
async def list_goods_receipt_charge_adjustments(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: GoodsReceiptChargeAdjustmentServiceDependency,
    filters: Annotated[GoodsReceiptChargeAdjustmentFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(GRN_CHARGE_ADJUSTMENT_READ))],
) -> ApiResponse[list[GoodsReceiptChargeAdjustmentResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        goods_receipt_id=filters.goods_receipt_id,
        branch_id=filters.branch_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[GoodsReceiptChargeAdjustmentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_goods_receipt_charge_adjustment(
    payload: GoodsReceiptChargeAdjustmentCreate,
    tenant: TenantContextDependency,
    service: GoodsReceiptChargeAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GRN_CHARGE_ADJUSTMENT_CREATE))],
) -> ApiResponse[GoodsReceiptChargeAdjustmentResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="GRN charge adjustment created successfully")


@router.get("/{adjustment_id}", response_model=ApiResponse[GoodsReceiptChargeAdjustmentResponse])
async def get_goods_receipt_charge_adjustment(
    adjustment_id: UUID,
    tenant: TenantContextDependency,
    service: GoodsReceiptChargeAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GRN_CHARGE_ADJUSTMENT_READ))],
) -> ApiResponse[GoodsReceiptChargeAdjustmentResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, adjustment_id))


@router.patch("/{adjustment_id}", response_model=ApiResponse[GoodsReceiptChargeAdjustmentResponse])
async def update_goods_receipt_charge_adjustment(
    adjustment_id: UUID,
    payload: GoodsReceiptChargeAdjustmentUpdate,
    tenant: TenantContextDependency,
    service: GoodsReceiptChargeAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GRN_CHARGE_ADJUSTMENT_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[GoodsReceiptChargeAdjustmentResponse]:
    row = await service.update(
        tenant.tenant_id,
        adjustment_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="GRN charge adjustment updated successfully")


@router.delete("/{adjustment_id}", response_model=ApiResponse[GoodsReceiptChargeAdjustmentResponse])
async def delete_goods_receipt_charge_adjustment(
    adjustment_id: UUID,
    tenant: TenantContextDependency,
    service: GoodsReceiptChargeAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GRN_CHARGE_ADJUSTMENT_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[GoodsReceiptChargeAdjustmentResponse]:
    row = await service.delete(
        tenant.tenant_id,
        adjustment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="GRN charge adjustment deleted successfully")


@router.post("/{adjustment_id}/post", response_model=ApiResponse[GoodsReceiptChargeAdjustmentResponse])
async def post_goods_receipt_charge_adjustment(
    adjustment_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: GoodsReceiptChargeAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GRN_CHARGE_ADJUSTMENT_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[GoodsReceiptChargeAdjustmentResponse]:
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
    return ApiResponse(data=row, message="GRN charge adjustment posted successfully")


@router.get("/{adjustment_id}/journal", response_model=ApiResponse[JournalEntryResponse])
async def get_goods_receipt_charge_adjustment_journal(
    adjustment_id: UUID,
    tenant: TenantContextDependency,
    service: GoodsReceiptChargeAdjustmentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(GRN_CHARGE_ADJUSTMENT_READ))],
) -> ApiResponse[JournalEntryResponse]:
    return ApiResponse(data=await service.journal(tenant.tenant_id, adjustment_id))
