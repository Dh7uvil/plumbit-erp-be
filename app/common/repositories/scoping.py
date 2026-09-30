"""Record-level list scoping by role."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.core.enums import RecordScope
from app.crm.leads.models import Lead
from app.crm.opportunities.models import Opportunity
from app.task_management.tasks.models import Task

_SCOPE_RANK: dict[RecordScope, int] = {
    RecordScope.ALL: 0,
    RecordScope.BRANCH: 1,
    RecordScope.TEAM: 2,
    RecordScope.OWN: 3,
}

_OWNER_COLUMN: dict[type[Any], str] = {
    Lead: "owner_id",
    Opportunity: "owner_id",
    Task: "assignee_id",
}


@dataclass(frozen=True, slots=True)
class Actor:
    """Authenticated user with an effective record visibility scope."""

    user_id: UUID
    record_scope: RecordScope = RecordScope.ALL


def effective_record_scope(scopes: Sequence[str | RecordScope]) -> RecordScope:
    """Return the most permissive scope across a user's roles."""

    if not scopes:
        return RecordScope.ALL
    parsed = [RecordScope(scope) for scope in scopes]
    return min(parsed, key=lambda scope: _SCOPE_RANK[scope])


def _owner_column(model: type[Any]) -> InstrumentedAttribute[Any] | None:
    column_name = _OWNER_COLUMN.get(model)
    if column_name is None:
        return None
    column = getattr(model, column_name, None)
    if not isinstance(column, InstrumentedAttribute):
        return None
    return column


def record_scope_criteria(actor: Actor, model: type[Any]) -> list[ColumnElement[bool]]:
    """Build SQL criteria for ``extra_criteria`` repository filters."""

    if actor.record_scope != RecordScope.OWN:
        return []
    column = _owner_column(model)
    if column is None:
        return []
    return [column == actor.user_id]


def apply_record_scope(
    statement: Select[tuple[Any]],
    actor: Actor,
    model: type[Any],
) -> Select[tuple[Any]]:
    """Apply role record scope to a SQLAlchemy select."""

    for criterion in record_scope_criteria(actor, model):
        statement = statement.where(criterion)
    return statement
