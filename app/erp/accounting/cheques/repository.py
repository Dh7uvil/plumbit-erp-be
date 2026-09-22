"""Cheque queries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.accounting.cheques.models import Cheque


class ChequeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Cheque,
            allowed_sort_fields=frozenset(
                {
                    "created_at",
                    "updated_at",
                    "cheque_date",
                    "due_date",
                    "amount",
                    "status",
                    "cheque_number",
                }
            ),
            allowed_filter_fields=frozenset({"status", "direction", "bank_account_id", "party_id"}),
            search_fields=frozenset({"document_number", "cheque_number", "narration"}),
        )

    async def get(self, tenant_id: UUID, cheque_id: UUID) -> Cheque | None:
        return await self._repo.get(tenant_id, cheque_id)

    async def get_for_update(self, tenant_id: UUID, cheque_id: UUID) -> Cheque | None:
        statement = (
            select(Cheque)
            .where(
                Cheque.tenant_id == tenant_id,
                Cheque.id == cheque_id,
                Cheque.deleted_at.is_(None),
            )
            .with_for_update()
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        due_date_from: date | None = None,
        due_date_to: date | None = None,
    ) -> tuple[Sequence[Cheque], int]:
        extra_criteria = self._due_date_criteria(due_date_from, due_date_to)
        return await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria or None,
        )

    def _due_date_criteria(
        self, due_date_from: date | None, due_date_to: date | None
    ) -> Sequence[object]:
        clauses: list[object] = []
        if due_date_from is not None:
            clauses.append(Cheque.due_date >= due_date_from)
        if due_date_to is not None:
            clauses.append(Cheque.due_date <= due_date_to)
        return clauses

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Cheque:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, cheque_id: UUID, values: Mapping[str, object]
    ) -> Cheque | None:
        return await self._repo.update(tenant_id, cheque_id, values)

    async def soft_delete(self, tenant_id: UUID, cheque_id: UUID) -> Cheque | None:
        return await self._repo.soft_delete(tenant_id, cheque_id)
