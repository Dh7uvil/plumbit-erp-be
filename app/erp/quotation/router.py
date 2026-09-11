"""Quotation routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, Form, Header, Query, Request, UploadFile, status

from app.auth.catalog import (
    PROFORMA_INVOICE_CREATE,
    QUOTATION_APPROVE,
    QUOTATION_CREATE,
    QUOTATION_DELETE,
    QUOTATION_EXPORT,
    QUOTATION_IMPORT,
    QUOTATION_READ,
    QUOTATION_REVISE,
    QUOTATION_SEND,
    QUOTATION_UPDATE,
    SALES_INVOICE_CREATE,
    SALES_ORDER_CREATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.imex.http import parse_mapping_json, read_upload
from app.common.imex.schemas import ImportPreviewResponse, ImportResult
from app.common.imex.service import export_response, preview_file, template_response
from app.common.print.schemas import PrintDocumentResponse
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.proforma_invoices.dependencies import ProformaInvoiceServiceDependency
from app.erp.proforma_invoices.schemas import ProformaInvoiceResponse
from app.erp.quotation.dependencies import QuotationServiceDependency
from app.erp.quotation.schemas import (
    ConvertToProformaInvoiceRequest,
    ConvertToSalesInvoiceRequest,
    ConvertToSalesOrderRequest,
    QuotationComposeDefaults,
    QuotationCreate,
    QuotationFilter,
    QuotationRejectRequest,
    QuotationResponse,
    QuotationReviseRequest,
    QuotationRevisionListItem,
    QuotationRevisionResponse,
    QuotationUpdate,
)
from app.erp.sales_invoices.dependencies import SalesInvoiceServiceDependency
from app.erp.sales_invoices.schemas import SalesInvoiceResponse
from app.erp.sales_orders.dependencies import SalesOrderServiceDependency
from app.erp.sales_orders.schemas import SalesOrderResponse

router = APIRouter(prefix="/quotations", tags=["Quotations"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("/compose-defaults", response_model=ApiResponse[QuotationComposeDefaults])
async def compose_defaults(
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    customer_id: Annotated[UUID, Query()],
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_READ))],
) -> ApiResponse[QuotationComposeDefaults]:
    data = await service.compose_defaults(tenant.tenant_id, customer_id)
    return ApiResponse(data=data)


@router.get("", response_model=ApiResponse[list[QuotationResponse]])
async def list_quotations(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: QuotationServiceDependency,
    filters: Annotated[QuotationFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_READ))],
) -> ApiResponse[list[QuotationResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        customer_id=filters.customer_id,
        branch_id=filters.branch_id,
        currency_id=filters.currency_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.get("/import/template")
async def quotation_import_template(
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_IMPORT))],
):
    return template_response("quotation")


@router.post("/import/preview", response_model=ApiResponse[ImportPreviewResponse])
async def quotation_import_preview(
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_IMPORT))],
    file: Annotated[UploadFile, File()],
) -> ApiResponse[ImportPreviewResponse]:
    filename, content = await read_upload(file)
    return ApiResponse(data=preview_file("quotation", filename=filename, content=content))


@router.post(
    "/import",
    response_model=ApiResponse[ImportResult],
    status_code=status.HTTP_201_CREATED,
)
async def quotation_import(
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_IMPORT))],
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str | None, Form()] = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[ImportResult]:
    require_idempotency_key(idempotency_key)
    filename, content = await read_upload(file)
    result = await service.import_drafts(
        tenant.tenant_id,
        filename=filename,
        content=content,
        mapping=parse_mapping_json(mapping),
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=result, message="Quotation drafts imported")


@router.get("/export")
async def quotation_export(
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    filters: Annotated[QuotationFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_EXPORT))],
):
    rows = await service.export_rows(
        tenant.tenant_id,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        customer_id=filters.customer_id,
        branch_id=filters.branch_id,
        currency_id=filters.currency_id,
    )
    headers = [
        "document_number",
        "document_date",
        "customer_id",
        "line.item_code",
        "line.description",
        "line.quantity",
        "line.unit_price",
        "line.carton_qty",
        "line.packing_unit",
        "line.cbm",
        "line.weight",
    ]
    return export_response("quotation", headers, rows)


@router.post("", response_model=ApiResponse[QuotationResponse], status_code=status.HTTP_201_CREATED)
async def create_quotation(
    payload: QuotationCreate,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_CREATE))],
) -> ApiResponse[QuotationResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Quotation created successfully")


@router.get("/{quotation_id}", response_model=ApiResponse[QuotationResponse])
async def get_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_READ))],
) -> ApiResponse[QuotationResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, quotation_id))


@router.get("/{quotation_id}/print", response_model=ApiResponse[PrintDocumentResponse])
async def print_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_READ))],
    template_family: Annotated[str, Query()] = "uae",
) -> ApiResponse[PrintDocumentResponse]:
    return ApiResponse(
        data=await service.print_document(
            tenant.tenant_id, quotation_id, template_family=template_family
        )
    )


@router.patch("/{quotation_id}", response_model=ApiResponse[QuotationResponse])
async def update_quotation(
    quotation_id: UUID,
    payload: QuotationUpdate,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[QuotationResponse]:
    row = await service.update(
        tenant.tenant_id,
        quotation_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Quotation updated successfully")


@router.delete("/{quotation_id}", response_model=ApiResponse[QuotationResponse])
async def delete_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[QuotationResponse]:
    row = await service.delete(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Quotation deleted successfully")


@router.post("/{quotation_id}/submit", response_model=ApiResponse[QuotationResponse])
async def submit_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[QuotationResponse]:
    row = await service.submit(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Quotation submitted for approval")


@router.post("/{quotation_id}/approve", response_model=ApiResponse[QuotationResponse])
async def approve_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_APPROVE))],
    if_match: IfMatch = None,
) -> ApiResponse[QuotationResponse]:
    row = await service.approve(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Quotation approved successfully")


@router.post("/{quotation_id}/reject", response_model=ApiResponse[QuotationResponse])
async def reject_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_APPROVE))],
    if_match: IfMatch = None,
    payload: Annotated[QuotationRejectRequest | None, Body()] = None,
) -> ApiResponse[QuotationResponse]:
    body = payload or QuotationRejectRequest()
    row = await service.reject(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        reason=body.reason,
    )
    return ApiResponse(data=row, message="Quotation rejected")


@router.post("/{quotation_id}/reopen", response_model=ApiResponse[QuotationResponse])
async def reopen_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[QuotationResponse]:
    row = await service.reopen(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Quotation reopened as draft")


@router.post("/{quotation_id}/send", response_model=ApiResponse[QuotationResponse])
async def send_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_SEND))],
    if_match: IfMatch = None,
) -> ApiResponse[QuotationResponse]:
    row = await service.send(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Quotation sent successfully")


@router.post("/{quotation_id}/accept", response_model=ApiResponse[QuotationResponse])
async def accept_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[QuotationResponse]:
    row = await service.accept(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Quotation accepted")


@router.post("/{quotation_id}/decline", response_model=ApiResponse[QuotationResponse])
async def decline_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[QuotationResponse]:
    row = await service.decline(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Quotation declined")


@router.post("/{quotation_id}/cancel", response_model=ApiResponse[QuotationResponse])
async def cancel_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[QuotationResponse]:
    row = await service.cancel(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Quotation cancelled")


@router.post("/{quotation_id}/revise", response_model=ApiResponse[QuotationResponse])
async def revise_quotation(
    quotation_id: UUID,
    payload: QuotationReviseRequest,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_REVISE))],
    if_match: IfMatch = None,
) -> ApiResponse[QuotationResponse]:
    row = await service.revise(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
        revision_reason=payload.revision_reason,
    )
    return ApiResponse(data=row, message="Quotation revised")


@router.get(
    "/{quotation_id}/revisions",
    response_model=ApiResponse[list[QuotationRevisionListItem]],
)
async def list_quotation_revisions(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_READ))],
) -> ApiResponse[list[QuotationRevisionListItem]]:
    rows = await service.list_revisions(tenant.tenant_id, quotation_id)
    return ApiResponse(data=rows)


@router.get(
    "/{quotation_id}/revisions/{revision_number}",
    response_model=ApiResponse[QuotationRevisionResponse],
)
async def get_quotation_revision(
    quotation_id: UUID,
    revision_number: int,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_READ))],
) -> ApiResponse[QuotationRevisionResponse]:
    return ApiResponse(
        data=await service.get_revision(tenant.tenant_id, quotation_id, revision_number)
    )


@router.post("/{quotation_id}/clone", response_model=ApiResponse[QuotationResponse])
async def clone_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_CREATE))],
) -> ApiResponse[QuotationResponse]:
    row = await service.clone(tenant.tenant_id, quotation_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Quotation cloned as a new draft")


@router.post(
    "/{quotation_id}/convert-to-sales-order",
    response_model=ApiResponse[SalesOrderResponse],
)
async def convert_quotation_to_sales_order(
    quotation_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    sales_orders: SalesOrderServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_UPDATE))],
    __: Annotated[CurrentUser, Depends(require_permission(SALES_ORDER_CREATE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[ConvertToSalesOrderRequest | None, Body()] = None,
) -> ApiResponse[SalesOrderResponse]:
    body = payload or ConvertToSalesOrderRequest()
    raw_body = await request.body()
    row = await sales_orders.create_from_quotation(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        order_date=body.order_date,
        expected_shipment_date=body.expected_shipment_date,
        reference_number=body.reference_number,
        customer_po_number=body.customer_po_number,
        customer_po_date=body.customer_po_date,
        warehouse_id=body.warehouse_id,
        branch_id=body.branch_id,
        conversion_lines=body.lines,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=raw_body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Quotation converted to a sales order")


@router.post(
    "/{quotation_id}/convert-to-proforma-invoice",
    response_model=ApiResponse[ProformaInvoiceResponse],
)
async def convert_quotation_to_proforma_invoice(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    proforma_invoices: ProformaInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_READ))],
    __: Annotated[CurrentUser, Depends(require_permission(PROFORMA_INVOICE_CREATE))],
    if_match: IfMatch = None,
    payload: Annotated[ConvertToProformaInvoiceRequest | None, Body()] = None,
) -> ApiResponse[ProformaInvoiceResponse]:
    body = payload or ConvertToProformaInvoiceRequest()
    row = await proforma_invoices.create_from_quotation(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        proforma_date=body.proforma_date,
        valid_until=body.valid_until,
        incoterm=body.incoterm,
        incoterm_place=body.incoterm_place,
    )
    return ApiResponse(data=row, message="Proforma invoice created from quotation")


@router.post(
    "/{quotation_id}/convert-to-sales-invoice",
    response_model=ApiResponse[SalesInvoiceResponse],
)
async def convert_quotation_to_sales_invoice(
    quotation_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    sales_invoices: SalesInvoiceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_UPDATE))],
    __: Annotated[CurrentUser, Depends(require_permission(SALES_INVOICE_CREATE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[ConvertToSalesInvoiceRequest | None, Body()] = None,
) -> ApiResponse[SalesInvoiceResponse]:
    body = payload or ConvertToSalesInvoiceRequest()
    raw_body = await request.body()
    row = await sales_invoices.create_from_quotation(
        tenant.tenant_id,
        quotation_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        invoice_date=body.invoice_date,
        notes=body.notes,
        conversion_lines=body.lines,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=raw_body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Quotation converted to a sales invoice")
