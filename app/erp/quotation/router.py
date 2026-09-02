"""Quotation routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, status

from app.auth.catalog import (
    QUOTATION_APPROVE,
    QUOTATION_CREATE,
    QUOTATION_DELETE,
    QUOTATION_READ,
    QUOTATION_SEND,
    QUOTATION_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.quotation.dependencies import QuotationServiceDependency
from app.erp.quotation.schemas import (
    QuotationComposeDefaults,
    QuotationCreate,
    QuotationFilter,
    QuotationRejectRequest,
    QuotationResponse,
    QuotationUpdate,
)

router = APIRouter(prefix="/quotations", tags=["Quotations"])

IfMatch = Annotated[str | None, Header()]


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


@router.post("/{quotation_id}/clone", response_model=ApiResponse[QuotationResponse])
async def clone_quotation(
    quotation_id: UUID,
    tenant: TenantContextDependency,
    service: QuotationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(QUOTATION_CREATE))],
) -> ApiResponse[QuotationResponse]:
    row = await service.clone(tenant.tenant_id, quotation_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Quotation cloned as a new draft")
