"""Current-user notification preference routes."""

from fastapi import APIRouter

from app.common.dependencies.tenant import TenantContextDependency
from app.common.notification_preferences.dependencies import (
    NotificationPreferenceServiceDependency,
)
from app.common.notification_preferences.schemas import (
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
)
from app.common.schemas.response import ApiResponse

router = APIRouter(prefix="/users/me", tags=["Notification Preferences"])


@router.get(
    "/notification-preferences",
    response_model=ApiResponse[NotificationPreferenceResponse],
    summary="Get notification preferences",
    description=(
        "Return the authenticated user's notification channel toggles. "
        "Falls back to defaults when no preference is saved."
    ),
)
async def get_notification_preference(
    tenant: TenantContextDependency,
    service: NotificationPreferenceServiceDependency,
) -> ApiResponse[NotificationPreferenceResponse]:
    data = await service.get(tenant.tenant_id, tenant.user_id)
    return ApiResponse(data=data)


@router.patch(
    "/notification-preferences",
    response_model=ApiResponse[NotificationPreferenceResponse],
    summary="Update notification preferences",
)
async def patch_notification_preference(
    payload: NotificationPreferenceUpdate,
    tenant: TenantContextDependency,
    service: NotificationPreferenceServiceDependency,
) -> ApiResponse[NotificationPreferenceResponse]:
    data = await service.upsert(tenant.tenant_id, tenant.user_id, payload)
    return ApiResponse(data=data, message="Notification preferences saved")
