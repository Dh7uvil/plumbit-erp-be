"""Credit note routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Request, status

from app.auth.catalog import (
    CREDIT_NOTE_CANCEL,
    CREDIT_NOTE_CREATE,
    CREDIT_NOTE_DELETE,
    CREDIT_NOTE_POST,
    CREDIT_NOTE_READ,
    CREDIT_NOTE_UPDATE,
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
from app.erp.accounting.ledger.schemas import JournalEntryResponse
from app.erp.credit_notes.dependencies import CreditNoteServiceDependency
from app.erp.credit_notes.schemas import (
    CreditNoteCancelRequest,
    CreditNoteCreate,
    CreditNoteCreateFromSalesInvoice,
    CreditNoteCreateFromSalesReturn,
    CreditNoteFilter,
    CreditNoteResponse,
    CreditNoteUpdate,
)

router = APIRouter(prefix="/credit-notes", tags=["Credit Notes"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[CreditNoteResponse]])
async def list_credit_notes(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CreditNoteServiceDependency,
    filters: Annotated[CreditNoteFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CREDIT_NOTE_READ))],
) -> ApiResponse[list[CreditNoteResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        customer_id=filters.customer_id,
        sales_invoice_id=filters.sales_invoice_id,
        sales_return_id=filters.sales_return_id,
        currency_id=filters.currency_id,
        credit_note_date_from=filters.credit_note_date_from,
        credit_note_date_to=filters.credit_note_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "/from-sales-invoice",
    response_model=ApiResponse[CreditNoteResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_credit_note_from_sales_invoice(
    payload: CreditNoteCreateFromSalesInvoice,
    request: Request,
    tenant: TenantContextDependency,
    service: CreditNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CREDIT_NOTE_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[CreditNoteResponse]:
    body = await request.body()
    row = await service.create_from_sales_invoice(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Credit note created from sales invoice")


@router.post(
    "/from-sales-return",
    response_model=ApiResponse[CreditNoteResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_credit_note_from_sales_return(
    payload: CreditNoteCreateFromSalesReturn,
    request: Request,
    tenant: TenantContextDependency,
    service: CreditNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CREDIT_NOTE_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[CreditNoteResponse]:
    body = await request.body()
    row = await service.create_from_sales_return(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Credit note created from sales return")


@router.post(
    "",
    response_model=ApiResponse[CreditNoteResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_credit_note(
    payload: CreditNoteCreate,
    tenant: TenantContextDependency,
    service: CreditNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CREDIT_NOTE_CREATE))],
) -> ApiResponse[CreditNoteResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Credit note created successfully")


@router.get("/{note_id}", response_model=ApiResponse[CreditNoteResponse])
async def get_credit_note(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: CreditNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CREDIT_NOTE_READ))],
) -> ApiResponse[CreditNoteResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, note_id))


@router.get("/{note_id}/print", response_model=ApiResponse[PrintDocumentResponse])
async def print_credit_note(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: CreditNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CREDIT_NOTE_READ))],
    template_family: Annotated[str, Query()] = "uae",
) -> ApiResponse[PrintDocumentResponse]:
    return ApiResponse(
        data=await service.print_document(
            tenant.tenant_id, note_id, template_family=template_family
        )
    )


@router.patch("/{note_id}", response_model=ApiResponse[CreditNoteResponse])
async def update_credit_note(
    note_id: UUID,
    payload: CreditNoteUpdate,
    tenant: TenantContextDependency,
    service: CreditNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CREDIT_NOTE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[CreditNoteResponse]:
    row = await service.update(
        tenant.tenant_id,
        note_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Credit note updated successfully")


@router.delete("/{note_id}", response_model=ApiResponse[CreditNoteResponse])
async def delete_credit_note(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: CreditNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CREDIT_NOTE_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[CreditNoteResponse]:
    row = await service.delete(
        tenant.tenant_id,
        note_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Credit note deleted successfully")


@router.post("/{note_id}/post", response_model=ApiResponse[CreditNoteResponse])
async def post_credit_note(
    note_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: CreditNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CREDIT_NOTE_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[CreditNoteResponse]:
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        note_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Credit note posted successfully")


@router.post("/{note_id}/cancel", response_model=ApiResponse[CreditNoteResponse])
async def cancel_credit_note(
    note_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: CreditNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CREDIT_NOTE_CANCEL))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[CreditNoteCancelRequest | None, Body()] = None,
) -> ApiResponse[CreditNoteResponse]:
    body_payload = payload or CreditNoteCancelRequest()
    body = await request.body()
    row = await service.cancel(
        tenant.tenant_id,
        note_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=body_payload.version
        ),
        reason=body_payload.reason,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Credit note cancelled")


@router.get("/{note_id}/journal", response_model=ApiResponse[JournalEntryResponse])
async def get_credit_note_journal(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: CreditNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CREDIT_NOTE_READ))],
) -> ApiResponse[JournalEntryResponse]:
    return ApiResponse(data=await service.journal(tenant.tenant_id, note_id))
