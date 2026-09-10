"""Journal entry routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    JOURNAL_ENTRY_CREATE,
    JOURNAL_ENTRY_DELETE,
    JOURNAL_ENTRY_POST,
    JOURNAL_ENTRY_READ,
    JOURNAL_ENTRY_REVERSE,
    JOURNAL_ENTRY_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.accounting.ledger.dependencies import JournalEntryServiceDependency
from app.erp.accounting.ledger.schemas import (
    JournalEntryCancelRequest,
    JournalEntryCreate,
    JournalEntryFilter,
    JournalEntryResponse,
    JournalEntryReverseRequest,
    JournalEntryUpdate,
)

router = APIRouter(prefix="/journals", tags=["Journals"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[JournalEntryResponse]])
async def list_journals(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: JournalEntryServiceDependency,
    filters: Annotated[JournalEntryFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(JOURNAL_ENTRY_READ))],
) -> ApiResponse[list[JournalEntryResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        journal_type=filters.journal_type.value if filters.journal_type else None,
        account_id=filters.account_id,
        party_id=filters.party_id,
        branch_id=filters.branch_id,
        entry_date_from=filters.entry_date_from,
        entry_date_to=filters.entry_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[JournalEntryResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_journal(
    payload: JournalEntryCreate,
    tenant: TenantContextDependency,
    service: JournalEntryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOURNAL_ENTRY_CREATE))],
) -> ApiResponse[JournalEntryResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Journal entry created successfully")


@router.get("/{journal_id}", response_model=ApiResponse[JournalEntryResponse])
async def get_journal(
    journal_id: UUID,
    tenant: TenantContextDependency,
    service: JournalEntryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOURNAL_ENTRY_READ))],
) -> ApiResponse[JournalEntryResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, journal_id))


@router.patch("/{journal_id}", response_model=ApiResponse[JournalEntryResponse])
async def update_journal(
    journal_id: UUID,
    payload: JournalEntryUpdate,
    tenant: TenantContextDependency,
    service: JournalEntryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOURNAL_ENTRY_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[JournalEntryResponse]:
    row = await service.update(
        tenant.tenant_id,
        journal_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Journal entry updated successfully")


@router.delete("/{journal_id}", response_model=ApiResponse[JournalEntryResponse])
async def delete_journal(
    journal_id: UUID,
    tenant: TenantContextDependency,
    service: JournalEntryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOURNAL_ENTRY_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[JournalEntryResponse]:
    row = await service.delete(
        tenant.tenant_id,
        journal_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Journal entry deleted successfully")


@router.post("/{journal_id}/post", response_model=ApiResponse[JournalEntryResponse])
async def post_journal(
    journal_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: JournalEntryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOURNAL_ENTRY_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[JournalEntryResponse]:
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        journal_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Journal entry posted successfully")


@router.post("/{journal_id}/cancel", response_model=ApiResponse[JournalEntryResponse])
async def cancel_journal(
    journal_id: UUID,
    tenant: TenantContextDependency,
    service: JournalEntryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOURNAL_ENTRY_UPDATE))],
    if_match: IfMatch = None,
    payload: Annotated[JournalEntryCancelRequest | None, Body()] = None,
) -> ApiResponse[JournalEntryResponse]:
    body = payload or JournalEntryCancelRequest()
    row = await service.cancel(
        tenant.tenant_id,
        journal_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=body.version),
        reason=body.reason,
    )
    return ApiResponse(data=row, message="Journal entry cancelled")


@router.post("/{journal_id}/reverse", response_model=ApiResponse[JournalEntryResponse])
async def reverse_journal(
    journal_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: JournalEntryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(JOURNAL_ENTRY_REVERSE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[JournalEntryReverseRequest | None, Body()] = None,
) -> ApiResponse[JournalEntryResponse]:
    body = payload or JournalEntryReverseRequest()
    raw = await request.body()
    row = await service.reverse(
        tenant.tenant_id,
        journal_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=body.version
        ),
        reversal_date=body.reversal_date,
        reason=body.reason,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=raw),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Journal entry reversed")
