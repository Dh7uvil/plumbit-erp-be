"""Journal entry queries."""

import builtins
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine


class JournalEntryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            JournalEntry,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "document_number", "entry_date", "status"}
            ),
            allowed_filter_fields=frozenset(
                {"status", "journal_type", "branch_id", "currency_id"}
            ),
            search_fields=frozenset({"document_number", "narration", "reference"}),
        )

    def _with_lines(self) -> Any:
        return selectinload(JournalEntry.lines)

    def has_account_clause(self, account_id: UUID) -> ColumnElement[bool]:
        return exists().where(
            JournalEntryLine.journal_entry_id == JournalEntry.id,
            JournalEntryLine.account_id == account_id,
            JournalEntryLine.tenant_id == JournalEntry.tenant_id,
        )

    def has_party_clause(self, party_id: UUID) -> ColumnElement[bool]:
        return exists().where(
            JournalEntryLine.journal_entry_id == JournalEntry.id,
            JournalEntryLine.party_id == party_id,
            JournalEntryLine.tenant_id == JournalEntry.tenant_id,
        )

    async def get(
        self, tenant_id: UUID, journal_id: UUID, *, for_update: bool = False
    ) -> JournalEntry | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(JournalEntry.id == journal_id)
            .options(self._with_lines())
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_posted_for_source(
        self, tenant_id: UUID, source_type: str, source_id: UUID
    ) -> JournalEntry | None:
        statement = (
            select(JournalEntry)
            .where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.source_type == source_type,
                JournalEntry.source_id == source_id,
                JournalEntry.status == "POSTED",
                JournalEntry.deleted_at.is_(None),
            )
            .options(self._with_lines())
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[JournalEntry], int]:
        rows, total = await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria,
        )
        if not rows:
            return rows, total
        ids = [row.id for row in rows]
        statement = (
            self._repo.base_query(tenant_id)
            .where(JournalEntry.id.in_(ids))
            .options(self._with_lines())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> JournalEntry:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, journal_id: UUID, values: Mapping[str, object]
    ) -> JournalEntry | None:
        return await self._repo.update(tenant_id, journal_id, values)

    async def soft_delete(self, tenant_id: UUID, journal_id: UUID) -> JournalEntry | None:
        return await self._repo.soft_delete(tenant_id, journal_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        journal_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[JournalEntryLine]:
        await self.session.execute(
            delete(JournalEntryLine).where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntryLine.journal_entry_id == journal_id,
            )
        )
        created: builtins.list[JournalEntryLine] = []
        for values in lines:
            row = JournalEntryLine(tenant_id=tenant_id, journal_entry_id=journal_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created
