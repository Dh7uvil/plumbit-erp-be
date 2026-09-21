"""Campaign routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import CAMPAIGN_CREATE, CAMPAIGN_DELETE, CAMPAIGN_READ, CAMPAIGN_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.crm.campaigns.dependencies import CampaignServiceDependency
from app.crm.campaigns.schemas import (
    CampaignCreate,
    CampaignFilter,
    CampaignMemberCreate,
    CampaignMemberResponse,
    CampaignMemberUpdate,
    CampaignResponse,
    CampaignRoiResponse,
    CampaignUpdate,
)

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


@router.get("", response_model=ApiResponse[list[CampaignResponse]])
async def list_campaigns(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CampaignServiceDependency,
    filters: Annotated[CampaignFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CAMPAIGN_READ))],
) -> ApiResponse[list[CampaignResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        campaign_type=filters.campaign_type.value if filters.campaign_type else None,
        owner_id=filters.owner_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[CampaignResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_campaign(
    payload: CampaignCreate,
    tenant: TenantContextDependency,
    service: CampaignServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CAMPAIGN_CREATE))],
) -> ApiResponse[CampaignResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Campaign created successfully")


@router.get("/{campaign_id}", response_model=ApiResponse[CampaignResponse])
async def get_campaign(
    campaign_id: UUID,
    tenant: TenantContextDependency,
    service: CampaignServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CAMPAIGN_READ))],
) -> ApiResponse[CampaignResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, campaign_id))


@router.patch("/{campaign_id}", response_model=ApiResponse[CampaignResponse])
async def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdate,
    tenant: TenantContextDependency,
    service: CampaignServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CAMPAIGN_UPDATE))],
) -> ApiResponse[CampaignResponse]:
    row = await service.update(tenant.tenant_id, campaign_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Campaign updated successfully")


@router.delete("/{campaign_id}", response_model=ApiResponse[CampaignResponse])
async def delete_campaign(
    campaign_id: UUID,
    tenant: TenantContextDependency,
    service: CampaignServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CAMPAIGN_DELETE))],
) -> ApiResponse[CampaignResponse]:
    row = await service.delete(tenant.tenant_id, campaign_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Campaign deleted successfully")


@router.get("/{campaign_id}/members", response_model=ApiResponse[list[CampaignMemberResponse]])
async def list_campaign_members(
    campaign_id: UUID,
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CampaignServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CAMPAIGN_READ))],
) -> ApiResponse[list[CampaignMemberResponse]]:
    rows, total = await service.list_members(tenant.tenant_id, campaign_id, page=page)
    return paginated_response(rows, params=page, total=total)


@router.post(
    "/{campaign_id}/members",
    response_model=ApiResponse[CampaignMemberResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_campaign_member(
    campaign_id: UUID,
    payload: CampaignMemberCreate,
    tenant: TenantContextDependency,
    service: CampaignServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CAMPAIGN_UPDATE))],
) -> ApiResponse[CampaignMemberResponse]:
    row = await service.add_member(
        tenant.tenant_id, campaign_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Campaign member added successfully")


@router.patch(
    "/{campaign_id}/members/{member_id}",
    response_model=ApiResponse[CampaignMemberResponse],
)
async def update_campaign_member(
    campaign_id: UUID,
    member_id: UUID,
    payload: CampaignMemberUpdate,
    tenant: TenantContextDependency,
    service: CampaignServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CAMPAIGN_UPDATE))],
) -> ApiResponse[CampaignMemberResponse]:
    row = await service.update_member(
        tenant.tenant_id,
        campaign_id,
        member_id,
        payload,
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Campaign member updated successfully")


@router.delete(
    "/{campaign_id}/members/{member_id}",
    response_model=ApiResponse[CampaignMemberResponse],
)
async def remove_campaign_member(
    campaign_id: UUID,
    member_id: UUID,
    tenant: TenantContextDependency,
    service: CampaignServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CAMPAIGN_UPDATE))],
) -> ApiResponse[CampaignMemberResponse]:
    row = await service.remove_member(
        tenant.tenant_id, campaign_id, member_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Campaign member removed successfully")


@router.get("/{campaign_id}/roi", response_model=ApiResponse[CampaignRoiResponse])
async def get_campaign_roi(
    campaign_id: UUID,
    tenant: TenantContextDependency,
    service: CampaignServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CAMPAIGN_READ))],
) -> ApiResponse[CampaignRoiResponse]:
    return ApiResponse(data=await service.roi(tenant.tenant_id, campaign_id))
