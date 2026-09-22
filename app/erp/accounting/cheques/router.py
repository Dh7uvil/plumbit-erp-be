"""Cheque register routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from app.auth.catalog import (
    CHEQUE_BOUNCE,
    CHEQUE_CANCEL,
    CHEQUE_CLEAR,
    CHEQUE_CREATE,
    CHEQUE_DELETE,
    CHEQUE_DEPOSIT,
    CHEQUE_ISSUE,
    CHEQUE_READ,
    CHEQUE_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.accounting.cheques.dependencies import ChequeServiceDependency
from app.erp.accounting.cheques.schemas import (
    ChequeBounceRequest,
    ChequeCancelRequest,
    ChequeCreate,
    ChequeFilter,
    ChequeResponse,
    ChequeUpdate,
)

router = APIRouter(prefix="/cheques", tags=["Cheques"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[ChequeResponse]])
async def list_cheques(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: ChequeServiceDependency,
    filters: Annotated[ChequeFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CHEQUE_READ))],
) -> ApiResponse[list[ChequeResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        direction=filters.direction.value if filters.direction else None,
        bank_account_id=filters.bank_account_id,
        party_id=filters.party_id,
        due_date_from=filters.due_date_from,
        due_date_to=filters.due_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[ChequeResponse], status_code=status.HTTP_201_CREATED)
async def create_cheque(
    payload: ChequeCreate,
    tenant: TenantContextDependency,
    service: ChequeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHEQUE_CREATE))],
) -> ApiResponse[ChequeResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Cheque created successfully")


@router.get("/{cheque_id}", response_model=ApiResponse[ChequeResponse])
async def get_cheque(
    cheque_id: UUID,
    tenant: TenantContextDependency,
    service: ChequeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHEQUE_READ))],
) -> ApiResponse[ChequeResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, cheque_id))


@router.patch("/{cheque_id}", response_model=ApiResponse[ChequeResponse])
async def update_cheque(
    cheque_id: UUID,
    payload: ChequeUpdate,
    tenant: TenantContextDependency,
    service: ChequeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHEQUE_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[ChequeResponse]:
    version = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.update(
        tenant.tenant_id,
        cheque_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=version,
    )
    return ApiResponse(data=row, message="Cheque updated successfully")


@router.delete("/{cheque_id}", response_model=ApiResponse[ChequeResponse])
async def delete_cheque(
    cheque_id: UUID,
    tenant: TenantContextDependency,
    service: ChequeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHEQUE_DELETE))],
    if_match: IfMatch = None,
    version: int | None = None,
) -> ApiResponse[ChequeResponse]:
    expected = require_document_version(if_match=if_match, body_version=version)
    row = await service.delete(
        tenant.tenant_id,
        cheque_id,
        actor_user_id=tenant.user_id,
        expected_version=expected,
    )
    return ApiResponse(data=row, message="Cheque deleted successfully")


@router.post("/{cheque_id}/issue", response_model=ApiResponse[ChequeResponse])
async def issue_cheque(
    request: Request,
    cheque_id: UUID,
    tenant: TenantContextDependency,
    service: ChequeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHEQUE_ISSUE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[ChequeResponse]:
    key = require_idempotency_key(idempotency_key)
    body = await request.body()
    row = await service.issue(
        tenant.tenant_id,
        cheque_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=key,
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Cheque issued successfully")


@router.post("/{cheque_id}/deposit", response_model=ApiResponse[ChequeResponse])
async def deposit_cheque(
    cheque_id: UUID,
    tenant: TenantContextDependency,
    service: ChequeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHEQUE_DEPOSIT))],
    if_match: IfMatch = None,
    version: int | None = None,
) -> ApiResponse[ChequeResponse]:
    expected = require_document_version(if_match=if_match, body_version=version)
    row = await service.deposit(
        tenant.tenant_id,
        cheque_id,
        actor_user_id=tenant.user_id,
        expected_version=expected,
    )
    return ApiResponse(data=row, message="Cheque deposited successfully")


@router.post("/{cheque_id}/clear", response_model=ApiResponse[ChequeResponse])
async def clear_cheque(
    request: Request,
    cheque_id: UUID,
    tenant: TenantContextDependency,
    service: ChequeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHEQUE_CLEAR))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[ChequeResponse]:
    key = require_idempotency_key(idempotency_key)
    body = await request.body()
    row = await service.clear(
        tenant.tenant_id,
        cheque_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=key,
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Cheque cleared successfully")


@router.post("/{cheque_id}/bounce", response_model=ApiResponse[ChequeResponse])
async def bounce_cheque(
    request: Request,
    cheque_id: UUID,
    payload: ChequeBounceRequest,
    tenant: TenantContextDependency,
    service: ChequeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHEQUE_BOUNCE))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[ChequeResponse]:
    expected = require_document_version(if_match=if_match, body_version=payload.version)
    key = require_idempotency_key(idempotency_key)
    body = await request.body()
    row = await service.bounce(
        tenant.tenant_id,
        cheque_id,
        actor_user_id=tenant.user_id,
        expected_version=expected,
        reason=payload.reason,
        idempotency_key=key,
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Cheque bounced successfully")


@router.post("/{cheque_id}/cancel", response_model=ApiResponse[ChequeResponse])
async def cancel_cheque(
    cheque_id: UUID,
    payload: ChequeCancelRequest,
    tenant: TenantContextDependency,
    service: ChequeServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CHEQUE_CANCEL))],
    if_match: IfMatch = None,
) -> ApiResponse[ChequeResponse]:
    expected = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.cancel(
        tenant.tenant_id,
        cheque_id,
        actor_user_id=tenant.user_id,
        expected_version=expected,
        reason=payload.reason,
    )
    return ApiResponse(data=row, message="Cheque cancelled successfully")
