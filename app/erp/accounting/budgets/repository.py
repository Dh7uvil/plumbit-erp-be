"""Budget queries."""

from __future__ import annotations

from builtins import list as _List
from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.budgets.models import Budget, BudgetLine


class BudgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Budget,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "name", "fiscal_year", "status"}
            ),
            allowed_filter_fields=frozenset({"status", "fiscal_year"}),
            search_fields=frozenset({"name", "notes"}),
        )

    async def get(
        self, tenant_id: UUID, budget_id: UUID, *, for_update: bool = False
    ) -> Budget | None:
        statement = select(Budget).where(
            Budget.tenant_id == tenant_id,
            Budget.id == budget_id,
            Budget.deleted_at.is_(None),
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
    ) -> tuple[Sequence[Budget], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Budget:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, budget_id: UUID, values: Mapping[str, object]
    ) -> Budget | None:
        return await self._repo.update(tenant_id, budget_id, values)

    async def soft_delete(self, tenant_id: UUID, budget_id: UUID) -> Budget | None:
        return await self._repo.soft_delete(tenant_id, budget_id)

    async def lines_for(self, tenant_id: UUID, budget_id: UUID) -> _List[BudgetLine]:
        statement = (
            select(BudgetLine)
            .where(BudgetLine.tenant_id == tenant_id, BudgetLine.budget_id == budget_id)
            .order_by(BudgetLine.period_start, BudgetLine.account_id)
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def replace_lines(
        self, tenant_id: UUID, budget_id: UUID, rows: _List[dict[str, object]]
    ) -> _List[BudgetLine]:
        await self.session.execute(
            delete(BudgetLine).where(
                BudgetLine.tenant_id == tenant_id, BudgetLine.budget_id == budget_id
            )
        )
        created: _List[BudgetLine] = []
        for values in rows:
            row = BudgetLine(tenant_id=tenant_id, budget_id=budget_id, **values)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created
