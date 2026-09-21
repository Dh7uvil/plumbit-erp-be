"""Campaign persistence."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.crm.campaigns.models import Campaign, CampaignMember


class CampaignRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Campaign,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "name",
                    "status",
                    "campaign_type",
                    "start_date",
                    "end_date",
                }
            ),
            allowed_filter_fields=frozenset({"status", "campaign_type", "owner_id"}),
            search_fields=frozenset({"name"}),
        )

    async def get(self, tenant_id: UUID, campaign_id: UUID) -> Campaign | None:
        return await self._repo.get(tenant_id, campaign_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[Campaign], int]:
        return await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria,
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Campaign:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, campaign_id: UUID, values: Mapping[str, object]
    ) -> Campaign | None:
        return await self._repo.update(tenant_id, campaign_id, values)

    async def soft_delete(self, tenant_id: UUID, campaign_id: UUID) -> Campaign | None:
        return await self._repo.soft_delete(tenant_id, campaign_id)


class CampaignMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, tenant_id: UUID, campaign_id: UUID, member_id: UUID
    ) -> CampaignMember | None:
        result = await self.session.execute(
            select(CampaignMember).where(
                CampaignMember.tenant_id == tenant_id,
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.id == member_id,
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        campaign_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[Sequence[CampaignMember], int]:
        criteria = (
            CampaignMember.tenant_id == tenant_id,
            CampaignMember.campaign_id == campaign_id,
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(CampaignMember).where(*criteria)
            )
            or 0
        )
        result = await self.session.execute(
            select(CampaignMember)
            .where(*criteria)
            .order_by(CampaignMember.created_at.desc())
            .offset(page.offset)
            .limit(page.page_size)
        )
        return list(result.scalars().all()), total

    async def count(self, tenant_id: UUID, campaign_id: UUID) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(CampaignMember)
            .where(
                CampaignMember.tenant_id == tenant_id,
                CampaignMember.campaign_id == campaign_id,
            )
        )
        return int(value or 0)

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> CampaignMember:
        row = CampaignMember(tenant_id=tenant_id, **dict(values))
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def update(
        self,
        tenant_id: UUID,
        campaign_id: UUID,
        member_id: UUID,
        values: Mapping[str, object],
    ) -> CampaignMember | None:
        row = await self.get(tenant_id, campaign_id, member_id)
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete(self, tenant_id: UUID, campaign_id: UUID, member_id: UUID) -> bool:
        row = await self.get(tenant_id, campaign_id, member_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def delete_for_campaign(self, tenant_id: UUID, campaign_id: UUID) -> None:
        await self.session.execute(
            delete(CampaignMember).where(
                CampaignMember.tenant_id == tenant_id,
                CampaignMember.campaign_id == campaign_id,
            )
        )
