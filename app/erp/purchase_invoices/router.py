"""Purchase invoice routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    PURCHASE_INVOICE_CANCEL,
    PURCHASE_INVOICE_CREATE,
    PURCHASE_INVOICE_DELETE,
    PURCHASE_INVOICE_POST,
    PURCHASE_INVOICE_READ,
    PURCHASE_INVOICE_UPDATE,
    SUPPLIER_PAYMENT_CREATE,
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
from app.erp.accounting.open_items.schemas import ApplyCreditsRequest
from app.erp.purchase_invoices.dependencies import PurchaseInvoiceServiceDependency
from app.erp.purchase_invoices.schemas import (
    PurchaseInvoiceCancelRequest,
    PurchaseInvoiceCreate,
    PurchaseInvoiceCreateFromGoodsReceipt,
    PurchaseInvoiceCreateFromPurchaseOrder,
    PurchaseInvoiceFilter,
    PurchaseInvoiceResponse,
    PurchaseInvoiceUpdate,
)
from app.erp.supplier_payments.dependencies import SupplierPaymentServiceDependency

router = APIRouter(prefix="/purchase-invoices", tags=["Purchase Invoices"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[PurchaseInvoiceResponse]])
async def list_purchase_invoices(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: PurchaseInvoiceServiceDependency,
    filters: Annotated[PurchaseInvoiceFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_INVOICE_READ))],
) -> ApiResponse[list[PurchaseInvoiceResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        supplier_id=filters.supplier_id,
        purchase_order_id=filters.purchase_order_id,
        goods_receipt_id=filters.goods_receipt_id,
        bill_type=filters.bill_type.value if filters.bill_type else None,
        payment_status=filters.payment_status.value if filters.payment_status else None,
        invoice_date_from=filters.invoice_date_from,
        invoice_date_to=filters.invoice_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "/from-purchase-order",
    response_model=ApiResponse[PurchaseInvoiceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_purchase_invoice_from_purchase_order(
    payload: PurchaseInvoiceCreateFromPurchaseOrder,
    request: Request,
    tenant: TenantContextDependency,
    service: PurchaseInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_INVOICE_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[PurchaseInvoiceResponse]:
    body = await request.body()
    row = await service.create_from_purchase_order(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Purchase invoice created from purchase order")


@router.post(
    "/from-goods-receipt",
    response_model=ApiResponse[PurchaseInvoiceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_purchase_invoice_from_goods_receipt(
    payload: PurchaseInvoiceCreateFromGoodsReceipt,
    request: Request,
    tenant: TenantContextDependency,
    service: PurchaseInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_INVOICE_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[PurchaseInvoiceResponse]:
    body = await request.body()
    row = await service.create_from_goods_receipt(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Purchase invoice created from goods receipt")


@router.post(
    "",
    response_model=ApiResponse[PurchaseInvoiceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_purchase_invoice(
    payload: PurchaseInvoiceCreate,
    tenant: TenantContextDependency,
    service: PurchaseInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_INVOICE_CREATE))],
) -> ApiResponse[PurchaseInvoiceResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Purchase invoice created successfully")


@router.get("/{invoice_id}", response_model=ApiResponse[PurchaseInvoiceResponse])
async def get_purchase_invoice(
    invoice_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_INVOICE_READ))],
) -> ApiResponse[PurchaseInvoiceResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, invoice_id))


@router.patch("/{invoice_id}", response_model=ApiResponse[PurchaseInvoiceResponse])
async def update_purchase_invoice(
    invoice_id: UUID,
    payload: PurchaseInvoiceUpdate,
    tenant: TenantContextDependency,
    service: PurchaseInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_INVOICE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseInvoiceResponse]:
    row = await service.update(
        tenant.tenant_id,
        invoice_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Purchase invoice updated successfully")


@router.delete("/{invoice_id}", response_model=ApiResponse[PurchaseInvoiceResponse])
async def delete_purchase_invoice(
    invoice_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_INVOICE_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseInvoiceResponse]:
    row = await service.delete(
        tenant.tenant_id,
        invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Purchase invoice deleted successfully")


@router.post("/{invoice_id}/post", response_model=ApiResponse[PurchaseInvoiceResponse])
async def post_purchase_invoice(
    invoice_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: PurchaseInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_INVOICE_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[PurchaseInvoiceResponse]:
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Purchase invoice posted successfully")


@router.post("/{invoice_id}/cancel", response_model=ApiResponse[PurchaseInvoiceResponse])
async def cancel_purchase_invoice(
    invoice_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: PurchaseInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_INVOICE_CANCEL))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[PurchaseInvoiceCancelRequest | None, Body()] = None,
) -> ApiResponse[PurchaseInvoiceResponse]:
    body_payload = payload or PurchaseInvoiceCancelRequest()
    body = await request.body()
    row = await service.cancel(
        tenant.tenant_id,
        invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=body_payload.version
        ),
        reason=body_payload.reason,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Purchase invoice cancelled")


@router.post("/{invoice_id}/apply-debits", response_model=ApiResponse[PurchaseInvoiceResponse])
async def apply_debits_to_purchase_invoice(
    invoice_id: UUID,
    payload: ApplyCreditsRequest,
    tenant: TenantContextDependency,
    payments: SupplierPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SUPPLIER_PAYMENT_CREATE))],
    if_match: IfMatch = None,
) -> ApiResponse[PurchaseInvoiceResponse]:
    row = await payments.apply_debits_to_invoice(
        tenant.tenant_id,
        invoice_id,
        payload.allocations,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=payload.version
        ),
    )
    return ApiResponse(data=row, message="Debits applied to purchase invoice")


@router.get("/{invoice_id}/journal", response_model=ApiResponse[JournalEntryResponse])
async def get_purchase_invoice_journal(
    invoice_id: UUID,
    tenant: TenantContextDependency,
    service: PurchaseInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PURCHASE_INVOICE_READ))],
) -> ApiResponse[JournalEntryResponse]:
    return ApiResponse(data=await service.journal(tenant.tenant_id, invoice_id))
