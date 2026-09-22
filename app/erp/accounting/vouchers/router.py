"""Cash/bank voucher routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from app.auth.catalog import (
    VOUCHER_CANCEL,
    VOUCHER_CREATE,
    VOUCHER_DELETE,
    VOUCHER_POST,
    VOUCHER_READ,
    VOUCHER_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.accounting.open_items.schemas import PaymentAllocationRecordResponse
from app.erp.accounting.vouchers.dependencies import VoucherServiceDependency
from app.erp.accounting.vouchers.schemas import (
    VoucherCancelRequest,
    VoucherCreate,
    VoucherFilter,
    VoucherResponse,
    VoucherUpdate,
)

router = APIRouter(prefix="/vouchers", tags=["Vouchers"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[VoucherResponse]])
async def list_vouchers(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: VoucherServiceDependency,
    filters: Annotated[VoucherFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(VOUCHER_READ))],
) -> ApiResponse[list[VoucherResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        voucher_type=filters.voucher_type.value if filters.voucher_type else None,
        party_id=filters.party_id,
        currency_id=filters.currency_id,
        payment_method=filters.payment_method.value if filters.payment_method else None,
        voucher_date_from=filters.voucher_date_from,
        voucher_date_to=filters.voucher_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[VoucherResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_voucher(
    payload: VoucherCreate,
    tenant: TenantContextDependency,
    service: VoucherServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(VOUCHER_CREATE))],
) -> ApiResponse[VoucherResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Voucher created successfully")


@router.get("/{voucher_id}", response_model=ApiResponse[VoucherResponse])
async def get_voucher(
    voucher_id: UUID,
    tenant: TenantContextDependency,
    service: VoucherServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(VOUCHER_READ))],
) -> ApiResponse[VoucherResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, voucher_id))


@router.patch("/{voucher_id}", response_model=ApiResponse[VoucherResponse])
async def update_voucher(
    voucher_id: UUID,
    payload: VoucherUpdate,
    tenant: TenantContextDependency,
    service: VoucherServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(VOUCHER_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[VoucherResponse]:
    version = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.update(
        tenant.tenant_id,
        voucher_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=version,
    )
    return ApiResponse(data=row, message="Voucher updated successfully")


@router.delete("/{voucher_id}", response_model=ApiResponse[VoucherResponse])
async def delete_voucher(
    voucher_id: UUID,
    tenant: TenantContextDependency,
    service: VoucherServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(VOUCHER_DELETE))],
    if_match: IfMatch = None,
    version: int | None = None,
) -> ApiResponse[VoucherResponse]:
    expected = require_document_version(if_match=if_match, body_version=version)
    row = await service.delete(
        tenant.tenant_id,
        voucher_id,
        actor_user_id=tenant.user_id,
        expected_version=expected,
    )
    return ApiResponse(data=row, message="Voucher deleted successfully")


@router.post("/{voucher_id}/post", response_model=ApiResponse[VoucherResponse])
async def post_voucher(
    request: Request,
    voucher_id: UUID,
    tenant: TenantContextDependency,
    service: VoucherServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(VOUCHER_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[VoucherResponse]:
    key = require_idempotency_key(idempotency_key)
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        voucher_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=key,
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Voucher posted successfully")


@router.post("/{voucher_id}/cancel", response_model=ApiResponse[VoucherResponse])
async def cancel_voucher(
    request: Request,
    voucher_id: UUID,
    payload: VoucherCancelRequest,
    tenant: TenantContextDependency,
    service: VoucherServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(VOUCHER_CANCEL))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[VoucherResponse]:
    expected = require_document_version(if_match=if_match, body_version=payload.version)
    key = require_idempotency_key(idempotency_key)
    body = await request.body()
    row = await service.cancel(
        tenant.tenant_id,
        voucher_id,
        actor_user_id=tenant.user_id,
        expected_version=expected,
        reason=payload.reason,
        idempotency_key=key,
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Voucher cancelled successfully")


@router.get(
    "/{voucher_id}/allocations",
    response_model=ApiResponse[list[PaymentAllocationRecordResponse]],
)
async def list_voucher_allocations(
    voucher_id: UUID,
    tenant: TenantContextDependency,
    service: VoucherServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(VOUCHER_READ))],
) -> ApiResponse[list[PaymentAllocationRecordResponse]]:
    rows = await service.list_allocations(tenant.tenant_id, voucher_id)
    return ApiResponse(data=rows)
