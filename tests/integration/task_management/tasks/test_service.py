"""Integration tests for task service."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth.catalog import (
    TASK_ASSIGN,
    TASK_MOVE,
    TASK_UPDATE,
)
from app.auth.models import User
from app.common.schemas.pagination import PageParams
from app.core.enums import TaskStatus
from app.db.session import async_session_factory
from app.task_management.task_labels.schemas import TaskLabelCreate
from app.task_management.task_labels.service import TaskLabelService
from app.task_management.tasks.schemas import (
    TaskAssign,
    TaskCreate,
    TaskLabelSet,
    TaskMove,
    TaskWatcherSet,
)
from app.task_management.tasks.service import TaskService
from tests.conftest import provision_admin


@pytest.mark.asyncio
async def test_task_move_assign_labels_and_watchers() -> None:
    tenant_id, _email, _password = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    permissions = frozenset({TASK_UPDATE, TASK_MOVE, TASK_ASSIGN})
    async with async_session_factory() as session:
        actor_user_id = (
            await session.execute(select(User.id).where(User.tenant_id == tenant_uuid).limit(1))
        ).scalar_one()
        label = await TaskLabelService(session).create(
            tenant_uuid,
            TaskLabelCreate(name="Integration", color="blue"),
            actor_user_id=actor_user_id,
        )
        service = TaskService(session, actor_permissions=permissions)
        created = await service.create(
            tenant_uuid,
            TaskCreate(title="Ship release"),
            actor_user_id=actor_user_id,
        )
        assert created.status is TaskStatus.TODO
        assert created.sort_order == 0
        assert "move:IN_PROGRESS" in created.available_actions

        moved = await service.move(
            tenant_uuid,
            created.id,
            TaskMove(status=TaskStatus.IN_PROGRESS, sort_order=0),
            actor_user_id=actor_user_id,
        )
        assert moved.status is TaskStatus.IN_PROGRESS
        assert moved.started_at is not None

        assigned = await service.assign(
            tenant_uuid,
            created.id,
            TaskAssign(assignee_id=actor_user_id),
            actor_user_id=actor_user_id,
        )
        assert assigned.assignee_id == actor_user_id

        labeled = await service.set_labels(
            tenant_uuid,
            created.id,
            TaskLabelSet(label_ids=[label.id]),
            actor_user_id=actor_user_id,
        )
        assert len(labeled.labels) == 1
        assert labeled.labels[0].id == label.id

        watched = await service.set_watchers(
            tenant_uuid,
            created.id,
            TaskWatcherSet(watcher_ids=[actor_user_id]),
            actor_user_id=actor_user_id,
        )
        assert watched.watcher_ids == [actor_user_id]

        mine, total = await service.list(
            tenant_uuid,
            page=PageParams(page=1, page_size=25),
            assignee_id=actor_user_id,
        )
        assert total == 1
        assert mine[0].id == created.id

        done = await service.move(
            tenant_uuid,
            created.id,
            TaskMove(status=TaskStatus.DONE, sort_order=0),
            actor_user_id=actor_user_id,
        )
        assert done.status is TaskStatus.DONE
        assert done.completed_at is not None

        reopened = await service.assign(
            tenant_uuid,
            created.id,
            TaskAssign(assignee_id=None),
            actor_user_id=actor_user_id,
        )
        assert reopened.assignee_id is None

        back_to_review = await service.move(
            tenant_uuid,
            created.id,
            TaskMove(status=TaskStatus.IN_REVIEW, sort_order=0),
            actor_user_id=actor_user_id,
        )
        assert back_to_review.status is TaskStatus.IN_REVIEW
        assert back_to_review.completed_at is None
