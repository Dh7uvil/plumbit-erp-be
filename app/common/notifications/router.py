"""Current-user in-app notification routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.tenant import TenantContextDependency
from app.common.notifications.dependencies import NotificationServiceDependency
from app.common.notifications.schemas import NotificationResponse, UnreadCountResponse
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get(
    "",
    response_model=ApiResponse[list[NotificationResponse]],
    summary="List notifications",
    description="Paginated in-app notifications for the authenticated user.",
)
async def list_notifications(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: NotificationServiceDependency,
    filters: Annotated[BaseFilter, Depends()],
    unread_only: Annotated[bool, Query(description="Return only unread notifications")] = False,
) -> ApiResponse[list[NotificationResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        tenant.user_id,
        page=page,
        common_filter=filters,
        unread_only=unread_only,
    )
    return paginated_response(rows, params=page, total=total)


@router.get(
    "/unread-count",
    response_model=ApiResponse[UnreadCountResponse],
    summary="Unread notification count",
)
async def unread_notification_count(
    tenant: TenantContextDependency,
    service: NotificationServiceDependency,
) -> ApiResponse[UnreadCountResponse]:
    data = await service.unread_count(tenant.tenant_id, tenant.user_id)
    return ApiResponse(data=data)


@router.post(
    "/{notification_id}/read",
    response_model=ApiResponse[NotificationResponse],
    summary="Mark notification read",
)
async def mark_notification_read(
    notification_id: Annotated[UUID, Path(description="Notification UUID")],
    tenant: TenantContextDependency,
    service: NotificationServiceDependency,
) -> ApiResponse[NotificationResponse]:
    data = await service.mark_read(tenant.tenant_id, tenant.user_id, notification_id)
    return ApiResponse(data=data, message="Notification marked read")


@router.post(
    "/read-all",
    response_model=ApiResponse[UnreadCountResponse],
    summary="Mark all notifications read",
)
async def mark_all_notifications_read(
    tenant: TenantContextDependency,
    service: NotificationServiceDependency,
) -> ApiResponse[UnreadCountResponse]:
    data = await service.mark_all_read(tenant.tenant_id, tenant.user_id)
    return ApiResponse(data=data, message="All notifications marked read")
