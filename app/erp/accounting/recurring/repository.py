"""Recurring template queries."""

from __future__ import annotations

from builtins import list as _List
from collections.abc import Mapping, Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import RecurringTemplateStatus
from app.erp.accounting.recurring.models import RecurringGeneration, RecurringTemplate


class RecurringRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            RecurringTemplate,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "name", "next_run_date", "status"}
            ),
            allowed_filter_fields=frozenset({"status", "document_kind"}),
            search_fields=frozenset({"name", "notes"}),
        )

    async def get(
        self, tenant_id: UUID, template_id: UUID, *, for_update: bool = False
    ) -> RecurringTemplate | None:
        statement = select(RecurringTemplate).where(
            RecurringTemplate.tenant_id == tenant_id,
            RecurringTemplate.id == template_id,
            RecurringTemplate.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[RecurringTemplate], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> RecurringTemplate:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, template_id: UUID, values: Mapping[str, object]
    ) -> RecurringTemplate | None:
        return await self._repo.update(tenant_id, template_id, values)

    async def soft_delete(self, tenant_id: UUID, template_id: UUID) -> RecurringTemplate | None:
        return await self._repo.soft_delete(tenant_id, template_id)

    async def generations_for(
        self, tenant_id: UUID, template_id: UUID
    ) -> _List[RecurringGeneration]:
        statement = (
            select(RecurringGeneration)
            .where(
                RecurringGeneration.tenant_id == tenant_id,
                RecurringGeneration.template_id == template_id,
            )
            .order_by(RecurringGeneration.run_date.desc())
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def generation_for_run(
        self, tenant_id: UUID, template_id: UUID, run_date: date
    ) -> RecurringGeneration | None:
        statement = select(RecurringGeneration).where(
            RecurringGeneration.tenant_id == tenant_id,
            RecurringGeneration.template_id == template_id,
            RecurringGeneration.run_date == run_date,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def due_for_tenant(self, tenant_id: UUID, on_or_before: date) -> _List[RecurringTemplate]:
        statement = select(RecurringTemplate).where(
            RecurringTemplate.tenant_id == tenant_id,
            RecurringTemplate.deleted_at.is_(None),
            RecurringTemplate.status == RecurringTemplateStatus.ACTIVE.value,
            RecurringTemplate.next_run_date <= on_or_before,
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def due_templates(self, on_or_before: date) -> _List[RecurringTemplate]:
        statement = select(RecurringTemplate).where(
            RecurringTemplate.deleted_at.is_(None),
            RecurringTemplate.status == RecurringTemplateStatus.ACTIVE.value,
            RecurringTemplate.next_run_date <= on_or_before,
        )
        return list((await self.session.execute(statement)).scalars().all())
