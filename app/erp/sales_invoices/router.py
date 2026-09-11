"""Sales invoice routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    COST_READ,
    CUSTOMER_PAYMENT_CREATE,
    SALES_INVOICE_CANCEL,
    SALES_INVOICE_CREATE,
    SALES_INVOICE_DELETE,
    SALES_INVOICE_POST,
    SALES_INVOICE_READ,
    SALES_INVOICE_UPDATE,
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
from app.erp.customer_payments.dependencies import CustomerPaymentServiceDependency
from app.erp.sales_invoices.dependencies import SalesInvoiceServiceDependency
from app.erp.sales_invoices.schemas import (
    SalesInvoiceCancelRequest,
    SalesInvoiceCreate,
    SalesInvoiceCreateFromDeliveryNotes,
    SalesInvoiceCreateFromSalesOrder,
    SalesInvoiceFilter,
    SalesInvoiceMarginResponse,
    SalesInvoiceResponse,
    SalesInvoiceUpdate,
)

router = APIRouter(prefix="/sales-invoices", tags=["Sales Invoices"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]
CreditOverrideHeader = Annotated[str | None, Header(alias="X-Credit-Override")]


@router.get("", response_model=ApiResponse[list[SalesInvoiceResponse]])
async def list_sales_invoices(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: SalesInvoiceServiceDependency,
    filters: Annotated[SalesInvoiceFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_READ))],
) -> ApiResponse[list[SalesInvoiceResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        customer_id=filters.customer_id,
        sales_order_id=filters.sales_order_id,
        source_quotation_id=filters.source_quotation_id,
        source_proforma_invoice_id=filters.source_proforma_invoice_id,
        branch_id=filters.branch_id,
        currency_id=filters.currency_id,
        payment_status=filters.payment_status.value if filters.payment_status else None,
        invoice_date_from=filters.invoice_date_from,
        invoice_date_to=filters.invoice_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "/from-sales-order",
    response_model=ApiResponse[SalesInvoiceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_sales_invoice_from_sales_order(
    payload: SalesInvoiceCreateFromSalesOrder,
    request: Request,
    tenant: TenantContextDependency,
    service: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[SalesInvoiceResponse]:
    body = await request.body()
    row = await service.create_from_sales_order(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Sales invoice created from sales order")


@router.post(
    "/from-delivery-notes",
    response_model=ApiResponse[SalesInvoiceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_sales_invoice_from_delivery_notes(
    payload: SalesInvoiceCreateFromDeliveryNotes,
    request: Request,
    tenant: TenantContextDependency,
    service: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[SalesInvoiceResponse]:
    body = await request.body()
    row = await service.create_from_delivery_notes(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Sales invoice created from delivery notes")


@router.post(
    "",
    response_model=ApiResponse[SalesInvoiceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_sales_invoice(
    payload: SalesInvoiceCreate,
    tenant: TenantContextDependency,
    service: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_CREATE))],
) -> ApiResponse[SalesInvoiceResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Sales invoice created successfully")


@router.get("/{invoice_id}", response_model=ApiResponse[SalesInvoiceResponse])
async def get_sales_invoice(
    invoice_id: UUID,
    tenant: TenantContextDependency,
    service: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_READ))],
) -> ApiResponse[SalesInvoiceResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, invoice_id))


@router.patch("/{invoice_id}", response_model=ApiResponse[SalesInvoiceResponse])
async def update_sales_invoice(
    invoice_id: UUID,
    payload: SalesInvoiceUpdate,
    tenant: TenantContextDependency,
    service: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesInvoiceResponse]:
    row = await service.update(
        tenant.tenant_id,
        invoice_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Sales invoice updated successfully")


@router.delete("/{invoice_id}", response_model=ApiResponse[SalesInvoiceResponse])
async def delete_sales_invoice(
    invoice_id: UUID,
    tenant: TenantContextDependency,
    service: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesInvoiceResponse]:
    row = await service.delete(
        tenant.tenant_id,
        invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Sales invoice deleted successfully")


@router.post("/{invoice_id}/post", response_model=ApiResponse[SalesInvoiceResponse])
async def post_sales_invoice(
    invoice_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    credit_override: CreditOverrideHeader = None,
) -> ApiResponse[SalesInvoiceResponse]:
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
        override_reason=credit_override,
    )
    message = "Sales invoice posted successfully"
    meta: dict[str, object] = {}
    if row.is_export and not row.export_evidence_ok:
        message = "Sales invoice posted; export evidence is missing"
        meta["export_evidence_ok"] = False
    return ApiResponse(data=row, message=message, meta=meta)


@router.post("/{invoice_id}/cancel", response_model=ApiResponse[SalesInvoiceResponse])
async def cancel_sales_invoice(
    invoice_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_CANCEL))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[SalesInvoiceCancelRequest | None, Body()] = None,
) -> ApiResponse[SalesInvoiceResponse]:
    body_payload = payload or SalesInvoiceCancelRequest()
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
    return ApiResponse(data=row, message="Sales invoice cancelled")


@router.post("/{invoice_id}/apply-credits", response_model=ApiResponse[SalesInvoiceResponse])
async def apply_credits_to_sales_invoice(
    invoice_id: UUID,
    payload: ApplyCreditsRequest,
    tenant: TenantContextDependency,
    payments: CustomerPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_PAYMENT_CREATE))],
    if_match: IfMatch = None,
) -> ApiResponse[SalesInvoiceResponse]:
    row = await payments.apply_credits_to_invoice(
        tenant.tenant_id,
        invoice_id,
        payload.allocations,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=payload.version
        ),
    )
    return ApiResponse(data=row, message="Credits applied to sales invoice")


@router.get("/{invoice_id}/journal", response_model=ApiResponse[JournalEntryResponse])
async def get_sales_invoice_journal(
    invoice_id: UUID,
    tenant: TenantContextDependency,
    service: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_READ))],
) -> ApiResponse[JournalEntryResponse]:
    return ApiResponse(data=await service.journal(tenant.tenant_id, invoice_id))


@router.get("/{invoice_id}/margin", response_model=ApiResponse[SalesInvoiceMarginResponse])
async def get_sales_invoice_margin(
    invoice_id: UUID,
    tenant: TenantContextDependency,
    service: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_READ))],
    __: Annotated[CurrentUser, Depends(require_permission(COST_READ))],
) -> ApiResponse[SalesInvoiceMarginResponse]:
    return ApiResponse(data=await service.margin(tenant.tenant_id, invoice_id))
