"""Task use cases."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.auth.catalog import (
    TASK_ASSIGN,
    TASK_DELETE,
    TASK_MOVE,
    TASK_UPDATE,
    TASKS_MODULE,
)
from app.auth.models import User
from app.common.repositories.scoping import Actor, record_scope_criteria
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.outbox.service import OutboxService
from app.common.services.audit import AuditWriter
from app.common.utils.datetime import utcnow
from app.core.enums import AuditAction, TaskPriority, TaskRelatedEntityType, TaskStatus, TaskType
from app.core.exceptions import AppError, ResourceNotFoundError, ValidationError
from app.core.permissions import has_permission
from app.db.session import transaction
from app.task_management.task_labels.models import TaskLabel
from app.task_management.tasks.codes import allocate_task_number
from app.task_management.tasks.models import (
    Task,
    TaskChecklistItem,
    TaskComment,
    TaskLabelLink,
    TaskWatcher,
)
from app.task_management.tasks.related import assert_related_entity_exists
from app.task_management.tasks.repository import TaskRepository
from app.task_management.tasks.schemas import (
    TaskAssign,
    TaskBulkAssign,
    TaskBulkResult,
    TaskBulkResultItem,
    TaskBulkStatus,
    TaskChecklistItemCreate,
    TaskChecklistItemResponse,
    TaskChecklistItemUpdate,
    TaskCommentCreate,
    TaskCommentResponse,
    TaskCommentUpdate,
    TaskCreate,
    TaskLabelSet,
    TaskLabelSummary,
    TaskMove,
    TaskParentSummary,
    TaskResponse,
    TaskUpdate,
    TaskWatcherSet,
)
from app.task_management.tasks.workflow import assert_move_allowed, available_actions

MAX_TASK_DEPTH = 3


class TaskService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
        actor: Actor | None = None,
        repo: TaskRepository | None = None,
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.actor = actor
        self.repo = repo or TaskRepository(session)
        self.audit = AuditWriter(session)
        self.outbox = OutboxService(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        priority: str | None = None,
        assignee_id: UUID | None = None,
        assignee_ids: builtins.list[UUID] | None = None,
        statuses: builtins.list[str] | None = None,
        priorities: builtins.list[str] | None = None,
        label_ids: builtins.list[UUID] | None = None,
        task_types: builtins.list[str] | None = None,
        unassigned: bool | None = None,
        parent_id: UUID | None = None,
        top_level_only: bool | None = None,
        overdue: bool | None = None,
        due_from: datetime | None = None,
        due_to: datetime | None = None,
        label_id: UUID | None = None,
        related_entity_type: str | None = None,
        related_entity_id: UUID | None = None,
    ) -> tuple[builtins.list[TaskResponse], int]:
        merged_statuses = list(statuses or [])
        if status is not None and status not in merged_statuses:
            merged_statuses.append(status)
        merged_priorities = list(priorities or [])
        if priority is not None and priority not in merged_priorities:
            merged_priorities.append(priority)
        merged_assignee_ids = list(assignee_ids or [])
        if assignee_id is not None and assignee_id not in merged_assignee_ids:
            merged_assignee_ids.append(assignee_id)
        merged_label_ids = list(label_ids or [])
        if label_id is not None and label_id not in merged_label_ids:
            merged_label_ids.append(label_id)

        filters: dict[str, object] = {}
        if related_entity_type is not None:
            filters["related_entity_type"] = related_entity_type
        if related_entity_id is not None:
            filters["related_entity_id"] = related_entity_id
        if parent_id is not None:
            filters["parent_id"] = parent_id
        if len(merged_statuses) == 1:
            filters["status"] = merged_statuses[0]
        if len(merged_priorities) == 1:
            filters["priority"] = merged_priorities[0]
        if len(merged_assignee_ids) == 1 and not unassigned:
            filters["assignee_id"] = merged_assignee_ids[0]

        extra: builtins.list[ColumnElement[bool]] = []
        if overdue:
            extra.append(Task.due_at.is_not(None))
            extra.append(Task.due_at < utcnow())
            extra.append(Task.status.notin_([TaskStatus.DONE.value, TaskStatus.CANCELLED.value]))
        if due_from is not None:
            extra.append(Task.due_at.is_not(None))
            extra.append(Task.due_at >= due_from)
        if due_to is not None:
            extra.append(Task.due_at.is_not(None))
            extra.append(Task.due_at <= due_to)
        if merged_assignee_ids and unassigned:
            extra.append(
                or_(Task.assignee_id.in_(merged_assignee_ids), Task.assignee_id.is_(None))
            )
        elif merged_assignee_ids:
            extra.append(Task.assignee_id.in_(merged_assignee_ids))
        elif unassigned:
            extra.append(Task.assignee_id.is_(None))
        if len(merged_statuses) > 1:
            extra.append(Task.status.in_(merged_statuses))
        if len(merged_priorities) > 1:
            extra.append(Task.priority.in_(merged_priorities))
        if task_types:
            extra.append(Task.task_type.in_(task_types))
        if top_level_only:
            extra.append(Task.parent_id.is_(None))
        if merged_label_ids:
            extra.append(
                Task.id.in_(
                    select(TaskLabelLink.task_id).where(
                        TaskLabelLink.tenant_id == tenant_id,
                        TaskLabelLink.label_id.in_(merged_label_ids),
                    )
                )
            )
        elif label_id is not None:
            extra.append(
                Task.id.in_(
                    select(TaskLabelLink.task_id).where(
                        TaskLabelLink.tenant_id == tenant_id,
                        TaskLabelLink.label_id == label_id,
                    )
                )
            )
        if self.actor is not None:
            extra.extend(record_scope_criteria(self.actor, Task))

        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        return await self._to_response_list(rows), total

    async def get(self, tenant_id: UUID, task_id: UUID) -> TaskResponse:
        row = await self._require(tenant_id, task_id)
        return await self._to_response(row, include_children=True)

    async def create(
        self, tenant_id: UUID, payload: TaskCreate, *, actor_user_id: UUID
    ) -> TaskResponse:
        async with transaction(self.session):
            await self._validate_related_optional(
                tenant_id, payload.related_entity_type, payload.related_entity_id
            )
            if payload.assignee_id is not None:
                await self._require_user(tenant_id, payload.assignee_id)
            for watcher_id in payload.watcher_ids:
                await self._require_user(tenant_id, watcher_id)
            await self._require_labels(tenant_id, payload.label_ids)
            if payload.parent_id is not None:
                await self._assert_valid_parent(
                    None, payload.parent_id, tenant_id, task_type=payload.task_type
                )

            sort_order = await self._next_sort_order(tenant_id, TaskStatus.TODO.value)
            task_number = await allocate_task_number(self.session, tenant_id)
            values = {
                "task_number": task_number,
                "title": payload.title,
                "description": payload.description,
                "task_type": payload.task_type.value,
                "priority": payload.priority.value,
                "due_at": payload.due_at,
                "assignee_id": payload.assignee_id,
                "parent_id": payload.parent_id,
                "status": TaskStatus.TODO.value,
                "sort_order": sort_order,
                "related_entity_type": payload.related_entity_type.value
                if payload.related_entity_type
                else None,
                "related_entity_id": payload.related_entity_id,
                "created_by": actor_user_id,
                "updated_by": actor_user_id,
            }
            row = await self.repo.create(tenant_id, values)
            await self._replace_labels(tenant_id, row.id, payload.label_ids)
            await self._replace_watchers(tenant_id, row.id, payload.watcher_ids)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=TASKS_MODULE,
                entity_type="task",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, row),
            )
            return await self._to_response(row, include_children=True)

    async def update(
        self,
        tenant_id: UUID,
        task_id: UUID,
        payload: TaskUpdate,
        *,
        actor_user_id: UUID,
    ) -> TaskResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            existing = await self._require(tenant_id, task_id)
            old_values = await self._snapshot(tenant_id, existing)
            if "task_type" in values and payload.task_type is not None:
                next_task_type = payload.task_type
            else:
                next_task_type = TaskType(existing.task_type)
            if "parent_id" in values:
                if payload.parent_id is not None:
                    await self._assert_valid_parent(
                        task_id, payload.parent_id, tenant_id, task_type=next_task_type
                    )
                if payload.parent_id == task_id:
                    raise ValidationError("A task cannot be its own parent")
            if "task_type" in values and payload.task_type is not None:
                values["task_type"] = payload.task_type.value
                if payload.task_type is TaskType.EPIC and existing.parent_id is not None:
                    raise ValidationError("An epic cannot have a parent")
            if "related_entity_type" in values or "related_entity_id" in values:
                rel_type = payload.related_entity_type
                rel_id = payload.related_entity_id
                if (rel_type is None) != (rel_id is None):
                    raise ValidationError(
                        "related_entity_type and related_entity_id must be provided together"
                    )
                if rel_type is not None and rel_id is not None:
                    await assert_related_entity_exists(self.session, tenant_id, rel_type, rel_id)
                    values["related_entity_type"] = rel_type.value
                else:
                    values["related_entity_type"] = None
                    values["related_entity_id"] = None
            if "assignee_id" in values and payload.assignee_id is not None:
                await self._require_user(tenant_id, payload.assignee_id)
            if "priority" in values and payload.priority is not None:
                values["priority"] = payload.priority.value
            values["updated_by"] = actor_user_id
            row = await self.repo.update(tenant_id, task_id, values)
            if row is None:
                raise ResourceNotFoundError("Task not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=TASKS_MODULE,
                entity_type="task",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            return await self._to_response(row, include_children=True)

    async def move(
        self,
        tenant_id: UUID,
        task_id: UUID,
        payload: TaskMove,
        *,
        actor_user_id: UUID,
    ) -> TaskResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, task_id)
            from_status = TaskStatus(existing.status)
            to_status = payload.status
            assert_move_allowed(from_status, to_status)
            old_values = await self._snapshot(tenant_id, existing)
            old_status_value = existing.status

            move_values: dict[str, object] = {
                "status": to_status.value,
                "sort_order": payload.sort_order,
                "updated_by": actor_user_id,
            }
            if to_status is TaskStatus.IN_PROGRESS and existing.started_at is None:
                move_values["started_at"] = utcnow()
            if to_status is TaskStatus.DONE:
                move_values["completed_at"] = utcnow()
            if from_status is TaskStatus.DONE and to_status is not TaskStatus.DONE:
                move_values["completed_at"] = None

            row = await self.repo.update(tenant_id, task_id, move_values)
            if row is None:
                raise ResourceNotFoundError("Task not found")
            await self._apply_sort_order(tenant_id, task_id, to_status.value, payload.sort_order)
            if old_status_value != to_status.value:
                await self._resequence_column(tenant_id, old_status_value)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=TASKS_MODULE,
                entity_type="task",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            refreshed = await self._require(tenant_id, task_id)
            return await self._to_response(refreshed, include_children=True)

    async def bulk_assign(
        self,
        tenant_id: UUID,
        payload: TaskBulkAssign,
        *,
        actor_user_id: UUID,
    ) -> TaskBulkResult:
        items: builtins.list[TaskBulkResultItem] = []
        for entry in payload.items:
            if not has_permission(self.actor_permissions, TASK_ASSIGN):
                items.append(
                    TaskBulkResultItem(
                        task_id=entry.task_id,
                        success=False,
                        error="Permission denied",
                    )
                )
                continue
            try:
                async with transaction(self.session):
                    row = await self.assign(
                        tenant_id,
                        entry.task_id,
                        TaskAssign(assignee_id=entry.assignee_id),
                        actor_user_id=actor_user_id,
                    )
                items.append(TaskBulkResultItem(task_id=entry.task_id, success=True, data=row))
            except (AppError, ValidationError) as exc:
                items.append(
                    TaskBulkResultItem(
                        task_id=entry.task_id,
                        success=False,
                        error=str(exc),
                    )
                )
        success_count = sum(1 for item in items if item.success)
        return TaskBulkResult(
            items=items,
            success_count=success_count,
            error_count=len(items) - success_count,
        )

    async def bulk_status(
        self,
        tenant_id: UUID,
        payload: TaskBulkStatus,
        *,
        actor_user_id: UUID,
    ) -> TaskBulkResult:
        items: builtins.list[TaskBulkResultItem] = []
        for entry in payload.items:
            if not has_permission(self.actor_permissions, TASK_MOVE):
                items.append(
                    TaskBulkResultItem(
                        task_id=entry.task_id,
                        success=False,
                        error="Permission denied",
                    )
                )
                continue
            try:
                existing = await self._require(tenant_id, entry.task_id)
                sort_order = (
                    entry.sort_order if entry.sort_order is not None else existing.sort_order
                )
                async with transaction(self.session):
                    row = await self.move(
                        tenant_id,
                        entry.task_id,
                        TaskMove(status=entry.status, sort_order=sort_order),
                        actor_user_id=actor_user_id,
                    )
                items.append(TaskBulkResultItem(task_id=entry.task_id, success=True, data=row))
            except (AppError, ValidationError) as exc:
                items.append(
                    TaskBulkResultItem(
                        task_id=entry.task_id,
                        success=False,
                        error=str(exc),
                    )
                )
        success_count = sum(1 for item in items if item.success)
        return TaskBulkResult(
            items=items,
            success_count=success_count,
            error_count=len(items) - success_count,
        )

    async def assign(
        self,
        tenant_id: UUID,
        task_id: UUID,
        payload: TaskAssign,
        *,
        actor_user_id: UUID,
    ) -> TaskResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, task_id)
            if payload.assignee_id is not None:
                await self._require_user(tenant_id, payload.assignee_id)
            old_values = await self._snapshot(tenant_id, existing)
            row = await self.repo.update(
                tenant_id,
                task_id,
                {"assignee_id": payload.assignee_id, "updated_by": actor_user_id},
            )
            if row is None:
                raise ResourceNotFoundError("Task not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=TASKS_MODULE,
                entity_type="task",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            if (
                payload.assignee_id is not None
                and payload.assignee_id != actor_user_id
                and old_values.get("assignee_id") != str(payload.assignee_id)
            ):
                await self.outbox.enqueue(
                    tenant_id,
                    event_type="tasks.assigned",
                    aggregate_type="task",
                    aggregate_id=row.id,
                    payload={
                        "task_id": str(row.id),
                        "assignee_id": str(payload.assignee_id),
                        "actor_user_id": str(actor_user_id),
                        "task_number": row.task_number,
                        "title": row.title,
                    },
                    dedupe_key=f"task-assigned:{row.id}:{payload.assignee_id}",
                )
            return await self._to_response(row, include_children=True)

    async def delete(self, tenant_id: UUID, task_id: UUID, *, actor_user_id: UUID) -> TaskResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, task_id)
            if await self._has_active_children(tenant_id, task_id):
                raise ValidationError(
                    "Cannot delete a task that still has subtasks. Delete or re-parent them first."
                )
            response = await self._to_response(row, include_children=True)
            status_value = row.status
            await self.repo.soft_delete(tenant_id, task_id)
            await self._resequence_column(tenant_id, status_value)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=TASKS_MODULE,
                entity_type="task",
                entity_id=task_id,
                old_values=await self._snapshot(tenant_id, row),
            )
            return response

    async def set_labels(
        self,
        tenant_id: UUID,
        task_id: UUID,
        payload: TaskLabelSet,
        *,
        actor_user_id: UUID,
    ) -> TaskResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, task_id)
            await self._require_labels(tenant_id, payload.label_ids)
            old_values = await self._snapshot(tenant_id, existing)
            await self._replace_labels(tenant_id, task_id, payload.label_ids)
            row = await self._require(tenant_id, task_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=TASKS_MODULE,
                entity_type="task",
                entity_id=task_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            return await self._to_response(row, include_children=True)

    async def set_watchers(
        self,
        tenant_id: UUID,
        task_id: UUID,
        payload: TaskWatcherSet,
        *,
        actor_user_id: UUID,
    ) -> TaskResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, task_id)
            for watcher_id in payload.watcher_ids:
                await self._require_user(tenant_id, watcher_id)
            old_values = await self._snapshot(tenant_id, existing)
            await self._replace_watchers(tenant_id, task_id, payload.watcher_ids)
            row = await self._require(tenant_id, task_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=TASKS_MODULE,
                entity_type="task",
                entity_id=task_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            return await self._to_response(row, include_children=True)

    async def list_checklist(
        self, tenant_id: UUID, task_id: UUID
    ) -> builtins.list[TaskChecklistItemResponse]:
        await self._require(tenant_id, task_id)
        statement = (
            select(TaskChecklistItem)
            .where(
                TaskChecklistItem.tenant_id == tenant_id,
                TaskChecklistItem.task_id == task_id,
            )
            .order_by(TaskChecklistItem.sort_order, TaskChecklistItem.created_at)
        )
        result = await self.session.execute(statement)
        return [TaskChecklistItemResponse.model_validate(row) for row in result.scalars().all()]

    async def create_checklist_item(
        self,
        tenant_id: UUID,
        task_id: UUID,
        payload: TaskChecklistItemCreate,
        *,
        actor_user_id: UUID,
    ) -> TaskChecklistItemResponse:
        async with transaction(self.session):
            await self._require(tenant_id, task_id)
            row = TaskChecklistItem(
                tenant_id=tenant_id,
                task_id=task_id,
                title=payload.title,
                sort_order=payload.sort_order,
            )
            self.session.add(row)
            await self.session.flush()
            return TaskChecklistItemResponse.model_validate(row)

    async def update_checklist_item(
        self,
        tenant_id: UUID,
        task_id: UUID,
        item_id: UUID,
        payload: TaskChecklistItemUpdate,
        *,
        actor_user_id: UUID,
    ) -> TaskChecklistItemResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            await self._require(tenant_id, task_id)
            row = await self._require_checklist_item(tenant_id, task_id, item_id)
            for key, value in values.items():
                setattr(row, key, value)
            await self.session.flush()
            return TaskChecklistItemResponse.model_validate(row)

    async def delete_checklist_item(
        self,
        tenant_id: UUID,
        task_id: UUID,
        item_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> TaskChecklistItemResponse:
        async with transaction(self.session):
            await self._require(tenant_id, task_id)
            row = await self._require_checklist_item(tenant_id, task_id, item_id)
            response = TaskChecklistItemResponse.model_validate(row)
            await self.session.delete(row)
            await self.session.flush()
            return response

    async def list_comments(
        self, tenant_id: UUID, task_id: UUID
    ) -> builtins.list[TaskCommentResponse]:
        await self._require(tenant_id, task_id)
        statement = (
            select(TaskComment)
            .where(
                TaskComment.tenant_id == tenant_id,
                TaskComment.task_id == task_id,
                TaskComment.deleted_at.is_(None),
            )
            .order_by(TaskComment.created_at)
        )
        result = await self.session.execute(statement)
        return [TaskCommentResponse.model_validate(row) for row in result.scalars().all()]

    async def create_comment(
        self,
        tenant_id: UUID,
        task_id: UUID,
        payload: TaskCommentCreate,
        *,
        actor_user_id: UUID,
    ) -> TaskCommentResponse:
        async with transaction(self.session):
            await self._require(tenant_id, task_id)
            row = TaskComment(
                tenant_id=tenant_id,
                task_id=task_id,
                body=payload.body,
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
            self.session.add(row)
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=TASKS_MODULE,
                entity_type="task_comment",
                entity_id=row.id,
                new_values={"body": row.body, "task_id": str(task_id)},
            )
            return TaskCommentResponse.model_validate(row)

    async def update_comment(
        self,
        tenant_id: UUID,
        task_id: UUID,
        comment_id: UUID,
        payload: TaskCommentUpdate,
        *,
        actor_user_id: UUID,
    ) -> TaskCommentResponse:
        async with transaction(self.session):
            await self._require(tenant_id, task_id)
            row = await self._require_comment(tenant_id, task_id, comment_id)
            old_values: dict[str, object] = {"body": row.body}
            row.body = payload.body
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=TASKS_MODULE,
                entity_type="task_comment",
                entity_id=row.id,
                old_values=old_values,
                new_values={"body": row.body},
            )
            return TaskCommentResponse.model_validate(row)

    async def delete_comment(
        self,
        tenant_id: UUID,
        task_id: UUID,
        comment_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> TaskCommentResponse:
        async with transaction(self.session):
            await self._require(tenant_id, task_id)
            row = await self._require_comment(tenant_id, task_id, comment_id)
            response = TaskCommentResponse.model_validate(row)
            row.deleted_at = utcnow()
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=TASKS_MODULE,
                entity_type="task_comment",
                entity_id=row.id,
                old_values={"body": row.body},
            )
            return response

    def _available_actions(self, status: TaskStatus) -> builtins.list[str]:
        return available_actions(
            status,
            can_update=has_permission(self.actor_permissions, TASK_UPDATE),
            can_delete=has_permission(self.actor_permissions, TASK_DELETE),
            can_move=has_permission(self.actor_permissions, TASK_MOVE),
            can_assign=has_permission(self.actor_permissions, TASK_ASSIGN),
        )

    async def _to_response_list(self, rows: Sequence[Task]) -> builtins.list[TaskResponse]:
        if not rows:
            return []
        tenant_id = rows[0].tenant_id
        task_ids = [row.id for row in rows]
        parent_ids = {row.parent_id for row in rows if row.parent_id is not None}
        labels_by_task = await self._load_labels_batch(tenant_id, task_ids)
        watchers_by_task = await self._load_watcher_ids_batch(tenant_id, task_ids)
        parents_by_id = await self._load_parent_summaries(tenant_id, parent_ids)
        subtask_counts = await self._load_subtask_counts(tenant_id, task_ids)
        return [
            self._build_response(
                row,
                labels=labels_by_task.get(row.id, []),
                watcher_ids=watchers_by_task.get(row.id, []),
                checklist_items=[],
                parent=parents_by_id.get(row.parent_id) if row.parent_id else None,
                subtask_count=subtask_counts.get(row.id, (0, 0))[0],
                subtask_done_count=subtask_counts.get(row.id, (0, 0))[1],
            )
            for row in rows
        ]

    async def _to_response(self, row: Task, *, include_children: bool) -> TaskResponse:
        labels = await self._load_labels(row.tenant_id, row.id)
        watcher_ids = await self._load_watcher_ids(row.tenant_id, row.id)
        checklist_items: builtins.list[TaskChecklistItemResponse] = []
        parent: TaskParentSummary | None = None
        subtask_count = 0
        subtask_done_count = 0
        if include_children:
            checklist_items = await self.list_checklist(row.tenant_id, row.id)
        if row.parent_id is not None:
            parents = await self._load_parent_summaries(row.tenant_id, {row.parent_id})
            parent = parents.get(row.parent_id)
        counts = await self._load_subtask_counts(row.tenant_id, [row.id])
        subtask_count, subtask_done_count = counts.get(row.id, (0, 0))
        return self._build_response(
            row,
            labels=labels,
            watcher_ids=watcher_ids,
            checklist_items=checklist_items,
            parent=parent,
            subtask_count=subtask_count,
            subtask_done_count=subtask_done_count,
        )

    def _build_response(
        self,
        row: Task,
        *,
        labels: builtins.list[TaskLabelSummary],
        watcher_ids: builtins.list[UUID],
        checklist_items: builtins.list[TaskChecklistItemResponse],
        parent: TaskParentSummary | None,
        subtask_count: int,
        subtask_done_count: int,
    ) -> TaskResponse:
        related_type = (
            TaskRelatedEntityType(row.related_entity_type) if row.related_entity_type else None
        )
        return TaskResponse.model_validate(row).model_copy(
            update={
                "task_type": TaskType(row.task_type),
                "status": TaskStatus(row.status),
                "priority": TaskPriority(row.priority),
                "related_entity_type": related_type,
                "parent": parent,
                "subtask_count": subtask_count,
                "subtask_done_count": subtask_done_count,
                "labels": labels,
                "watcher_ids": watcher_ids,
                "checklist_items": checklist_items,
                "available_actions": self._available_actions(TaskStatus(row.status)),
            }
        )

    async def _assert_valid_parent(
        self,
        task_id: UUID | None,
        parent_id: UUID,
        tenant_id: UUID,
        *,
        task_type: TaskType,
    ) -> None:
        if task_type is TaskType.EPIC:
            raise ValidationError("An epic cannot have a parent")
        if task_id is not None and parent_id == task_id:
            raise ValidationError("A task cannot be its own parent")
        parent = await self.repo.get(tenant_id, parent_id)
        if parent is None:
            raise ValidationError("Parent task not found")
        current: Task | None = parent
        depth = 0
        while current is not None:
            if task_id is not None and current.id == task_id:
                raise ValidationError("A task cannot be a descendant of itself")
            depth += 1
            if depth >= MAX_TASK_DEPTH:
                raise ValidationError("Tasks can be nested at most three levels deep")
            if current.parent_id is None:
                break
            current = await self.repo.get(tenant_id, current.parent_id)

    async def _has_active_children(self, tenant_id: UUID, task_id: UUID) -> bool:
        statement = select(Task.id).where(
            Task.tenant_id == tenant_id,
            Task.parent_id == task_id,
            Task.deleted_at.is_(None),
        )
        result = await self.session.execute(statement.limit(1))
        return result.scalar_one_or_none() is not None

    async def _load_parent_summaries(
        self, tenant_id: UUID, parent_ids: set[UUID]
    ) -> dict[UUID, TaskParentSummary]:
        if not parent_ids:
            return {}
        statement = select(Task).where(
            Task.tenant_id == tenant_id,
            Task.id.in_(parent_ids),
            Task.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return {
            row.id: TaskParentSummary(
                id=row.id,
                task_number=row.task_number,
                title=row.title,
                task_type=TaskType(row.task_type),
            )
            for row in result.scalars().all()
        }

    async def _load_subtask_counts(
        self, tenant_id: UUID, task_ids: builtins.list[UUID]
    ) -> dict[UUID, tuple[int, int]]:
        if not task_ids:
            return {}
        statement = (
            select(
                Task.parent_id,
                func.count(Task.id),
                func.sum(
                    case(
                        (Task.status.in_([TaskStatus.DONE.value, TaskStatus.CANCELLED.value]), 1),
                        else_=0,
                    )
                ),
            )
            .where(
                Task.tenant_id == tenant_id,
                Task.parent_id.in_(task_ids),
                Task.deleted_at.is_(None),
            )
            .group_by(Task.parent_id)
        )
        result = await self.session.execute(statement)
        return {
            parent_id: (int(total), int(done or 0))
            for parent_id, total, done in result.all()
            if parent_id is not None
        }

    async def _load_labels_batch(
        self, tenant_id: UUID, task_ids: builtins.list[UUID]
    ) -> dict[UUID, builtins.list[TaskLabelSummary]]:
        if not task_ids:
            return {}
        statement = (
            select(TaskLabelLink.task_id, TaskLabel)
            .join(TaskLabel, TaskLabelLink.label_id == TaskLabel.id)
            .where(
                TaskLabelLink.tenant_id == tenant_id,
                TaskLabelLink.task_id.in_(task_ids),
                TaskLabel.deleted_at.is_(None),
            )
            .order_by(TaskLabel.name)
        )
        result = await self.session.execute(statement)
        grouped: dict[UUID, builtins.list[TaskLabelSummary]] = {}
        for task_id, label in result.all():
            grouped.setdefault(task_id, []).append(
                TaskLabelSummary(id=label.id, name=label.name, color=label.color)
            )
        return grouped

    async def _load_watcher_ids_batch(
        self, tenant_id: UUID, task_ids: builtins.list[UUID]
    ) -> dict[UUID, builtins.list[UUID]]:
        if not task_ids:
            return {}
        statement = select(TaskWatcher.task_id, TaskWatcher.user_id).where(
            TaskWatcher.tenant_id == tenant_id,
            TaskWatcher.task_id.in_(task_ids),
        )
        result = await self.session.execute(statement)
        grouped: dict[UUID, builtins.list[UUID]] = {}
        for task_id, user_id in result.all():
            grouped.setdefault(task_id, []).append(user_id)
        return grouped

    async def _require(self, tenant_id: UUID, task_id: UUID) -> Task:
        row = await self.repo.get(tenant_id, task_id)
        if row is None:
            raise ResourceNotFoundError("Task not found")
        return row

    async def _require_user(self, tenant_id: UUID, user_id: UUID) -> None:
        statement = select(User.id).where(User.tenant_id == tenant_id, User.id == user_id)
        result = await self.session.execute(statement)
        if result.scalar_one_or_none() is None:
            raise ValidationError("User not found")

    async def _require_labels(self, tenant_id: UUID, label_ids: builtins.list[UUID]) -> None:
        if not label_ids:
            return
        statement = select(TaskLabel.id).where(
            TaskLabel.tenant_id == tenant_id,
            TaskLabel.id.in_(label_ids),
            TaskLabel.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        found = {row[0] for row in result.all()}
        missing = [str(label_id) for label_id in label_ids if label_id not in found]
        if missing:
            raise ValidationError(
                "One or more labels were not found",
                details={"label_ids": missing},
            )

    async def _validate_related_optional(
        self,
        tenant_id: UUID,
        related_entity_type: TaskRelatedEntityType | None,
        related_entity_id: UUID | None,
    ) -> None:
        if related_entity_type is None and related_entity_id is None:
            return
        if related_entity_type is None or related_entity_id is None:
            raise ValidationError(
                "related_entity_type and related_entity_id must be provided together"
            )
        await assert_related_entity_exists(
            self.session, tenant_id, related_entity_type, related_entity_id
        )

    async def _next_sort_order(self, tenant_id: UUID, status: str) -> int:
        statement = select(func.coalesce(func.max(Task.sort_order), -1)).where(
            Task.tenant_id == tenant_id,
            Task.status == status,
            Task.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return int(result.scalar_one()) + 1

    async def _apply_sort_order(
        self, tenant_id: UUID, task_id: UUID, status: str, sort_order: int
    ) -> None:
        await self.session.execute(
            update(Task)
            .where(
                Task.tenant_id == tenant_id,
                Task.status == status,
                Task.deleted_at.is_(None),
                Task.id != task_id,
                Task.sort_order >= sort_order,
            )
            .values(sort_order=Task.sort_order + 1)
        )
        await self.session.flush()
        await self._resequence_column(tenant_id, status)

    async def _resequence_column(self, tenant_id: UUID, status: str) -> None:
        statement = (
            select(Task.id)
            .where(
                Task.tenant_id == tenant_id,
                Task.status == status,
                Task.deleted_at.is_(None),
            )
            .order_by(Task.sort_order, Task.created_at)
        )
        result = await self.session.execute(statement)
        for index, (task_id,) in enumerate(result.all()):
            await self.session.execute(
                update(Task)
                .where(Task.tenant_id == tenant_id, Task.id == task_id)
                .values(sort_order=index)
            )
        await self.session.flush()

    async def _replace_labels(
        self, tenant_id: UUID, task_id: UUID, label_ids: builtins.list[UUID]
    ) -> None:
        await self.session.execute(
            delete(TaskLabelLink).where(
                TaskLabelLink.tenant_id == tenant_id,
                TaskLabelLink.task_id == task_id,
            )
        )
        for label_id in label_ids:
            self.session.add(TaskLabelLink(tenant_id=tenant_id, task_id=task_id, label_id=label_id))
        await self.session.flush()

    async def _replace_watchers(
        self, tenant_id: UUID, task_id: UUID, watcher_ids: builtins.list[UUID]
    ) -> None:
        await self.session.execute(
            delete(TaskWatcher).where(
                TaskWatcher.tenant_id == tenant_id,
                TaskWatcher.task_id == task_id,
            )
        )
        for user_id in watcher_ids:
            self.session.add(TaskWatcher(tenant_id=tenant_id, task_id=task_id, user_id=user_id))
        await self.session.flush()

    async def _load_labels(self, tenant_id: UUID, task_id: UUID) -> builtins.list[TaskLabelSummary]:
        statement = (
            select(TaskLabel)
            .join(TaskLabelLink, TaskLabelLink.label_id == TaskLabel.id)
            .where(
                TaskLabelLink.tenant_id == tenant_id,
                TaskLabelLink.task_id == task_id,
                TaskLabel.deleted_at.is_(None),
            )
            .order_by(TaskLabel.name)
        )
        result = await self.session.execute(statement)
        return [
            TaskLabelSummary(id=row.id, name=row.name, color=row.color)
            for row in result.scalars().all()
        ]

    async def _load_watcher_ids(self, tenant_id: UUID, task_id: UUID) -> builtins.list[UUID]:
        statement = select(TaskWatcher.user_id).where(
            TaskWatcher.tenant_id == tenant_id,
            TaskWatcher.task_id == task_id,
        )
        result = await self.session.execute(statement)
        return [row[0] for row in result.all()]

    async def _require_checklist_item(
        self, tenant_id: UUID, task_id: UUID, item_id: UUID
    ) -> TaskChecklistItem:
        statement = select(TaskChecklistItem).where(
            TaskChecklistItem.tenant_id == tenant_id,
            TaskChecklistItem.task_id == task_id,
            TaskChecklistItem.id == item_id,
        )
        result = await self.session.execute(statement)
        row = result.scalar_one_or_none()
        if row is None:
            raise ResourceNotFoundError("Checklist item not found")
        return row

    async def _require_comment(
        self, tenant_id: UUID, task_id: UUID, comment_id: UUID
    ) -> TaskComment:
        statement = select(TaskComment).where(
            TaskComment.tenant_id == tenant_id,
            TaskComment.task_id == task_id,
            TaskComment.id == comment_id,
            TaskComment.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        row = result.scalar_one_or_none()
        if row is None:
            raise ResourceNotFoundError("Comment not found")
        return row

    async def _snapshot(self, tenant_id: UUID, row: Task) -> dict[str, object]:
        labels = await self._load_labels(tenant_id, row.id)
        watcher_ids = await self._load_watcher_ids(tenant_id, row.id)
        return {
            "task_number": row.task_number,
            "task_type": row.task_type,
            "title": row.title,
            "description": row.description,
            "status": row.status,
            "priority": row.priority,
            "due_at": row.due_at.isoformat() if row.due_at else None,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "assignee_id": str(row.assignee_id) if row.assignee_id else None,
            "parent_id": str(row.parent_id) if row.parent_id else None,
            "sort_order": row.sort_order,
            "related_entity_type": row.related_entity_type,
            "related_entity_id": str(row.related_entity_id) if row.related_entity_id else None,
            "label_ids": [str(label.id) for label in labels],
            "watcher_ids": [str(watcher_id) for watcher_id in watcher_ids],
        }
