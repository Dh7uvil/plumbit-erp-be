"""Per-record activity feed: audit rows scoped by entity type and permission."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.audit_repository import AuditLogRepository
from app.auth.models import User
from app.auth.org_repository import OrganizationRepository
from app.common.activity.entities import get_activity_spec
from app.common.activity.schemas import (
    ActivityChangedField,
    ActivityEntry,
    ActivityFilter,
    ActivityKind,
)
from app.common.models.audit_log import AuditLog
from app.common.schemas.pagination import PageParams
from app.common.services.audit import audit_field_changes
from app.core.exceptions import PermissionDeniedError, ValidationError
from app.core.permissions import has_permission

_APPROVAL_ACTIONS = frozenset({"SUBMIT", "APPROVE", "REJECT"})
_VISIBLE_METADATA_FIELDS = frozenset({"original_filename", "reason", "rejection_reason"})


class ActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AuditLogRepository(session)
        self.org = OrganizationRepository(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        filters: ActivityFilter,
        actor_permissions: frozenset[str],
    ) -> tuple[list[ActivityEntry], int]:
        spec = get_activity_spec(filters.entity_type)
        if spec is None:
            raise ValidationError(
                "Activity is not available for this entity type",
                details={"entity_type": filters.entity_type},
            )
        if not has_permission(actor_permissions, spec.read_permission):
            raise PermissionDeniedError()

        rows, total = await self.repo.list_logs(
            tenant_id,
            page=page,
            common_filter=filters,
            module=spec.module,
            entity_type=spec.entity_type,
            entity_id=filters.entity_id,
        )
        user_ids = [row.user_id for row in rows if row.user_id is not None]
        users = await self.org.get_users_by_ids(tenant_id, user_ids)
        return [self._to_entry(row, users, spec.changed_fields) for row in rows], total

    @staticmethod
    def _to_entry(
        row: AuditLog,
        users: dict[UUID, User],
        allowlist: frozenset[str],
    ) -> ActivityEntry:
        user = users.get(row.user_id) if row.user_id is not None else None
        old_values = _json_object(row.old_values)
        new_values = _json_object(row.new_values)
        kind = _classify_kind(row.action, old_values, new_values)
        visible = allowlist | _VISIBLE_METADATA_FIELDS
        changed = [
            ActivityChangedField(
                field=change["field"],
                old_value=change["old_value"],
                new_value=change["new_value"],
            )
            for change in audit_field_changes(old_values, new_values)
            if change["field"] in visible
        ]
        return ActivityEntry(
            action=row.action,
            actor_id=row.user_id,
            actor_name=user.name if user is not None else None,
            actor_email=user.email if user is not None else None,
            occurred_at=row.created_at,
            changed_fields=changed,
            status=row.status,
            kind=kind,
            summary=_entry_summary(kind, old_values, new_values),
        )


def _snapshot_text(values: dict[str, Any] | None, *keys: str) -> str | None:
    if not values:
        return None
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _classify_kind(
    action: str,
    old_values: dict[str, Any] | None,
    new_values: dict[str, Any] | None,
) -> ActivityKind:
    event_kind = _snapshot_text(new_values, "event_kind") or _snapshot_text(
        old_values, "event_kind"
    )
    filename = _snapshot_text(new_values, "original_filename") or _snapshot_text(
        old_values, "original_filename"
    )
    if event_kind == "attachment" or filename:
        return "attachment"
    if action in _APPROVAL_ACTIONS:
        return "approval"
    return "edit"


def _entry_summary(
    kind: ActivityKind,
    old_values: dict[str, Any] | None,
    new_values: dict[str, Any] | None,
) -> str | None:
    if kind == "attachment":
        return _snapshot_text(new_values, "original_filename") or _snapshot_text(
            old_values, "original_filename"
        )
    if kind == "approval":
        return _snapshot_text(new_values, "reason", "rejection_reason") or _snapshot_text(
            old_values, "reason", "rejection_reason"
        )
    return None


def _json_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None
