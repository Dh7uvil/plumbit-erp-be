"""Lost reason routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    LOST_REASON_CREATE,
    LOST_REASON_DELETE,
    LOST_REASON_READ,
    LOST_REASON_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.crm.lost_reasons.dependencies import LostReasonServiceDependency
from app.crm.lost_reasons.schemas import (
    LostReasonCreate,
    LostReasonFilter,
    LostReasonResponse,
    LostReasonUpdate,
)

router = APIRouter(prefix="/lost-reasons", tags=["Lost Reasons"])


@router.get("", response_model=ApiResponse[list[LostReasonResponse]])
async def list_lost_reasons(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: LostReasonServiceDependency,
    filters: Annotated[LostReasonFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(LOST_REASON_READ))],
) -> ApiResponse[list[LostReasonResponse]]:
    rows, total = await service.list(
        tenant.tenant_id, page=page, common_filter=filters, is_active=filters.is_active
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[LostReasonResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_lost_reason(
    payload: LostReasonCreate,
    tenant: TenantContextDependency,
    service: LostReasonServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LOST_REASON_CREATE))],
) -> ApiResponse[LostReasonResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Lost reason created successfully")


@router.get("/{lost_reason_id}", response_model=ApiResponse[LostReasonResponse])
async def get_lost_reason(
    lost_reason_id: UUID,
    tenant: TenantContextDependency,
    service: LostReasonServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LOST_REASON_READ))],
) -> ApiResponse[LostReasonResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, lost_reason_id))


@router.patch("/{lost_reason_id}", response_model=ApiResponse[LostReasonResponse])
async def update_lost_reason(
    lost_reason_id: UUID,
    payload: LostReasonUpdate,
    tenant: TenantContextDependency,
    service: LostReasonServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LOST_REASON_UPDATE))],
) -> ApiResponse[LostReasonResponse]:
    row = await service.update(
        tenant.tenant_id, lost_reason_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Lost reason updated successfully")


@router.delete("/{lost_reason_id}", response_model=ApiResponse[LostReasonResponse])
async def delete_lost_reason(
    lost_reason_id: UUID,
    tenant: TenantContextDependency,
    service: LostReasonServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(LOST_REASON_DELETE))],
) -> ApiResponse[LostReasonResponse]:
    row = await service.delete(tenant.tenant_id, lost_reason_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Lost reason deleted successfully")
