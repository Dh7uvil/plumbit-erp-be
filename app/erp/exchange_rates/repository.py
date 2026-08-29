"""Currency and exchange-rate queries."""

from collections.abc import Mapping, Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.exchange_rates.models import Currency, ExchangeRate


class CurrencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Currency,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "code", "name"}),
            allowed_filter_fields=frozenset({"is_base", "is_active"}),
            search_fields=frozenset({"code", "name"}),
        )

    async def get(self, tenant_id: UUID, currency_id: UUID) -> Currency | None:
        return await self._repo.get(tenant_id, currency_id)

    async def get_by_code(self, tenant_id: UUID, code: str) -> Currency | None:
        statement = (
            select(Currency)
            .where(
                Currency.tenant_id == tenant_id,
                Currency.code == code,
                Currency.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_base(self, tenant_id: UUID) -> Currency | None:
        statement = (
            select(Currency)
            .where(
                Currency.tenant_id == tenant_id,
                Currency.is_base.is_(True),
                Currency.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Currency], int]:
        return await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Currency:
        return await self._repo.create(tenant_id, values)

    async def update(
        self,
        tenant_id: UUID,
        currency_id: UUID,
        values: Mapping[str, object],
    ) -> Currency | None:
        return await self._repo.update(tenant_id, currency_id, values)

    async def soft_delete(self, tenant_id: UUID, currency_id: UUID) -> Currency | None:
        return await self._repo.soft_delete(tenant_id, currency_id)

    async def clear_base_except(self, tenant_id: UUID, currency_id: UUID) -> None:
        statement = select(Currency).where(
            Currency.tenant_id == tenant_id,
            Currency.is_base.is_(True),
            Currency.id != currency_id,
            Currency.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        for row in result.scalars().all():
            row.is_base = False
        await self.session.flush()


class ExchangeRateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_pair_on_date(
        self,
        tenant_id: UUID,
        *,
        from_currency_id: UUID,
        to_currency_id: UUID,
        effective_date: date,
    ) -> ExchangeRate | None:
        statement = select(ExchangeRate).where(
            ExchangeRate.tenant_id == tenant_id,
            ExchangeRate.from_currency_id == from_currency_id,
            ExchangeRate.to_currency_id == to_currency_id,
            ExchangeRate.effective_date == effective_date,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_for_date(
        self,
        tenant_id: UUID,
        *,
        effective_date: date,
    ) -> Sequence[ExchangeRate]:
        statement = (
            select(ExchangeRate)
            .where(
                ExchangeRate.tenant_id == tenant_id,
                ExchangeRate.effective_date == effective_date,
            )
            .order_by(ExchangeRate.created_at.desc())
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> ExchangeRate:
        row = ExchangeRate(tenant_id=tenant_id)
        for name, value in values.items():
            setattr(row, name, value)
        self.session.add(row)
        await self.session.flush()
        return row
