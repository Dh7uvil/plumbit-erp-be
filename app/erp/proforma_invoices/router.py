"""Proforma invoice routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Request, status

from app.auth.catalog import (
    PROFORMA_INVOICE_CONFIRM,
    PROFORMA_INVOICE_CREATE,
    PROFORMA_INVOICE_DELETE,
    PROFORMA_INVOICE_READ,
    PROFORMA_INVOICE_SEND,
    PROFORMA_INVOICE_UPDATE,
    SALES_INVOICE_CREATE,
    SALES_ORDER_CREATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.proforma_invoices.dependencies import ProformaInvoiceServiceDependency
from app.erp.proforma_invoices.schemas import (
    ConvertProformaToSalesInvoiceRequest,
    ConvertProformaToSalesOrderRequest,
    ProformaInvoiceComposeDefaults,
    ProformaInvoiceCreate,
    ProformaInvoiceFilter,
    ProformaInvoiceReasonRequest,
    ProformaInvoiceResponse,
    ProformaInvoiceUpdate,
)
from app.erp.sales_invoices.dependencies import SalesInvoiceServiceDependency
from app.erp.sales_invoices.schemas import SalesInvoiceResponse
from app.erp.sales_orders.dependencies import SalesOrderServiceDependency
from app.erp.sales_orders.schemas import SalesOrderResponse

router = APIRouter(prefix="/proforma-invoices", tags=["Proforma Invoices"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("/compose-defaults", response_model=ApiResponse[ProformaInvoiceComposeDefaults])
async def compose_defaults(
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    customer_id: Annotated[UUID, Query()],
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_READ))],
) -> ApiResponse[ProformaInvoiceComposeDefaults]:
    data = await service.compose_defaults(tenant.tenant_id, customer_id)
    return ApiResponse(data=data)


@router.get("", response_model=ApiResponse[list[ProformaInvoiceResponse]])
async def list_proforma_invoices(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: ProformaInvoiceServiceDependency,
    filters: Annotated[ProformaInvoiceFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_READ))],
) -> ApiResponse[list[ProformaInvoiceResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        customer_id=filters.customer_id,
        branch_id=filters.branch_id,
        currency_id=filters.currency_id,
        source_quotation_id=filters.source_quotation_id,
        source_sales_order_id=filters.source_sales_order_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[ProformaInvoiceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_proforma_invoice(
    payload: ProformaInvoiceCreate,
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_CREATE))],
) -> ApiResponse[ProformaInvoiceResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Proforma invoice created successfully")


@router.get("/{proforma_invoice_id}", response_model=ApiResponse[ProformaInvoiceResponse])
async def get_proforma_invoice(
    proforma_invoice_id: UUID,
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_READ))],
) -> ApiResponse[ProformaInvoiceResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, proforma_invoice_id))


@router.patch("/{proforma_invoice_id}", response_model=ApiResponse[ProformaInvoiceResponse])
async def update_proforma_invoice(
    proforma_invoice_id: UUID,
    payload: ProformaInvoiceUpdate,
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[ProformaInvoiceResponse]:
    row = await service.update(
        tenant.tenant_id,
        proforma_invoice_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Proforma invoice updated successfully")


@router.delete("/{proforma_invoice_id}", response_model=ApiResponse[ProformaInvoiceResponse])
async def delete_proforma_invoice(
    proforma_invoice_id: UUID,
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[ProformaInvoiceResponse]:
    row = await service.delete(
        tenant.tenant_id,
        proforma_invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Proforma invoice deleted successfully")


@router.post("/{proforma_invoice_id}/send", response_model=ApiResponse[ProformaInvoiceResponse])
async def send_proforma_invoice(
    proforma_invoice_id: UUID,
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_SEND))],
    if_match: IfMatch = None,
) -> ApiResponse[ProformaInvoiceResponse]:
    row = await service.send(
        tenant.tenant_id,
        proforma_invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Proforma invoice sent successfully")


@router.post("/{proforma_invoice_id}/confirm", response_model=ApiResponse[ProformaInvoiceResponse])
async def confirm_proforma_invoice(
    proforma_invoice_id: UUID,
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_CONFIRM))],
    if_match: IfMatch = None,
) -> ApiResponse[ProformaInvoiceResponse]:
    row = await service.confirm(
        tenant.tenant_id,
        proforma_invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Proforma invoice confirmed")


@router.post("/{proforma_invoice_id}/decline", response_model=ApiResponse[ProformaInvoiceResponse])
async def decline_proforma_invoice(
    proforma_invoice_id: UUID,
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_UPDATE))],
    if_match: IfMatch = None,
    payload: Annotated[ProformaInvoiceReasonRequest | None, Body()] = None,
) -> ApiResponse[ProformaInvoiceResponse]:
    body = payload or ProformaInvoiceReasonRequest()
    row = await service.decline(
        tenant.tenant_id,
        proforma_invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        reason=body.reason,
    )
    return ApiResponse(data=row, message="Proforma invoice declined")


@router.post("/{proforma_invoice_id}/cancel", response_model=ApiResponse[ProformaInvoiceResponse])
async def cancel_proforma_invoice(
    proforma_invoice_id: UUID,
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_UPDATE))],
    if_match: IfMatch = None,
    payload: Annotated[ProformaInvoiceReasonRequest | None, Body()] = None,
) -> ApiResponse[ProformaInvoiceResponse]:
    body = payload or ProformaInvoiceReasonRequest()
    row = await service.cancel(
        tenant.tenant_id,
        proforma_invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        reason=body.reason,
    )
    return ApiResponse(data=row, message="Proforma invoice cancelled")


@router.post("/{proforma_invoice_id}/reopen", response_model=ApiResponse[ProformaInvoiceResponse])
async def reopen_proforma_invoice(
    proforma_invoice_id: UUID,
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[ProformaInvoiceResponse]:
    row = await service.reopen(
        tenant.tenant_id,
        proforma_invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Proforma invoice reopened as draft")


@router.post("/{proforma_invoice_id}/revise", response_model=ApiResponse[ProformaInvoiceResponse])
async def revise_proforma_invoice(
    proforma_invoice_id: UUID,
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[ProformaInvoiceResponse]:
    row = await service.revise(
        tenant.tenant_id,
        proforma_invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Proforma invoice revised")


@router.post("/{proforma_invoice_id}/clone", response_model=ApiResponse[ProformaInvoiceResponse])
async def clone_proforma_invoice(
    proforma_invoice_id: UUID,
    tenant: TenantContextDependency,
    service: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_CREATE))],
) -> ApiResponse[ProformaInvoiceResponse]:
    row = await service.clone(
        tenant.tenant_id, proforma_invoice_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Proforma invoice cloned as a new draft")


@router.post(
    "/{proforma_invoice_id}/convert-to-sales-order",
    response_model=ApiResponse[SalesOrderResponse],
)
async def convert_proforma_invoice_to_sales_order(
    proforma_invoice_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    sales_orders: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_READ))],
    __: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_CREATE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[ConvertProformaToSalesOrderRequest | None, Body()] = None,
) -> ApiResponse[SalesOrderResponse]:
    body = payload or ConvertProformaToSalesOrderRequest()
    raw_body = await request.body()
    row = await sales_orders.create_from_proforma_invoice(
        tenant.tenant_id,
        proforma_invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        order_date=body.order_date,
        expected_shipment_date=body.expected_shipment_date,
        customer_po_number=body.customer_po_number,
        customer_po_date=body.customer_po_date,
        warehouse_id=body.warehouse_id,
        branch_id=body.branch_id,
        conversion_lines=body.lines,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=raw_body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Proforma invoice converted to a sales order")


@router.post(
    "/{proforma_invoice_id}/convert-to-sales-invoice",
    response_model=ApiResponse[SalesInvoiceResponse],
)
async def convert_proforma_invoice_to_sales_invoice(
    proforma_invoice_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    sales_invoices: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_READ))],
    __: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_CREATE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[ConvertProformaToSalesInvoiceRequest | None, Body()] = None,
) -> ApiResponse[SalesInvoiceResponse]:
    body = payload or ConvertProformaToSalesInvoiceRequest()
    raw_body = await request.body()
    row = await sales_invoices.create_from_proforma_invoice(
        tenant.tenant_id,
        proforma_invoice_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        invoice_date=body.invoice_date,
        notes=body.notes,
        conversion_lines=body.lines,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=raw_body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Proforma invoice converted to a sales invoice")
