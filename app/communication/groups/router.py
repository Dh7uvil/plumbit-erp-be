"""Group conversation routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    CONVERSATION_CREATE,
    CONVERSATION_READ,
    CONVERSATION_UPDATE,
    GROUP_MANAGE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_any_permission, require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.communication.groups.dependencies import GroupServiceDependency
from app.communication.groups.schemas import (
    GroupCreate,
    GroupMembersAdd,
    GroupResponse,
    GroupUpdate,
)
from app.communication.shared.feature import require_communication_enabled

router = APIRouter(prefix="/groups", tags=["Communication"])


@router.post("", response_model=ApiResponse[GroupResponse], status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreate,
    tenant: TenantContextDependency,
    service: GroupServiceDependency,
    current_user: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_CREATE))],
) -> ApiResponse[GroupResponse]:
    require_communication_enabled()
    row = await service.create(
        tenant.tenant_id,
        payload,
        actor_user_id=tenant.user_id,
        actor_permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Group created")


@router.patch("/{group_id}", response_model=ApiResponse[GroupResponse])
async def update_group(
    group_id: UUID,
    payload: GroupUpdate,
    tenant: TenantContextDependency,
    service: GroupServiceDependency,
    current_user: Annotated[
        CurrentUser,
        Depends(require_any_permission(CONVERSATION_UPDATE, GROUP_MANAGE)),
    ],
) -> ApiResponse[GroupResponse]:
    require_communication_enabled()
    row = await service.update(
        tenant.tenant_id,
        group_id,
        payload,
        actor_user_id=tenant.user_id,
        actor_permissions=current_user.permissions,
    )
    return ApiResponse(data=row)


@router.post(
    "/{group_id}/members",
    response_model=ApiResponse[GroupResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_group_members(
    group_id: UUID,
    payload: GroupMembersAdd,
    tenant: TenantContextDependency,
    service: GroupServiceDependency,
    current_user: Annotated[
        CurrentUser,
        Depends(require_any_permission(CONVERSATION_UPDATE, GROUP_MANAGE)),
    ],
) -> ApiResponse[GroupResponse]:
    require_communication_enabled()
    row = await service.add_members(
        tenant.tenant_id,
        group_id,
        payload,
        actor_user_id=tenant.user_id,
        actor_permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Members added")


@router.delete("/{group_id}/members/{user_id}", response_model=ApiResponse[GroupResponse])
async def remove_group_member(
    group_id: UUID,
    user_id: UUID,
    tenant: TenantContextDependency,
    service: GroupServiceDependency,
    current_user: Annotated[
        CurrentUser,
        Depends(require_any_permission(CONVERSATION_UPDATE, GROUP_MANAGE, CONVERSATION_READ)),
    ],
) -> ApiResponse[GroupResponse]:
    require_communication_enabled()
    row = await service.remove_member(
        tenant.tenant_id,
        group_id,
        user_id,
        actor_user_id=tenant.user_id,
        actor_permissions=current_user.permissions,
    )
    return ApiResponse(data=row)


@router.post(
    "/{group_id}/admins/{user_id}",
    response_model=ApiResponse[GroupResponse],
    status_code=status.HTTP_201_CREATED,
)
async def promote_group_admin(
    group_id: UUID,
    user_id: UUID,
    tenant: TenantContextDependency,
    service: GroupServiceDependency,
    current_user: Annotated[
        CurrentUser,
        Depends(require_any_permission(CONVERSATION_UPDATE, GROUP_MANAGE)),
    ],
) -> ApiResponse[GroupResponse]:
    require_communication_enabled()
    row = await service.promote_admin(
        tenant.tenant_id,
        group_id,
        user_id,
        actor_user_id=tenant.user_id,
        actor_permissions=current_user.permissions,
    )
    return ApiResponse(data=row, message="Admin promoted")


@router.delete("/{group_id}/admins/{user_id}", response_model=ApiResponse[GroupResponse])
async def demote_group_admin(
    group_id: UUID,
    user_id: UUID,
    tenant: TenantContextDependency,
    service: GroupServiceDependency,
    current_user: Annotated[
        CurrentUser,
        Depends(require_any_permission(CONVERSATION_UPDATE, GROUP_MANAGE)),
    ],
) -> ApiResponse[GroupResponse]:
    require_communication_enabled()
    row = await service.demote_admin(
        tenant.tenant_id,
        group_id,
        user_id,
        actor_user_id=tenant.user_id,
        actor_permissions=current_user.permissions,
    )
    return ApiResponse(data=row)


@router.post("/{group_id}/leave", response_model=ApiResponse[None])
async def leave_group(
    group_id: UUID,
    tenant: TenantContextDependency,
    service: GroupServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_READ))],
) -> ApiResponse[None]:
    require_communication_enabled()
    await service.leave(tenant.tenant_id, group_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=None)
