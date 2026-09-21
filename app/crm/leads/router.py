"""Lead routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from app.auth.catalog import (
    LEAD_ASSIGN,
    LEAD_CONVERT,
    LEAD_CREATE,
    LEAD_DELETE,
    LEAD_READ,
    LEAD_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.crm.leads.dependencies import LeadServiceDependency
from app.crm.leads.schemas import (
    LeadAssign,
    LeadConvert,
    LeadConvertResponse,
    LeadCreate,
    LeadFilter,
    LeadResponse,
    LeadStatusChange,
    LeadUpdate,
)

router = APIRouter(prefix="/leads", tags=["Leads"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[LeadResponse]])
async def list_leads(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: LeadServiceDependency,
    filters: Annotated[LeadFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_READ))],
) -> ApiResponse[list[LeadResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        source_id=filters.source_id,
        owner_id=filters.owner_id,
        rating=filters.rating,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[LeadResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_lead(
    payload: LeadCreate,
    tenant: TenantContextDependency,
    service: LeadServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_CREATE))],
) -> ApiResponse[LeadResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Lead created successfully")


@router.get("/{lead_id}", response_model=ApiResponse[LeadResponse])
async def get_lead(
    lead_id: UUID,
    tenant: TenantContextDependency,
    service: LeadServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_READ))],
) -> ApiResponse[LeadResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, lead_id))


@router.patch("/{lead_id}", response_model=ApiResponse[LeadResponse])
async def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    tenant: TenantContextDependency,
    service: LeadServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[LeadResponse]:
    row = await service.update(
        tenant.tenant_id,
        lead_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Lead updated successfully")


@router.delete("/{lead_id}", response_model=ApiResponse[LeadResponse])
async def delete_lead(
    lead_id: UUID,
    tenant: TenantContextDependency,
    service: LeadServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_DELETE))],
) -> ApiResponse[LeadResponse]:
    row = await service.delete(tenant.tenant_id, lead_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Lead deleted successfully")


@router.post("/{lead_id}/assign", response_model=ApiResponse[LeadResponse])
async def assign_lead(
    lead_id: UUID,
    payload: LeadAssign,
    tenant: TenantContextDependency,
    service: LeadServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_ASSIGN))],
    if_match: IfMatch = None,
) -> ApiResponse[LeadResponse]:
    row = await service.assign(
        tenant.tenant_id,
        lead_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Lead assigned successfully")


@router.post("/{lead_id}/status", response_model=ApiResponse[LeadResponse])
async def change_lead_status(
    lead_id: UUID,
    payload: LeadStatusChange,
    tenant: TenantContextDependency,
    service: LeadServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[LeadResponse]:
    row = await service.change_status(
        tenant.tenant_id,
        lead_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Lead status updated successfully")


@router.post(
    "/{lead_id}/convert",
    response_model=ApiResponse[LeadConvertResponse],
    status_code=status.HTTP_201_CREATED,
)
async def convert_lead(
    lead_id: UUID,
    request: Request,
    payload: LeadConvert,
    tenant: TenantContextDependency,
    service: LeadServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_CONVERT))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[LeadConvertResponse]:
    body = await request.body()
    row = await service.convert(
        tenant.tenant_id,
        lead_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Lead converted successfully")
