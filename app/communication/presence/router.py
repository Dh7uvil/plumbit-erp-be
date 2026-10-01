"""Presence routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.catalog import PRESENCE_READ
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.communication.presence.dependencies import PresenceServiceDependency
from app.communication.presence.schemas import HeartbeatRequest, PresenceResponse
from app.communication.shared.feature import require_communication_enabled

router = APIRouter(tags=["Communication"])


@router.get("/presence", response_model=ApiResponse[list[PresenceResponse]])
async def get_presence(
    tenant: TenantContextDependency,
    service: PresenceServiceDependency,
    user_ids: Annotated[list[UUID], Query()],
    _: Annotated[CurrentUser, Depends(require_permission(PRESENCE_READ))],
) -> ApiResponse[list[PresenceResponse]]:
    require_communication_enabled()
    data = await service.get_presence(tenant.tenant_id, user_ids)
    return ApiResponse(data=data)


@router.post("/presence/heartbeat", response_model=ApiResponse[PresenceResponse])
async def heartbeat(
    payload: HeartbeatRequest,
    tenant: TenantContextDependency,
    service: PresenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRESENCE_READ))],
) -> ApiResponse[PresenceResponse]:
    require_communication_enabled()
    data = await service.heartbeat(tenant.tenant_id, tenant.user_id, payload)
    return ApiResponse(data=data)
