"""Bank statement queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.bank_reconciliation.models import BankStatement, BankStatementLine


class BankStatementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            BankStatement,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "period_start", "period_end", "status"}
            ),
            allowed_filter_fields=frozenset({"bank_account_id", "status"}),
            search_fields=frozenset({"import_reference", "notes"}),
        )

    async def get(self, tenant_id: UUID, statement_id: UUID) -> BankStatement | None:
        statement = (
            select(BankStatement)
            .options(selectinload(BankStatement.lines))
            .where(
                BankStatement.tenant_id == tenant_id,
                BankStatement.id == statement_id,
                BankStatement.deleted_at.is_(None),
            )
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[BankStatement], int]:
        rows, total = await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )
        if not rows:
            return rows, total
        statement_ids = [row.id for row in rows]
        loaded = (
            (
                await self.session.execute(
                    select(BankStatement)
                    .options(selectinload(BankStatement.lines))
                    .where(
                        BankStatement.tenant_id == tenant_id,
                        BankStatement.id.in_(statement_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in loaded}
        return [by_id[row.id] for row in rows if row.id in by_id], total

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> BankStatement:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, statement_id: UUID, values: Mapping[str, object]
    ) -> BankStatement | None:
        return await self._repo.update(tenant_id, statement_id, values)

    async def soft_delete(self, tenant_id: UUID, statement_id: UUID) -> BankStatement | None:
        return await self._repo.soft_delete(tenant_id, statement_id)

    async def get_line(self, tenant_id: UUID, statement_line_id: UUID) -> BankStatementLine | None:
        statement = select(BankStatementLine).where(
            BankStatementLine.tenant_id == tenant_id,
            BankStatementLine.id == statement_line_id,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def matched_journal_line_ids(self, tenant_id: UUID) -> set[UUID]:
        statement = select(BankStatementLine.matched_journal_line_id).where(
            BankStatementLine.tenant_id == tenant_id,
            BankStatementLine.matched_journal_line_id.is_not(None),
            BankStatementLine.match_status == "MATCHED",
        )
        rows = (await self.session.execute(statement)).scalars().all()
        return {row for row in rows if row is not None}
