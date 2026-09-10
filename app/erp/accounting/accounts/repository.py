"""Chart of accounts queries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.accounts.models import Account


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Account,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "code", "name", "account_type", "depth"}
            ),
            allowed_filter_fields=frozenset(
                {"account_type", "account_subtype", "is_group", "is_active", "parent_id"}
            ),
            search_fields=frozenset({"code", "name", "description"}),
        )

    async def get(self, tenant_id: UUID, account_id: UUID) -> Account | None:
        return await self._repo.get(tenant_id, account_id)

    async def get_by_code(self, tenant_id: UUID, code: str) -> Account | None:
        statement = select(Account).where(
            Account.tenant_id == tenant_id,
            Account.code == code,
            Account.deleted_at.is_(None),
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_by_system_role(self, tenant_id: UUID, role: str) -> Account | None:
        statement = select(Account).where(
            Account.tenant_id == tenant_id,
            Account.system_role == role,
            Account.deleted_at.is_(None),
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Account], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def list_all(self, tenant_id: UUID) -> list[Account]:
        statement = (
            select(Account)
            .where(Account.tenant_id == tenant_id, Account.deleted_at.is_(None))
            .order_by(Account.code.asc())
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def count(self, tenant_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Account)
            .where(Account.tenant_id == tenant_id, Account.deleted_at.is_(None))
        )
        return int(await self.session.scalar(statement) or 0)

    async def count_children(self, tenant_id: UUID, parent_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Account)
            .where(
                Account.tenant_id == tenant_id,
                Account.parent_id == parent_id,
                Account.deleted_at.is_(None),
            )
        )
        return int(await self.session.scalar(statement) or 0)

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Account:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, account_id: UUID, values: Mapping[str, object]
    ) -> Account | None:
        return await self._repo.update(tenant_id, account_id, values)

    async def soft_delete(self, tenant_id: UUID, account_id: UUID) -> Account | None:
        return await self._repo.soft_delete(tenant_id, account_id)
