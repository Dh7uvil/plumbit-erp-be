"""Financial category persistence."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.financial_categories.models import FinancialCategory


class FinancialCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID, category_id: UUID) -> FinancialCategory | None:
        statement = select(FinancialCategory).where(
            FinancialCategory.tenant_id == tenant_id,
            FinancialCategory.id == category_id,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        account_type: str | None = None,
    ) -> tuple[Sequence[FinancialCategory], int]:
        criteria = [FinancialCategory.tenant_id == tenant_id]
        if account_type is not None:
            criteria.append(FinancialCategory.account_type == account_type)
        if common_filter and common_filter.search:
            term = f"%{common_filter.search.strip()}%"
            criteria.append(FinancialCategory.name.ilike(term))
        count_stmt = select(func.count()).select_from(FinancialCategory).where(*criteria)
        total = int((await self.session.execute(count_stmt)).scalar_one())
        allowed_sort = frozenset({"created_at", "updated_at", "name", "account_type"})
        sort_by = (
            common_filter.sort_by
            if common_filter and common_filter.sort_by in allowed_sort
            else "name"
        )
        sort_col = getattr(FinancialCategory, sort_by)
        if common_filter and common_filter.sort_order == "desc":
            sort_col = sort_col.desc()
        statement = (
            select(FinancialCategory)
            .where(*criteria)
            .order_by(sort_col)
            .offset(page.offset)
            .limit(page.page_size)
        )
        rows = (await self.session.execute(statement)).scalars().all()
        return rows, total

    async def create(
        self, tenant_id: UUID, values: Mapping[str, object]
    ) -> FinancialCategory:
        row = FinancialCategory(tenant_id=tenant_id, **values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(
        self, tenant_id: UUID, category_id: UUID, values: Mapping[str, object]
    ) -> FinancialCategory | None:
        row = await self.get(tenant_id, category_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.flush()
        return row

    async def delete(self, tenant_id: UUID, category_id: UUID) -> FinancialCategory | None:
        row = await self.get(tenant_id, category_id)
        if row is None:
            return None
        await self.session.delete(row)
        await self.session.flush()
        return row

