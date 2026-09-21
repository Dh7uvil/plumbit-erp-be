"""Opportunity routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from app.auth.catalog import (
    OPPORTUNITY_CREATE,
    OPPORTUNITY_DELETE,
    OPPORTUNITY_READ,
    OPPORTUNITY_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.crm.opportunities.dependencies import OpportunityServiceDependency
from app.crm.opportunities.schemas import (
    OpportunityCreate,
    OpportunityFilter,
    OpportunityLose,
    OpportunityResponse,
    OpportunityStageChange,
    OpportunityUpdate,
    OpportunityVersionedAction,
)

router = APIRouter(prefix="/opportunities", tags=["Opportunities"])

IfMatch = Annotated[str | None, Header()]


@router.get("", response_model=ApiResponse[list[OpportunityResponse]])
async def list_opportunities(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: OpportunityServiceDependency,
    filters: Annotated[OpportunityFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(OPPORTUNITY_READ))],
) -> ApiResponse[list[OpportunityResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        pipeline_id=filters.pipeline_id,
        stage_id=filters.stage_id,
        owner_id=filters.owner_id,
        customer_id=filters.customer_id,
        source_id=filters.source_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[OpportunityResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_opportunity(
    payload: OpportunityCreate,
    tenant: TenantContextDependency,
    service: OpportunityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPPORTUNITY_CREATE))],
) -> ApiResponse[OpportunityResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Opportunity created successfully")


@router.get("/{opportunity_id}", response_model=ApiResponse[OpportunityResponse])
async def get_opportunity(
    opportunity_id: UUID,
    tenant: TenantContextDependency,
    service: OpportunityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPPORTUNITY_READ))],
) -> ApiResponse[OpportunityResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, opportunity_id))


@router.patch("/{opportunity_id}", response_model=ApiResponse[OpportunityResponse])
async def update_opportunity(
    opportunity_id: UUID,
    payload: OpportunityUpdate,
    tenant: TenantContextDependency,
    service: OpportunityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPPORTUNITY_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[OpportunityResponse]:
    row = await service.update(
        tenant.tenant_id,
        opportunity_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Opportunity updated successfully")


@router.delete("/{opportunity_id}", response_model=ApiResponse[OpportunityResponse])
async def delete_opportunity(
    opportunity_id: UUID,
    tenant: TenantContextDependency,
    service: OpportunityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPPORTUNITY_DELETE))],
) -> ApiResponse[OpportunityResponse]:
    row = await service.delete(tenant.tenant_id, opportunity_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Opportunity deleted successfully")


@router.post("/{opportunity_id}/stage", response_model=ApiResponse[OpportunityResponse])
async def change_opportunity_stage(
    opportunity_id: UUID,
    payload: OpportunityStageChange,
    tenant: TenantContextDependency,
    service: OpportunityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPPORTUNITY_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[OpportunityResponse]:
    row = await service.change_stage(
        tenant.tenant_id,
        opportunity_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Opportunity stage updated successfully")


@router.post("/{opportunity_id}/win", response_model=ApiResponse[OpportunityResponse])
async def win_opportunity(
    opportunity_id: UUID,
    payload: OpportunityVersionedAction,
    tenant: TenantContextDependency,
    service: OpportunityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPPORTUNITY_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[OpportunityResponse]:
    row = await service.win(
        tenant.tenant_id,
        opportunity_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Opportunity marked as won")


@router.post("/{opportunity_id}/lose", response_model=ApiResponse[OpportunityResponse])
async def lose_opportunity(
    opportunity_id: UUID,
    payload: OpportunityLose,
    tenant: TenantContextDependency,
    service: OpportunityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPPORTUNITY_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[OpportunityResponse]:
    row = await service.lose(
        tenant.tenant_id,
        opportunity_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Opportunity marked as lost")


@router.post("/{opportunity_id}/reopen", response_model=ApiResponse[OpportunityResponse])
async def reopen_opportunity(
    opportunity_id: UUID,
    payload: OpportunityVersionedAction,
    tenant: TenantContextDependency,
    service: OpportunityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OPPORTUNITY_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[OpportunityResponse]:
    row = await service.reopen(
        tenant.tenant_id,
        opportunity_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Opportunity reopened successfully")
