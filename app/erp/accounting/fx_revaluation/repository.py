"""FX revaluation queries."""

from __future__ import annotations

from builtins import list as _List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import FxRevaluationStatus
from app.erp.accounting.fx_revaluation.models import FxRevaluationLine, FxRevaluationRun


class FxRevaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            FxRevaluationRun,
            allowed_sort_fields=frozenset({"created_at", "as_of_date", "status"}),
            allowed_filter_fields=frozenset({"status"}),
            search_fields=frozenset({"notes"}),
        )

    async def get(
        self, tenant_id: UUID, run_id: UUID, *, for_update: bool = False
    ) -> FxRevaluationRun | None:
        statement = select(FxRevaluationRun).where(
            FxRevaluationRun.tenant_id == tenant_id,
            FxRevaluationRun.id == run_id,
            FxRevaluationRun.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self, tenant_id: UUID, *, page: PageParams, common_filter: BaseFilter | None = None
    ) -> tuple[_List[FxRevaluationRun], int]:
        rows, total = await self._repo.list(tenant_id, page=page, common_filter=common_filter)
        return list(rows), total

    async def open_run(self, tenant_id: UUID) -> FxRevaluationRun | None:
        statement = select(FxRevaluationRun).where(
            FxRevaluationRun.tenant_id == tenant_id,
            FxRevaluationRun.deleted_at.is_(None),
            FxRevaluationRun.status == FxRevaluationStatus.POSTED.value,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def create(self, tenant_id: UUID, values: dict[str, object]) -> FxRevaluationRun:
        return await self._repo.create(tenant_id, values)

    async def lines_for(self, tenant_id: UUID, run_id: UUID) -> _List[FxRevaluationLine]:
        statement = (
            select(FxRevaluationLine)
            .where(FxRevaluationLine.tenant_id == tenant_id, FxRevaluationLine.run_id == run_id)
            .order_by(FxRevaluationLine.exposure_kind, FxRevaluationLine.currency_id)
        )
        return list((await self.session.execute(statement)).scalars().all())
