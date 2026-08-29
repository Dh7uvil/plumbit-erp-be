"""Contact queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.crm.contacts.models import Contact


class ContactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Contact,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name"}),
            allowed_filter_fields=frozenset({"customer_id", "is_primary", "is_active"}),
            search_fields=frozenset({"name", "email", "phone"}),
        )

    async def get(self, tenant_id: UUID, contact_id: UUID) -> Contact | None:
        return await self._repo.get(tenant_id, contact_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Contact], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Contact:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, contact_id: UUID, values: Mapping[str, object]
    ) -> Contact | None:
        return await self._repo.update(tenant_id, contact_id, values)

    async def soft_delete(self, tenant_id: UUID, contact_id: UUID) -> Contact | None:
        return await self._repo.soft_delete(tenant_id, contact_id)

    async def get_primary(self, tenant_id: UUID, customer_id: UUID) -> Contact | None:
        statement = (
            select(Contact)
            .where(
                Contact.tenant_id == tenant_id,
                Contact.customer_id == customer_id,
                Contact.is_primary.is_(True),
                Contact.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def clear_other_primaries(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        *,
        keep_id: UUID | None = None,
    ) -> None:
        criteria = [
            Contact.tenant_id == tenant_id,
            Contact.customer_id == customer_id,
            Contact.is_primary.is_(True),
            Contact.deleted_at.is_(None),
        ]
        if keep_id is not None:
            criteria.append(Contact.id != keep_id)
        result = await self.session.execute(select(Contact).where(*criteria))
        for row in result.scalars().all():
            row.is_primary = False
        await self.session.flush()
