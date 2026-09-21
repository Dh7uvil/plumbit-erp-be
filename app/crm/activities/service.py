"""Activity use cases."""

from __future__ import annotations

import builtins
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.auth.catalog import ACTIVITY_DELETE, ACTIVITY_UPDATE, CRM_MODULE
from app.auth.models import User
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.datetime import utcnow
from app.core.enums import (
    ActivityPriority,
    ActivityStatus,
    ActivityType,
    AuditAction,
    CrmRelatedEntityType,
)
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.core.permissions import has_permission
from app.crm.activities.models import Activity
from app.crm.activities.repository import ActivityRepository
from app.crm.activities.schemas import (
    ActivityComplete,
    ActivityCreate,
    ActivityResponse,
    ActivityUpdate,
)
from app.crm.activities.workflow import (
    assert_complete_allowed,
    assert_editable,
    available_actions,
)
from app.crm.related import assert_related_entity_exists
from app.db.session import transaction


class ActivityService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
        repo: ActivityRepository | None = None,
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = repo or ActivityRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        related_entity_type: str | None = None,
        related_entity_id: UUID | None = None,
        owner_id: UUID | None = None,
        status: str | None = None,
        activity_type: str | None = None,
        overdue: bool | None = None,
        due_from: datetime | None = None,
        due_to: datetime | None = None,
    ) -> tuple[builtins.list[ActivityResponse], int]:
        filters: dict[str, object] = {}
        if related_entity_type is not None:
            filters["related_entity_type"] = related_entity_type
        if related_entity_id is not None:
            filters["related_entity_id"] = related_entity_id
        if owner_id is not None:
            filters["owner_id"] = owner_id
        if status is not None:
            filters["status"] = status
        if activity_type is not None:
            filters["activity_type"] = activity_type

        extra: list[ColumnElement[bool]] = []
        if overdue:
            extra.append(Activity.due_at.is_not(None))
            extra.append(Activity.due_at < utcnow())
            extra.append(Activity.status == ActivityStatus.OPEN.value)
        if due_from is not None:
            extra.append(Activity.due_at.is_not(None))
            extra.append(Activity.due_at >= due_from)
        if due_to is not None:
            extra.append(Activity.due_at.is_not(None))
            extra.append(Activity.due_at <= due_to)

        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, activity_id: UUID) -> ActivityResponse:
        return self._to_response(await self._require(tenant_id, activity_id))

    async def create(
        self, tenant_id: UUID, payload: ActivityCreate, *, actor_user_id: UUID
    ) -> ActivityResponse:
        async with transaction(self.session):
            await self._validate_related(
                tenant_id, payload.related_entity_type, payload.related_entity_id
            )
            if payload.owner_id is not None:
                await self._require_owner(tenant_id, payload.owner_id)
            values = payload.model_dump()
            values["activity_type"] = payload.activity_type.value
            values["priority"] = payload.priority.value
            values["related_entity_type"] = payload.related_entity_type.value
            values["status"] = ActivityStatus.OPEN.value
            values["duration_minutes"] = self._duration_minutes(payload)
            values["created_by"] = actor_user_id
            values["updated_by"] = actor_user_id
            row = await self.repo.create(tenant_id, values)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=CRM_MODULE,
                entity_type="activity",
                entity_id=row.id,
                new_values=self._snapshot(row),
            )
            return self._to_response(row)

    async def update(
        self,
        tenant_id: UUID,
        activity_id: UUID,
        payload: ActivityUpdate,
        *,
        actor_user_id: UUID,
    ) -> ActivityResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            existing = await self._require(tenant_id, activity_id)
            assert_editable(ActivityStatus(existing.status))
            old_values = self._snapshot(existing)
            if "related_entity_type" in values:
                if payload.related_entity_type is None or payload.related_entity_id is None:
                    raise ValidationError("related_entity_type and related_entity_id are required")
                await self._validate_related(
                    tenant_id, payload.related_entity_type, payload.related_entity_id
                )
                values["related_entity_type"] = payload.related_entity_type.value
            if "owner_id" in values and payload.owner_id is not None:
                await self._require_owner(tenant_id, payload.owner_id)
            if "activity_type" in values and payload.activity_type is not None:
                values["activity_type"] = payload.activity_type.value
            if "priority" in values and payload.priority is not None:
                values["priority"] = payload.priority.value
            if "status" in values and payload.status is not None:
                values["status"] = payload.status.value
            merged_start = values.get("start_at", existing.start_at)
            merged_end = values.get("end_at", existing.end_at)
            start_at = merged_start if isinstance(merged_start, datetime) else None
            end_at = merged_end if isinstance(merged_end, datetime) else None
            if start_at is not None and end_at is not None and end_at <= start_at:
                raise ValidationError("end_at must be after start_at")
            if "duration_minutes" not in values:
                values["duration_minutes"] = self._duration_from_bounds(
                    start_at, end_at, existing.duration_minutes
                )
            values["updated_by"] = actor_user_id
            row = await self.repo.update(tenant_id, activity_id, values)
            if row is None:
                raise ResourceNotFoundError("Activity not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="activity",
                entity_id=row.id,
                old_values=old_values,
                new_values=self._snapshot(row),
            )
            return self._to_response(row)

    async def complete(
        self,
        tenant_id: UUID,
        activity_id: UUID,
        payload: ActivityComplete,
        *,
        actor_user_id: UUID,
    ) -> ActivityResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, activity_id)
            status = ActivityStatus(existing.status)
            assert_complete_allowed(status)
            old_values = self._snapshot(existing)
            values: dict[str, object] = {
                "status": ActivityStatus.COMPLETED.value,
                "updated_by": actor_user_id,
            }
            if payload.outcome is not None:
                values["outcome"] = payload.outcome
            row = await self.repo.update(tenant_id, activity_id, values)
            if row is None:
                raise ResourceNotFoundError("Activity not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CONFIRM,
                module=CRM_MODULE,
                entity_type="activity",
                entity_id=row.id,
                old_values=old_values,
                new_values=self._snapshot(row),
            )
            return self._to_response(row)

    async def delete(
        self, tenant_id: UUID, activity_id: UUID, *, actor_user_id: UUID
    ) -> ActivityResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, activity_id)
            assert_editable(ActivityStatus(row.status))
            response = self._to_response(row)
            await self.repo.soft_delete(tenant_id, activity_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=CRM_MODULE,
                entity_type="activity",
                entity_id=activity_id,
                old_values=self._snapshot(row),
            )
            return response

    def _available_actions(self, status: ActivityStatus) -> builtins.list[str]:
        return available_actions(
            status,
            can_update=has_permission(self.actor_permissions, ACTIVITY_UPDATE),
            can_delete=has_permission(self.actor_permissions, ACTIVITY_DELETE),
        )

    def _to_response(self, row: Activity) -> ActivityResponse:
        return ActivityResponse.model_validate(row).model_copy(
            update={
                "activity_type": ActivityType(row.activity_type),
                "status": ActivityStatus(row.status),
                "priority": ActivityPriority(row.priority),
                "available_actions": self._available_actions(ActivityStatus(row.status)),
            }
        )

    async def _require(self, tenant_id: UUID, activity_id: UUID) -> Activity:
        row = await self.repo.get(tenant_id, activity_id)
        if row is None:
            raise ResourceNotFoundError("Activity not found")
        return row

    async def _require_owner(self, tenant_id: UUID, owner_id: UUID) -> None:
        statement = select(User.id).where(User.tenant_id == tenant_id, User.id == owner_id)
        result = await self.session.execute(statement)
        if result.scalar_one_or_none() is None:
            raise ValidationError("Owner not found")

    async def _validate_related(
        self,
        tenant_id: UUID,
        related_entity_type: CrmRelatedEntityType,
        related_entity_id: UUID,
    ) -> None:
        await assert_related_entity_exists(
            self.session, tenant_id, related_entity_type, related_entity_id
        )

    def _snapshot(self, row: Activity) -> dict[str, object]:
        return {
            "activity_type": row.activity_type,
            "subject": row.subject,
            "status": row.status,
            "priority": row.priority,
            "due_at": row.due_at.isoformat() if row.due_at else None,
            "start_at": row.start_at.isoformat() if row.start_at else None,
            "end_at": row.end_at.isoformat() if row.end_at else None,
            "duration_minutes": row.duration_minutes,
            "outcome": row.outcome,
            "owner_id": str(row.owner_id) if row.owner_id else None,
            "related_entity_type": row.related_entity_type,
            "related_entity_id": str(row.related_entity_id),
        }

    def _duration_minutes(self, payload: ActivityCreate) -> int | None:
        return self._duration_from_bounds(
            payload.start_at, payload.end_at, payload.duration_minutes
        )

    @staticmethod
    def _duration_from_bounds(
        start_at: datetime | None, end_at: datetime | None, fallback: int | None
    ) -> int | None:
        if start_at is not None and end_at is not None:
            return max(int((end_at - start_at).total_seconds() // 60), 0)
        return fallback
