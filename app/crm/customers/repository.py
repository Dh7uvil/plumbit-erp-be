"""Customer queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.crm.customers.models import Customer, CustomerAddress


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Customer,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "code"}),
            allowed_filter_fields=frozenset(
                {
                    "tax_treatment",
                    "currency_id",
                    "is_active",
                    "company_type",
                    "default_price_list_id",
                }
            ),
            search_fields=frozenset({"name", "code", "trn"}),
        )
        self._addresses = BaseRepository(
            session,
            CustomerAddress,
            allowed_sort_fields=frozenset({"created_at", "updated_at"}),
            allowed_filter_fields=frozenset({"customer_id"}),
        )

    async def get(self, tenant_id: UUID, customer_id: UUID) -> Customer | None:
        return await self._repo.get(tenant_id, customer_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Customer], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Customer:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, customer_id: UUID, values: Mapping[str, object]
    ) -> Customer | None:
        return await self._repo.update(tenant_id, customer_id, values)

    async def soft_delete(self, tenant_id: UUID, customer_id: UUID) -> Customer | None:
        return await self._repo.soft_delete(tenant_id, customer_id)

    async def list_extra_addresses(
        self, tenant_id: UUID, customer_id: UUID
    ) -> Sequence[CustomerAddress]:
        statement = (
            select(CustomerAddress)
            .where(
                CustomerAddress.tenant_id == tenant_id,
                CustomerAddress.customer_id == customer_id,
                CustomerAddress.deleted_at.is_(None),
            )
            .order_by(CustomerAddress.created_at.asc())
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def get_extra_address(
        self, tenant_id: UUID, customer_id: UUID, extra_id: UUID
    ) -> CustomerAddress | None:
        statement = select(CustomerAddress).where(
            CustomerAddress.tenant_id == tenant_id,
            CustomerAddress.customer_id == customer_id,
            CustomerAddress.id == extra_id,
            CustomerAddress.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def create_extra_address(
        self, tenant_id: UUID, values: Mapping[str, object]
    ) -> CustomerAddress:
        return await self._addresses.create(tenant_id, values)

    async def soft_delete_extra_address(
        self, tenant_id: UUID, extra_id: UUID
    ) -> CustomerAddress | None:
        return await self._addresses.soft_delete(tenant_id, extra_id)
