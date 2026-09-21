"""Lead persistence."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.crm.leads.models import Lead


class LeadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Lead,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "lead_number",
                    "status",
                    "first_name",
                    "last_name",
                    "company_name",
                }
            ),
            allowed_filter_fields=frozenset(
                {"status", "source_id", "owner_id", "rating", "campaign_id"}
            ),
            search_fields=frozenset(
                {
                    "lead_number",
                    "first_name",
                    "last_name",
                    "company_name",
                    "email",
                    "phone",
                }
            ),
        )

    async def get(self, tenant_id: UUID, lead_id: UUID, *, for_update: bool = False) -> Lead | None:
        statement = self._repo.base_query(tenant_id).where(Lead.id == lead_id)
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
    ) -> tuple[Sequence[Lead], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Lead:
        return await self._repo.create(tenant_id, values)

    async def count_for_campaign(
        self, tenant_id: UUID, campaign_id: UUID, *, status: str | None = None
    ) -> int:
        criteria = [
            Lead.tenant_id == tenant_id,
            Lead.campaign_id == campaign_id,
            Lead.deleted_at.is_(None),
        ]
        if status is not None:
            criteria.append(Lead.status == status)
        value = await self.session.scalar(select(func.count()).select_from(Lead).where(*criteria))
        return int(value or 0)

    async def update(
        self, tenant_id: UUID, lead_id: UUID, values: Mapping[str, object]
    ) -> Lead | None:
        return await self._repo.update(tenant_id, lead_id, values)

    async def soft_delete(self, tenant_id: UUID, lead_id: UUID) -> Lead | None:
        return await self._repo.soft_delete(tenant_id, lead_id)
