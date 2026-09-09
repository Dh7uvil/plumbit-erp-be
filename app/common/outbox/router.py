"""Operational outbox visibility and retry routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.catalog import OUTBOX_EVENT_READ, OUTBOX_EVENT_RETRY
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.outbox.dependencies import OutboxServiceDependency
from app.common.outbox.schemas import OutboxEventResponse, OutboxFilter
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.db.session import transaction

router = APIRouter(prefix="/outbox-events", tags=["Outbox Events"])


@router.get(
    "",
    response_model=ApiResponse[list[OutboxEventResponse]],
    summary="List outbox events",
    description="Requires `identity.outbox_event.read`. Tenant-scoped operational queue.",
)
async def list_outbox_events(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: OutboxServiceDependency,
    filters: Annotated[OutboxFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(OUTBOX_EVENT_READ))],
) -> ApiResponse[list[OutboxEventResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status is not None else None,
        event_type=filters.event_type,
        aggregate_type=filters.aggregate_type,
        aggregate_id=filters.aggregate_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.get(
    "/{event_id}",
    response_model=ApiResponse[OutboxEventResponse],
    summary="Get an outbox event",
    description="Requires `identity.outbox_event.read`.",
)
async def get_outbox_event(
    event_id: UUID,
    tenant: TenantContextDependency,
    service: OutboxServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OUTBOX_EVENT_READ))],
) -> ApiResponse[OutboxEventResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, event_id))


@router.post(
    "/{event_id}/retry",
    response_model=ApiResponse[OutboxEventResponse],
    summary="Retry a failed or dead outbox event",
    description="Requires `identity.outbox_event.retry`. Re-queues FAILED and DEAD rows.",
)
async def retry_outbox_event(
    event_id: UUID,
    tenant: TenantContextDependency,
    service: OutboxServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(OUTBOX_EVENT_RETRY))],
) -> ApiResponse[OutboxEventResponse]:
    async with transaction(service.session):
        row = await service.retry(tenant.tenant_id, event_id)
    return ApiResponse(data=row, message="Outbox event queued for retry")
