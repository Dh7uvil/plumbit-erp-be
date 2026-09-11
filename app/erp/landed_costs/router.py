"""Landed cost routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    LANDED_COST_CANCEL,
    LANDED_COST_CREATE,
    LANDED_COST_POST,
    LANDED_COST_READ,
    LANDED_COST_UPDATE,
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
from app.erp.landed_costs.dependencies import LandedCostServiceDependency
from app.erp.landed_costs.schemas import (
    LandedCostCancelRequest,
    LandedCostCreate,
    LandedCostCreateFromBills,
    LandedCostFilter,
    LandedCostResponse,
    LandedCostUpdate,
)

router = APIRouter(prefix="/landed-costs", tags=["Landed Costs"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[LandedCostResponse]])
async def list_landed_costs(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: LandedCostServiceDependency,
    filters: Annotated[LandedCostFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(LANDED_COST_READ))],
) -> ApiResponse[list[LandedCostResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        shipment_id=filters.shipment_id,
        goods_receipt_id=filters.goods_receipt_id,
        purchase_invoice_id=filters.purchase_invoice_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "/from-bills",
    response_model=ApiResponse[LandedCostResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_landed_cost_from_bills(
    payload: LandedCostCreateFromBills,
    request: Request,
    tenant: TenantContextDependency,
    service: LandedCostServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LANDED_COST_CREATE))],
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[LandedCostResponse]:
    body = await request.body()
    row = await service.create_from_bills(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Landed cost created from bills")


@router.post(
    "",
    response_model=ApiResponse[LandedCostResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_landed_cost(
    payload: LandedCostCreate,
    tenant: TenantContextDependency,
    service: LandedCostServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LANDED_COST_CREATE))],
) -> ApiResponse[LandedCostResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Landed cost created successfully")


@router.get("/{landed_cost_id}", response_model=ApiResponse[LandedCostResponse])
async def get_landed_cost(
    landed_cost_id: UUID,
    tenant: TenantContextDependency,
    service: LandedCostServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LANDED_COST_READ))],
) -> ApiResponse[LandedCostResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, landed_cost_id))


@router.patch("/{landed_cost_id}", response_model=ApiResponse[LandedCostResponse])
async def update_landed_cost(
    landed_cost_id: UUID,
    payload: LandedCostUpdate,
    tenant: TenantContextDependency,
    service: LandedCostServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LANDED_COST_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[LandedCostResponse]:
    row = await service.update(
        tenant.tenant_id,
        landed_cost_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Landed cost updated successfully")


@router.delete("/{landed_cost_id}", response_model=ApiResponse[LandedCostResponse])
async def delete_landed_cost(
    landed_cost_id: UUID,
    tenant: TenantContextDependency,
    service: LandedCostServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LANDED_COST_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[LandedCostResponse]:
    row = await service.delete(
        tenant.tenant_id,
        landed_cost_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Landed cost deleted successfully")


@router.post("/{landed_cost_id}/post", response_model=ApiResponse[LandedCostResponse])
async def post_landed_cost(
    landed_cost_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: LandedCostServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LANDED_COST_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[LandedCostResponse]:
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        landed_cost_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Landed cost posted successfully")


@router.post("/{landed_cost_id}/cancel", response_model=ApiResponse[LandedCostResponse])
async def cancel_landed_cost(
    landed_cost_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: LandedCostServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LANDED_COST_CANCEL))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[LandedCostCancelRequest | None, Body()] = None,
) -> ApiResponse[LandedCostResponse]:
    body_payload = payload or LandedCostCancelRequest()
    body = await request.body()
    row = await service.cancel(
        tenant.tenant_id,
        landed_cost_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=body_payload.version
        ),
        reason=body_payload.reason,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Landed cost cancelled")


@router.get("/{landed_cost_id}/journal", response_model=ApiResponse[JournalEntryResponse])
async def get_landed_cost_journal(
    landed_cost_id: UUID,
    tenant: TenantContextDependency,
    service: LandedCostServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LANDED_COST_READ))],
) -> ApiResponse[JournalEntryResponse]:
    return ApiResponse(data=await service.journal(tenant.tenant_id, landed_cost_id))
