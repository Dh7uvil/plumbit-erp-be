"""Attachment parent-entity registry. Populated at wiring time from owning services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AttachmentEntityType
from app.core.exceptions import ValidationError

Probe = Callable[[AsyncSession, UUID, UUID], Awaitable["EntityRef"]]


@dataclass(frozen=True, slots=True)
class EntityRef:
    """Lightweight existence/posted probe result for an attachment parent."""

    exists: bool
    is_posted: bool = False


@dataclass(frozen=True, slots=True)
class AttachmentEntitySpec:
    entity_type: AttachmentEntityType
    read_permission: str
    write_permission: str
    probe: Probe


_REGISTRY: dict[AttachmentEntityType, AttachmentEntitySpec] = {}


def register(spec: AttachmentEntitySpec) -> None:
    _REGISTRY[spec.entity_type] = spec


def get_spec(entity_type: AttachmentEntityType) -> AttachmentEntitySpec | None:
    return _REGISTRY.get(entity_type)


def require_spec(entity_type: AttachmentEntityType) -> AttachmentEntitySpec:
    spec = get_spec(entity_type)
    if spec is None:
        raise ValidationError(
            "Attachments are not supported for this entity type",
            details={"entity_type": entity_type.value},
        )
    return spec


def clear() -> None:
    """Remove every spec. Intended for tests."""

    _REGISTRY.clear()
