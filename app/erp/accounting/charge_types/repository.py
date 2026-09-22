"""Charge type queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.charge_types.models import ChargeType


class ChargeTypeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            ChargeType,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "name", "code", "sort_order", "is_active"}
            ),
            allowed_filter_fields=frozenset({"is_active", "applies_to"}),
            search_fields=frozenset({"name", "code"}),
        )

    async def get(self, tenant_id: UUID, charge_type_id: UUID) -> ChargeType | None:
        return await self._repo.get(tenant_id, charge_type_id)

    async def get_by_code(self, tenant_id: UUID, code: str) -> ChargeType | None:
        statement = select(ChargeType).where(
            ChargeType.tenant_id == tenant_id,
            ChargeType.code == code,
            ChargeType.deleted_at.is_(None),
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[ChargeType], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> ChargeType:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, charge_type_id: UUID, values: Mapping[str, object]
    ) -> ChargeType | None:
        return await self._repo.update(tenant_id, charge_type_id, values)

    async def soft_delete(self, tenant_id: UUID, charge_type_id: UUID) -> ChargeType | None:
        return await self._repo.soft_delete(tenant_id, charge_type_id)
