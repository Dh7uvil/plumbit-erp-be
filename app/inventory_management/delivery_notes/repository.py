"""Delivery note queries."""

import builtins
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.inventory_management.delivery_notes.models import DeliveryNote, DeliveryNoteLine


class DeliveryNoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            DeliveryNote,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "document_number", "document_date", "status"}
            ),
            allowed_filter_fields=frozenset(
                {
                    "status",
                    "warehouse_id",
                    "customer_id",
                    "sales_order_id",
                    "shipment_id",
                    "branch_id",
                }
            ),
            search_fields=frozenset({"document_number", "notes", "vehicle_number", "driver_name"}),
        )

    def _with_lines(self) -> Any:
        return selectinload(DeliveryNote.lines)

    def has_product_clause(self, product_id: UUID) -> ColumnElement[bool]:
        return exists().where(
            DeliveryNoteLine.delivery_note_id == DeliveryNote.id,
            DeliveryNoteLine.product_id == product_id,
            DeliveryNoteLine.tenant_id == DeliveryNote.tenant_id,
        )

    async def get(
        self, tenant_id: UUID, note_id: UUID, *, for_update: bool = False
    ) -> DeliveryNote | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(DeliveryNote.id == note_id)
            .options(self._with_lines())
        )
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
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[DeliveryNote], int]:
        rows, total = await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria,
        )
        if not rows:
            return rows, total
        ids = [row.id for row in rows]
        statement = (
            self._repo.base_query(tenant_id)
            .where(DeliveryNote.id.in_(ids))
            .options(self._with_lines())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def list_for_sales_order(
        self, tenant_id: UUID, sales_order_id: UUID
    ) -> Sequence[DeliveryNote]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(DeliveryNote.sales_order_id == sales_order_id)
            .options(self._with_lines())
            .order_by(DeliveryNote.document_date, DeliveryNote.created_at)
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> DeliveryNote:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, note_id: UUID, values: Mapping[str, object]
    ) -> DeliveryNote | None:
        return await self._repo.update(tenant_id, note_id, values)

    async def soft_delete(self, tenant_id: UUID, note_id: UUID) -> DeliveryNote | None:
        return await self._repo.soft_delete(tenant_id, note_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        note_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[DeliveryNoteLine]:
        await self.session.execute(
            delete(DeliveryNoteLine).where(
                DeliveryNoteLine.tenant_id == tenant_id,
                DeliveryNoteLine.delivery_note_id == note_id,
            )
        )
        created: builtins.list[DeliveryNoteLine] = []
        for values in lines:
            row = DeliveryNoteLine(tenant_id=tenant_id, delivery_note_id=note_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created
