"""Lead source routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    LEAD_SOURCE_CREATE,
    LEAD_SOURCE_DELETE,
    LEAD_SOURCE_READ,
    LEAD_SOURCE_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.crm.lead_sources.dependencies import LeadSourceServiceDependency
from app.crm.lead_sources.schemas import (
    LeadSourceCreate,
    LeadSourceFilter,
    LeadSourceResponse,
    LeadSourceUpdate,
)

router = APIRouter(prefix="/lead-sources", tags=["Lead Sources"])


@router.get("", response_model=ApiResponse[list[LeadSourceResponse]])
async def list_lead_sources(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: LeadSourceServiceDependency,
    filters: Annotated[LeadSourceFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_SOURCE_READ))],
) -> ApiResponse[list[LeadSourceResponse]]:
    rows, total = await service.list(
        tenant.tenant_id, page=page, common_filter=filters, is_active=filters.is_active
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[LeadSourceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_lead_source(
    payload: LeadSourceCreate,
    tenant: TenantContextDependency,
    service: LeadSourceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_SOURCE_CREATE))],
) -> ApiResponse[LeadSourceResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Lead source created successfully")


@router.get("/{lead_source_id}", response_model=ApiResponse[LeadSourceResponse])
async def get_lead_source(
    lead_source_id: UUID,
    tenant: TenantContextDependency,
    service: LeadSourceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_SOURCE_READ))],
) -> ApiResponse[LeadSourceResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, lead_source_id))


@router.patch("/{lead_source_id}", response_model=ApiResponse[LeadSourceResponse])
async def update_lead_source(
    lead_source_id: UUID,
    payload: LeadSourceUpdate,
    tenant: TenantContextDependency,
    service: LeadSourceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_SOURCE_UPDATE))],
) -> ApiResponse[LeadSourceResponse]:
    row = await service.update(
        tenant.tenant_id, lead_source_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Lead source updated successfully")


@router.delete("/{lead_source_id}", response_model=ApiResponse[LeadSourceResponse])
async def delete_lead_source(
    lead_source_id: UUID,
    tenant: TenantContextDependency,
    service: LeadSourceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LEAD_SOURCE_DELETE))],
) -> ApiResponse[LeadSourceResponse]:
    row = await service.delete(tenant.tenant_id, lead_source_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Lead source deleted successfully")
