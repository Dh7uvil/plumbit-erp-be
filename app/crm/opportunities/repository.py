"""Opportunity persistence."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.crm.opportunities.models import Opportunity, OpportunityStageHistory


class OpportunityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Opportunity,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "opportunity_number",
                    "name",
                    "status",
                    "amount",
                    "expected_close_date",
                }
            ),
            allowed_filter_fields=frozenset(
                {
                    "status",
                    "pipeline_id",
                    "stage_id",
                    "owner_id",
                    "customer_id",
                    "source_id",
                }
            ),
            search_fields=frozenset({"opportunity_number", "name"}),
        )

    async def get(
        self, tenant_id: UUID, opportunity_id: UUID, *, for_update: bool = False
    ) -> Opportunity | None:
        statement = self._repo.base_query(tenant_id).where(Opportunity.id == opportunity_id)
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
    ) -> tuple[Sequence[Opportunity], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Opportunity:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, opportunity_id: UUID, values: Mapping[str, object]
    ) -> Opportunity | None:
        return await self._repo.update(tenant_id, opportunity_id, values)

    async def soft_delete(self, tenant_id: UUID, opportunity_id: UUID) -> Opportunity | None:
        return await self._repo.soft_delete(tenant_id, opportunity_id)


class OpportunityStageHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest_for_opportunity(
        self, tenant_id: UUID, opportunity_id: UUID
    ) -> OpportunityStageHistory | None:
        result = await self.session.execute(
            select(OpportunityStageHistory)
            .where(
                OpportunityStageHistory.tenant_id == tenant_id,
                OpportunityStageHistory.opportunity_id == opportunity_id,
            )
            .order_by(OpportunityStageHistory.changed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def append(
        self,
        tenant_id: UUID,
        *,
        opportunity_id: UUID,
        from_stage_id: UUID | None,
        to_stage_id: UUID,
        changed_by: UUID | None,
        changed_at: datetime,
        duration_days: int | None,
    ) -> OpportunityStageHistory:
        row = OpportunityStageHistory(
            tenant_id=tenant_id,
            opportunity_id=opportunity_id,
            from_stage_id=from_stage_id,
            to_stage_id=to_stage_id,
            changed_by=changed_by,
            changed_at=changed_at,
            duration_days=duration_days,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row
