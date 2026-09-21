"""Pipeline and stage persistence."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.crm.pipelines.models import Pipeline, PipelineStage


class PipelineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Pipeline,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "name", "is_default", "is_active"}
            ),
            allowed_filter_fields=frozenset({"is_active", "is_default"}),
            search_fields=frozenset({"name"}),
        )

    async def get(self, tenant_id: UUID, pipeline_id: UUID) -> Pipeline | None:
        return await self._repo.get(tenant_id, pipeline_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Pipeline], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Pipeline:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, pipeline_id: UUID, values: Mapping[str, object]
    ) -> Pipeline | None:
        return await self._repo.update(tenant_id, pipeline_id, values)

    async def soft_delete(self, tenant_id: UUID, pipeline_id: UUID) -> Pipeline | None:
        return await self._repo.soft_delete(tenant_id, pipeline_id)

    async def clear_default_except(
        self, tenant_id: UUID, *, except_pipeline_id: UUID | None = None
    ) -> None:
        statement = (
            update(Pipeline)
            .where(
                Pipeline.tenant_id == tenant_id,
                Pipeline.is_default.is_(True),
                Pipeline.deleted_at.is_(None),
            )
            .values(is_default=False)
        )
        if except_pipeline_id is not None:
            statement = statement.where(Pipeline.id != except_pipeline_id)
        await self.session.execute(statement)


class PipelineStageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_pipeline(
        self, tenant_id: UUID, pipeline_id: UUID
    ) -> list[PipelineStage]:
        result = await self.session.execute(
            select(PipelineStage)
            .where(
                PipelineStage.tenant_id == tenant_id,
                PipelineStage.pipeline_id == pipeline_id,
            )
            .order_by(PipelineStage.sort_order.asc(), PipelineStage.name.asc())
        )
        return list(result.scalars().all())

    async def get(
        self, tenant_id: UUID, pipeline_id: UUID, stage_id: UUID
    ) -> PipelineStage | None:
        result = await self.session.execute(
            select(PipelineStage).where(
                PipelineStage.tenant_id == tenant_id,
                PipelineStage.pipeline_id == pipeline_id,
                PipelineStage.id == stage_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> PipelineStage:
        row = PipelineStage(tenant_id=tenant_id, **dict(values))
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def update(
        self,
        tenant_id: UUID,
        pipeline_id: UUID,
        stage_id: UUID,
        values: Mapping[str, object],
    ) -> PipelineStage | None:
        row = await self.get(tenant_id, pipeline_id, stage_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete(self, tenant_id: UUID, pipeline_id: UUID, stage_id: UUID) -> bool:
        row = await self.get(tenant_id, pipeline_id, stage_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True
