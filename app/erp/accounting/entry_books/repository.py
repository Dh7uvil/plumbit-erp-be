"""Entry book persistence."""

from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.entry_books.models import EntryBook


class EntryBookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID, entry_book_id: UUID) -> EntryBook | None:
        statement = select(EntryBook).where(
            EntryBook.tenant_id == tenant_id,
            EntryBook.id == entry_book_id,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_by_voucher_type(
        self, tenant_id: UUID, voucher_type: str
    ) -> EntryBook | None:
        statement = select(EntryBook).where(
            EntryBook.tenant_id == tenant_id,
            EntryBook.voucher_type == voucher_type,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        voucher_type: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[Sequence[EntryBook], int]:
        criteria = [EntryBook.tenant_id == tenant_id]
        if voucher_type is not None:
            criteria.append(EntryBook.voucher_type == voucher_type)
        if is_active is not None:
            criteria.append(EntryBook.is_active.is_(is_active))
        if common_filter and common_filter.search:
            term = f"%{common_filter.search.strip()}%"
            criteria.append(EntryBook.name.ilike(term))
        count_stmt = select(func.count()).select_from(EntryBook).where(*criteria)
        total = int((await self.session.execute(count_stmt)).scalar_one())
        allowed_sort = frozenset({"name", "voucher_type", "series_prefix"})
        sort_by = (
            common_filter.sort_by
            if common_filter and common_filter.sort_by in allowed_sort
            else "voucher_type"
        )
        sort_col = getattr(EntryBook, sort_by)
        if common_filter and common_filter.sort_order == "desc":
            sort_col = sort_col.desc()
        statement = (
            select(EntryBook)
            .where(*criteria)
            .order_by(sort_col)
            .offset(page.offset)
            .limit(page.page_size)
        )
        rows = (await self.session.execute(statement)).scalars().all()
        return rows, total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> EntryBook:
        row = EntryBook(tenant_id=tenant_id, id=uuid4(), **values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(
        self, tenant_id: UUID, entry_book_id: UUID, values: Mapping[str, object]
    ) -> EntryBook | None:
        row = await self.get(tenant_id, entry_book_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.flush()
        return row
