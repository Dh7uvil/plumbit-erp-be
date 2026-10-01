"""Chat notification settings routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.catalog import CONVERSATION_READ
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.communication.settings.dependencies import ChatNotificationSettingsServiceDependency
from app.communication.settings.schemas import (
    ChatNotificationSettingsResponse,
    ChatNotificationSettingsUpdate,
)
from app.communication.shared.feature import require_communication_enabled

router = APIRouter(prefix="/settings", tags=["Communication"])


@router.get("/notifications", response_model=ApiResponse[ChatNotificationSettingsResponse])
async def get_notification_settings(
    tenant: TenantContextDependency,
    service: ChatNotificationSettingsServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_READ))],
) -> ApiResponse[ChatNotificationSettingsResponse]:
    require_communication_enabled()
    row = await service.get(tenant.tenant_id, tenant.user_id)
    return ApiResponse(data=row)


@router.patch("/notifications", response_model=ApiResponse[ChatNotificationSettingsResponse])
async def update_notification_settings(
    payload: ChatNotificationSettingsUpdate,
    tenant: TenantContextDependency,
    service: ChatNotificationSettingsServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CONVERSATION_READ))],
) -> ApiResponse[ChatNotificationSettingsResponse]:
    require_communication_enabled()
    row = await service.update(tenant.tenant_id, tenant.user_id, payload)
    return ApiResponse(data=row)
