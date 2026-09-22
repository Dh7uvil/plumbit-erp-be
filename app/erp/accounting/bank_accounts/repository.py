"""Bank account queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.bank_accounts.models import BankAccount


class BankAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            BankAccount,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "account_name", "bank_name", "is_active"}
            ),
            allowed_filter_fields=frozenset({"is_active", "currency_id"}),
            search_fields=frozenset({"account_name", "bank_name", "account_number", "iban"}),
        )

    async def get(self, tenant_id: UUID, bank_account_id: UUID) -> BankAccount | None:
        return await self._repo.get(tenant_id, bank_account_id)

    async def get_by_account_id(self, tenant_id: UUID, account_id: UUID) -> BankAccount | None:
        statement = select(BankAccount).where(
            BankAccount.tenant_id == tenant_id,
            BankAccount.account_id == account_id,
            BankAccount.deleted_at.is_(None),
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[BankAccount], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> BankAccount:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, bank_account_id: UUID, values: Mapping[str, object]
    ) -> BankAccount | None:
        return await self._repo.update(tenant_id, bank_account_id, values)

    async def soft_delete(self, tenant_id: UUID, bank_account_id: UUID) -> BankAccount | None:
        return await self._repo.soft_delete(tenant_id, bank_account_id)
