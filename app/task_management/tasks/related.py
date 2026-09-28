"""Registry-backed validation for polymorphic task links."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TaskRelatedEntityType
from app.core.exceptions import ResourceNotFoundError, ValidationError

Probe = Callable[[AsyncSession, UUID, UUID], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class TaskRelatedEntitySpec:
    entity_type: TaskRelatedEntityType
    probe: Probe


_REGISTRY: dict[TaskRelatedEntityType, TaskRelatedEntitySpec] = {}


def register(spec: TaskRelatedEntitySpec) -> None:
    _REGISTRY[spec.entity_type] = spec


def require_spec(entity_type: TaskRelatedEntityType) -> TaskRelatedEntitySpec:
    spec = _REGISTRY.get(entity_type)
    if spec is None:
        raise ValidationError(
            "Task linking is not supported for this entity type",
            details={"entity_type": entity_type.value},
        )
    return spec


async def assert_related_entity_exists(
    session: AsyncSession,
    tenant_id: UUID,
    related_entity_type: TaskRelatedEntityType,
    related_entity_id: UUID,
) -> None:
    spec = require_spec(related_entity_type)
    try:
        await spec.probe(session, tenant_id, related_entity_id)
    except ResourceNotFoundError as exc:
        raise ValidationError(f"Related {related_entity_type.value} was not found") from exc
