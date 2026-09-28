"""Task label use cases."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import TASKS_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.db.session import transaction
from app.task_management.task_labels.models import TaskLabel
from app.task_management.task_labels.repository import TaskLabelRepository
from app.task_management.task_labels.schemas import (
    TaskLabelCreate,
    TaskLabelResponse,
    TaskLabelUpdate,
)


class TaskLabelService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TaskLabelRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[TaskLabelResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [TaskLabelResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, label_id: UUID) -> TaskLabelResponse:
        return TaskLabelResponse.model_validate(await self._require(tenant_id, label_id))

    async def create(
        self, tenant_id: UUID, payload: TaskLabelCreate, *, actor_user_id: UUID
    ) -> TaskLabelResponse:
        async with transaction(self.session):
            try:
                row = await self.repo.create(
                    tenant_id,
                    {
                        **payload.model_dump(),
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A label with this name already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=TASKS_MODULE,
                entity_type="task_label",
                entity_id=row.id,
                new_values=_label_snapshot(row),
            )
            return TaskLabelResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        label_id: UUID,
        payload: TaskLabelUpdate,
        *,
        actor_user_id: UUID,
    ) -> TaskLabelResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, label_id)
            old_values = _label_snapshot(existing)
            try:
                row = await self.repo.update(tenant_id, label_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A label with this name already exists") from exc
            if row is None:
                raise ResourceNotFoundError("Label not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=TASKS_MODULE,
                entity_type="task_label",
                entity_id=row.id,
                old_values=old_values,
                new_values=_label_snapshot(row),
            )
            return TaskLabelResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, label_id: UUID, *, actor_user_id: UUID
    ) -> TaskLabelResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, label_id)
            response = TaskLabelResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, label_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=TASKS_MODULE,
                entity_type="task_label",
                entity_id=label_id,
                old_values=_label_snapshot(row),
            )
            return response

    async def _require(self, tenant_id: UUID, label_id: UUID) -> TaskLabel:
        row = await self.repo.get(tenant_id, label_id)
        if row is None:
            raise ResourceNotFoundError("Label not found")
        return row


def _label_snapshot(row: TaskLabel) -> dict[str, object]:
    return {
        "name": row.name,
        "color": row.color,
        "is_active": row.is_active,
    }
