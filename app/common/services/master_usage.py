"""Reference checks for soft-deleted master records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Column, Table, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.db.base import Base


async def assert_master_not_referenced(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    table_name: str,
    record_id: UUID,
    label: str,
    action: str = "delete",
    exclude_tables: frozenset[str] = frozenset(),
) -> None:
    """Reject destructive master changes when live tenant rows still reference the record."""

    blockers: list[str] = []
    target_table = Base.metadata.tables[table_name]
    for table in Base.metadata.sorted_tables:
        if table.name == table_name or table.name in exclude_tables:
            continue
        foreign_key_columns = [
            column
            for column in table.columns
            for foreign_key in column.foreign_keys
            if foreign_key.column.table is target_table and foreign_key.column.name == "id"
        ]
        if not foreign_key_columns or "tenant_id" not in table.columns:
            continue
        if await _has_reference(session, table, tenant_id, record_id, foreign_key_columns):
            blockers.append(table.name)
    if blockers:
        refs = ", ".join(sorted(blockers)[:5])
        suffix = "" if len(blockers) <= 5 else f", and {len(blockers) - 5} more"
        raise ValidationError(f"Cannot {action} {label}; it is referenced by {refs}{suffix}")


async def _has_reference(
    session: AsyncSession,
    table: Table,
    tenant_id: UUID,
    record_id: UUID,
    foreign_key_columns: list[Column],
) -> bool:
    criteria = [
        table.c.tenant_id == tenant_id,
        or_(*(column == record_id for column in foreign_key_columns)),
    ]
    if "deleted_at" in table.columns:
        criteria.append(table.c.deleted_at.is_(None))
    statement = select(func.count()).select_from(table).where(and_(*criteria)).limit(1)
    return bool(await session.scalar(statement))
