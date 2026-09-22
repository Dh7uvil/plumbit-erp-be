"""Voucher queries."""

import builtins
from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.vouchers.models import Voucher, VoucherLine


class VoucherRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Voucher,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "document_number",
                    "voucher_date",
                    "status",
                    "total_amount",
                }
            ),
            allowed_filter_fields=frozenset(
                {
                    "status",
                    "voucher_type",
                    "currency_id",
                    "payment_method",
                }
            ),
            search_fields=frozenset({"document_number", "reference", "narration"}),
        )

    def _load_lines(self):
        return selectinload(Voucher.lines)

    async def get(
        self, tenant_id: UUID, voucher_id: UUID, *, for_update: bool = False
    ) -> Voucher | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(Voucher.id == voucher_id)
            .options(self._load_lines())
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[Voucher], int]:
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
            self._repo.base_query(tenant_id).where(Voucher.id.in_(ids)).options(self._load_lines())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Voucher:
        row = Voucher(tenant_id=tenant_id, **dict(values))
        self.session.add(row)
        await self.session.flush()
        return row

    async def replace_lines(
        self, tenant_id: UUID, voucher_id: UUID, lines: builtins.list[dict[str, object]]
    ) -> None:
        row = await self.get(tenant_id, voucher_id, for_update=True)
        if row is None:
            return
        row.lines.clear()
        await self.session.flush()
        for line_values in lines:
            row.lines.append(VoucherLine(tenant_id=tenant_id, voucher_id=voucher_id, **line_values))

    async def soft_delete(self, tenant_id: UUID, voucher_id: UUID) -> Voucher | None:
        return await self._repo.soft_delete(tenant_id, voucher_id)
