"""Activity routes.

`/activities` is the user-scheduled task, call and meeting resource.
`/activity` (in `app/common/activity/`) is the existing audit-derived per-record
feed. They are deliberately separate and neither replaces the other.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, status

from app.auth.catalog import ACTIVITY_CREATE, ACTIVITY_DELETE, ACTIVITY_READ, ACTIVITY_UPDATE
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.crm.activities.dependencies import ActivityServiceDependency
from app.crm.activities.schemas import (
    ActivityComplete,
    ActivityCreate,
    ActivityFilter,
    ActivityResponse,
    ActivityUpdate,
)

router = APIRouter(prefix="/activities", tags=["Activities"])


@router.get("", response_model=ApiResponse[list[ActivityResponse]])
async def list_activities(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: ActivityServiceDependency,
    filters: Annotated[ActivityFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(ACTIVITY_READ))],
) -> ApiResponse[list[ActivityResponse]]:
    owner_id = tenant.user_id if filters.mine else filters.owner_id
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        related_entity_type=filters.related_entity_type.value
        if filters.related_entity_type
        else None,
        related_entity_id=filters.related_entity_id,
        owner_id=owner_id,
        status=filters.status.value if filters.status else None,
        activity_type=filters.activity_type.value if filters.activity_type else None,
        overdue=filters.overdue,
        due_from=filters.due_from,
        due_to=filters.due_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[ActivityResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_activity(
    payload: ActivityCreate,
    tenant: TenantContextDependency,
    service: ActivityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACTIVITY_CREATE))],
) -> ApiResponse[ActivityResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Activity created successfully")


@router.get("/{activity_id}", response_model=ApiResponse[ActivityResponse])
async def get_activity(
    activity_id: UUID,
    tenant: TenantContextDependency,
    service: ActivityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACTIVITY_READ))],
) -> ApiResponse[ActivityResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, activity_id))


@router.patch("/{activity_id}", response_model=ApiResponse[ActivityResponse])
async def update_activity(
    activity_id: UUID,
    payload: ActivityUpdate,
    tenant: TenantContextDependency,
    service: ActivityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACTIVITY_UPDATE))],
) -> ApiResponse[ActivityResponse]:
    row = await service.update(tenant.tenant_id, activity_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Activity updated successfully")


@router.delete("/{activity_id}", response_model=ApiResponse[ActivityResponse])
async def delete_activity(
    activity_id: UUID,
    tenant: TenantContextDependency,
    service: ActivityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACTIVITY_DELETE))],
) -> ApiResponse[ActivityResponse]:
    row = await service.delete(tenant.tenant_id, activity_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Activity deleted successfully")


@router.post("/{activity_id}/complete", response_model=ApiResponse[ActivityResponse])
async def complete_activity(
    activity_id: UUID,
    tenant: TenantContextDependency,
    service: ActivityServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(ACTIVITY_UPDATE))],
    payload: Annotated[ActivityComplete | None, Body()] = None,
) -> ApiResponse[ActivityResponse]:
    row = await service.complete(
        tenant.tenant_id,
        activity_id,
        payload or ActivityComplete(),
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=row, message="Activity completed successfully")
