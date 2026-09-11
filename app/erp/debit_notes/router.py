"""Debit note routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Request, status

from app.auth.catalog import (
    DEBIT_NOTE_CANCEL,
    DEBIT_NOTE_CREATE,
    DEBIT_NOTE_DELETE,
    DEBIT_NOTE_POST,
    DEBIT_NOTE_READ,
    DEBIT_NOTE_UPDATE,
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
from app.erp.debit_notes.dependencies import DebitNoteServiceDependency
from app.erp.debit_notes.schemas import (
    DebitNoteCancelRequest,
    DebitNoteCreate,
    DebitNoteCreateFromPurchaseInvoice,
    DebitNoteCreateFromPurchaseReturn,
    DebitNoteFilter,
    DebitNoteResponse,
    DebitNoteUpdate,
)

router = APIRouter(prefix="/debit-notes", tags=["Debit Notes"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[DebitNoteResponse]])
async def list_debit_notes(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: DebitNoteServiceDependency,
    filters: Annotated[DebitNoteFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(DEBIT_NOTE_READ))],
) -> ApiResponse[list[DebitNoteResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        supplier_id=filters.supplier_id,
        purchase_invoice_id=filters.purchase_invoice_id,
        purchase_return_id=filters.purchase_return_id,
        currency_id=filters.currency_id,
        debit_note_date_from=filters.debit_note_date_from,
        debit_note_date_to=filters.debit_note_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "/from-purchase-invoice",
    response_model=ApiResponse[DebitNoteResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_debit_note_from_purchase_invoice(
    payload: DebitNoteCreateFromPurchaseInvoice,
    request: Request,
    tenant: TenantContextDependency,
    service: DebitNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEBIT_NOTE_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[DebitNoteResponse]:
    body = await request.body()
    row = await service.create_from_purchase_invoice(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Debit note created from purchase invoice")


@router.post(
    "/from-purchase-return",
    response_model=ApiResponse[DebitNoteResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_debit_note_from_purchase_return(
    payload: DebitNoteCreateFromPurchaseReturn,
    request: Request,
    tenant: TenantContextDependency,
    service: DebitNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEBIT_NOTE_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[DebitNoteResponse]:
    body = await request.body()
    row = await service.create_from_purchase_return(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Debit note created from purchase return")


@router.post(
    "",
    response_model=ApiResponse[DebitNoteResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_debit_note(
    payload: DebitNoteCreate,
    tenant: TenantContextDependency,
    service: DebitNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEBIT_NOTE_CREATE))],
) -> ApiResponse[DebitNoteResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Debit note created successfully")


@router.get("/{note_id}", response_model=ApiResponse[DebitNoteResponse])
async def get_debit_note(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: DebitNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEBIT_NOTE_READ))],
) -> ApiResponse[DebitNoteResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, note_id))


@router.get("/{note_id}/print", response_model=ApiResponse[PrintDocumentResponse])
async def print_debit_note(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: DebitNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEBIT_NOTE_READ))],
    template_family: Annotated[str, Query()] = "uae",
) -> ApiResponse[PrintDocumentResponse]:
    return ApiResponse(
        data=await service.print_document(
            tenant.tenant_id, note_id, template_family=template_family
        )
    )


@router.patch("/{note_id}", response_model=ApiResponse[DebitNoteResponse])
async def update_debit_note(
    note_id: UUID,
    payload: DebitNoteUpdate,
    tenant: TenantContextDependency,
    service: DebitNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEBIT_NOTE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[DebitNoteResponse]:
    row = await service.update(
        tenant.tenant_id,
        note_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Debit note updated successfully")


@router.delete("/{note_id}", response_model=ApiResponse[DebitNoteResponse])
async def delete_debit_note(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: DebitNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEBIT_NOTE_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[DebitNoteResponse]:
    row = await service.delete(
        tenant.tenant_id,
        note_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Debit note deleted successfully")


@router.post("/{note_id}/post", response_model=ApiResponse[DebitNoteResponse])
async def post_debit_note(
    note_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: DebitNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEBIT_NOTE_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[DebitNoteResponse]:
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
    return ApiResponse(data=row, message="Debit note posted successfully")


@router.post("/{note_id}/cancel", response_model=ApiResponse[DebitNoteResponse])
async def cancel_debit_note(
    note_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: DebitNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEBIT_NOTE_CANCEL))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[DebitNoteCancelRequest | None, Body()] = None,
) -> ApiResponse[DebitNoteResponse]:
    body_payload = payload or DebitNoteCancelRequest()
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
    return ApiResponse(data=row, message="Debit note cancelled")


@router.get("/{note_id}/journal", response_model=ApiResponse[JournalEntryResponse])
async def get_debit_note_journal(
    note_id: UUID,
    tenant: TenantContextDependency,
    service: DebitNoteServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DEBIT_NOTE_READ))],
) -> ApiResponse[JournalEntryResponse]:
    return ApiResponse(data=await service.journal(tenant.tenant_id, note_id))
