"""Per-record activity feed routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.common.activity.dependencies import ActivityServiceDependency
from app.common.activity.schemas import ActivityEntry, ActivityFilter
from app.common.dependencies.auth import CurrentUserDependency
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse

router = APIRouter(prefix="/activity", tags=["Activity"])


@router.get(
    "",
    response_model=ApiResponse[list[ActivityEntry]],
    summary="List per-record activity",
    description=(
        "Paginated audit history for one entity. Requires the owning record's read "
        "permission (for example `erp.quotation.read`), not `identity.audit_log.read`."
    ),
)
async def list_activity(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: ActivityServiceDependency,
    filters: Annotated[ActivityFilter, Depends()],
    current_user: CurrentUserDependency,
) -> ApiResponse[list[ActivityEntry]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        filters=filters,
        actor_permissions=current_user.permissions,
    )
    return paginated_response(rows, params=page, total=total)
