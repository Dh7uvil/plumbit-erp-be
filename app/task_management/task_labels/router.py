"""Task label routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    TASK_LABEL_CREATE,
    TASK_LABEL_DELETE,
    TASK_LABEL_READ,
    TASK_LABEL_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.task_management.task_labels.dependencies import TaskLabelServiceDependency
from app.task_management.task_labels.schemas import (
    TaskLabelCreate,
    TaskLabelFilter,
    TaskLabelResponse,
    TaskLabelUpdate,
)

router = APIRouter(prefix="/task-labels", tags=["Task Labels"])


@router.get("", response_model=ApiResponse[list[TaskLabelResponse]])
async def list_task_labels(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: TaskLabelServiceDependency,
    filters: Annotated[TaskLabelFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(TASK_LABEL_READ))],
) -> ApiResponse[list[TaskLabelResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[TaskLabelResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_task_label(
    payload: TaskLabelCreate,
    tenant: TenantContextDependency,
    service: TaskLabelServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_LABEL_CREATE))],
) -> ApiResponse[TaskLabelResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Label created successfully")


@router.get("/{label_id}", response_model=ApiResponse[TaskLabelResponse])
async def get_task_label(
    label_id: UUID,
    tenant: TenantContextDependency,
    service: TaskLabelServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_LABEL_READ))],
) -> ApiResponse[TaskLabelResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, label_id))


@router.patch("/{label_id}", response_model=ApiResponse[TaskLabelResponse])
async def update_task_label(
    label_id: UUID,
    payload: TaskLabelUpdate,
    tenant: TenantContextDependency,
    service: TaskLabelServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_LABEL_UPDATE))],
) -> ApiResponse[TaskLabelResponse]:
    row = await service.update(tenant.tenant_id, label_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Label updated successfully")


@router.delete("/{label_id}", response_model=ApiResponse[TaskLabelResponse])
async def delete_task_label(
    label_id: UUID,
    tenant: TenantContextDependency,
    service: TaskLabelServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_LABEL_DELETE))],
) -> ApiResponse[TaskLabelResponse]:
    row = await service.delete(tenant.tenant_id, label_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Label deleted successfully")
