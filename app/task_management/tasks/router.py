"""Task routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    TASK_ASSIGN,
    TASK_CHECKLIST_CREATE,
    TASK_CHECKLIST_DELETE,
    TASK_CHECKLIST_READ,
    TASK_CHECKLIST_UPDATE,
    TASK_COMMENT_CREATE,
    TASK_COMMENT_DELETE,
    TASK_COMMENT_READ,
    TASK_COMMENT_UPDATE,
    TASK_CREATE,
    TASK_DELETE,
    TASK_MOVE,
    TASK_READ,
    TASK_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.task_management.tasks.dependencies import TaskServiceDependency
from app.task_management.tasks.schemas import (
    TaskAssign,
    TaskChecklistItemCreate,
    TaskChecklistItemResponse,
    TaskChecklistItemUpdate,
    TaskCommentCreate,
    TaskCommentResponse,
    TaskCommentUpdate,
    TaskCreate,
    TaskFilter,
    TaskLabelSet,
    TaskMove,
    TaskResponse,
    TaskUpdate,
    TaskWatcherSet,
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("", response_model=ApiResponse[list[TaskResponse]])
async def list_tasks(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: TaskServiceDependency,
    filters: Annotated[TaskFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(TASK_READ))],
) -> ApiResponse[list[TaskResponse]]:
    assignee_ids = [*filters.parsed_assignee_ids()]
    if filters.assignee_id is not None:
        assignee_ids.append(filters.assignee_id)
    if filters.mine:
        assignee_ids.append(tenant.user_id)
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        priority=filters.priority.value if filters.priority else None,
        assignee_ids=assignee_ids or None,
        statuses=[status.value for status in filters.parsed_statuses()],
        priorities=[priority.value for priority in filters.parsed_priorities()],
        label_ids=filters.parsed_label_ids(),
        task_types=[task_type.value for task_type in filters.parsed_task_types()],
        unassigned=filters.unassigned,
        parent_id=filters.parent_id,
        top_level_only=filters.top_level_only,
        overdue=filters.overdue,
        due_from=filters.due_from,
        due_to=filters.due_to,
        label_id=filters.label_id,
        related_entity_type=filters.related_entity_type.value
        if filters.related_entity_type
        else None,
        related_entity_id=filters.related_entity_id,
    )
    return paginated_response(rows, params=page, total=total)


@router.post("", response_model=ApiResponse[TaskResponse], status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_CREATE))],
) -> ApiResponse[TaskResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Task created successfully")


@router.get("/{task_id}", response_model=ApiResponse[TaskResponse])
async def get_task(
    task_id: UUID,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_READ))],
) -> ApiResponse[TaskResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, task_id))


@router.patch("/{task_id}", response_model=ApiResponse[TaskResponse])
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_UPDATE))],
) -> ApiResponse[TaskResponse]:
    row = await service.update(tenant.tenant_id, task_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Task updated successfully")


@router.delete("/{task_id}", response_model=ApiResponse[TaskResponse])
async def delete_task(
    task_id: UUID,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_DELETE))],
) -> ApiResponse[TaskResponse]:
    row = await service.delete(tenant.tenant_id, task_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Task deleted successfully")


@router.post("/{task_id}/move", response_model=ApiResponse[TaskResponse])
async def move_task(
    task_id: UUID,
    payload: TaskMove,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_MOVE))],
) -> ApiResponse[TaskResponse]:
    row = await service.move(tenant.tenant_id, task_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Task moved successfully")


@router.post("/{task_id}/assign", response_model=ApiResponse[TaskResponse])
async def assign_task(
    task_id: UUID,
    payload: TaskAssign,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_ASSIGN))],
) -> ApiResponse[TaskResponse]:
    row = await service.assign(tenant.tenant_id, task_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Task assigned successfully")


@router.put("/{task_id}/labels", response_model=ApiResponse[TaskResponse])
async def set_task_labels(
    task_id: UUID,
    payload: TaskLabelSet,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_UPDATE))],
) -> ApiResponse[TaskResponse]:
    row = await service.set_labels(tenant.tenant_id, task_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Task labels updated successfully")


@router.put("/{task_id}/watchers", response_model=ApiResponse[TaskResponse])
async def set_task_watchers(
    task_id: UUID,
    payload: TaskWatcherSet,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_UPDATE))],
) -> ApiResponse[TaskResponse]:
    row = await service.set_watchers(
        tenant.tenant_id, task_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Task watchers updated successfully")


@router.get(
    "/{task_id}/checklist-items",
    response_model=ApiResponse[list[TaskChecklistItemResponse]],
)
async def list_checklist_items(
    task_id: UUID,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_CHECKLIST_READ))],
) -> ApiResponse[list[TaskChecklistItemResponse]]:
    rows = await service.list_checklist(tenant.tenant_id, task_id)
    return ApiResponse(data=rows)


@router.post(
    "/{task_id}/checklist-items",
    response_model=ApiResponse[TaskChecklistItemResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_checklist_item(
    task_id: UUID,
    payload: TaskChecklistItemCreate,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_CHECKLIST_CREATE))],
) -> ApiResponse[TaskChecklistItemResponse]:
    row = await service.create_checklist_item(
        tenant.tenant_id, task_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Checklist item created successfully")


@router.patch(
    "/{task_id}/checklist-items/{item_id}",
    response_model=ApiResponse[TaskChecklistItemResponse],
)
async def update_checklist_item(
    task_id: UUID,
    item_id: UUID,
    payload: TaskChecklistItemUpdate,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_CHECKLIST_UPDATE))],
) -> ApiResponse[TaskChecklistItemResponse]:
    row = await service.update_checklist_item(
        tenant.tenant_id, task_id, item_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Checklist item updated successfully")


@router.delete(
    "/{task_id}/checklist-items/{item_id}",
    response_model=ApiResponse[TaskChecklistItemResponse],
)
async def delete_checklist_item(
    task_id: UUID,
    item_id: UUID,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_CHECKLIST_DELETE))],
) -> ApiResponse[TaskChecklistItemResponse]:
    row = await service.delete_checklist_item(
        tenant.tenant_id, task_id, item_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Checklist item deleted successfully")


@router.get("/{task_id}/comments", response_model=ApiResponse[list[TaskCommentResponse]])
async def list_task_comments(
    task_id: UUID,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_COMMENT_READ))],
) -> ApiResponse[list[TaskCommentResponse]]:
    rows = await service.list_comments(tenant.tenant_id, task_id)
    return ApiResponse(data=rows)


@router.post(
    "/{task_id}/comments",
    response_model=ApiResponse[TaskCommentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_task_comment(
    task_id: UUID,
    payload: TaskCommentCreate,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_COMMENT_CREATE))],
) -> ApiResponse[TaskCommentResponse]:
    row = await service.create_comment(
        tenant.tenant_id, task_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Comment created successfully")


@router.patch(
    "/{task_id}/comments/{comment_id}",
    response_model=ApiResponse[TaskCommentResponse],
)
async def update_task_comment(
    task_id: UUID,
    comment_id: UUID,
    payload: TaskCommentUpdate,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_COMMENT_UPDATE))],
) -> ApiResponse[TaskCommentResponse]:
    row = await service.update_comment(
        tenant.tenant_id, task_id, comment_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Comment updated successfully")


@router.delete(
    "/{task_id}/comments/{comment_id}",
    response_model=ApiResponse[TaskCommentResponse],
)
async def delete_task_comment(
    task_id: UUID,
    comment_id: UUID,
    tenant: TenantContextDependency,
    service: TaskServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TASK_COMMENT_DELETE))],
) -> ApiResponse[TaskCommentResponse]:
    row = await service.delete_comment(
        tenant.tenant_id, task_id, comment_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Comment deleted successfully")
