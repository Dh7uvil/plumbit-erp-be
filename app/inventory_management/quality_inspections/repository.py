"""Quality inspection queries."""

import builtins
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import QualityInspectionStatus
from app.inventory_management.quality_inspections.models import (
    QualityInspection,
    QualityInspectionLine,
)


class QualityInspectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            QualityInspection,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "document_number", "inspection_date", "status"}
            ),
            allowed_filter_fields=frozenset({"status", "goods_receipt_id"}),
            search_fields=frozenset({"document_number", "notes"}),
        )

    def _with_lines(self) -> Any:
        return selectinload(QualityInspection.lines)

    async def get(
        self, tenant_id: UUID, inspection_id: UUID, *, for_update: bool = False
    ) -> QualityInspection | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(QualityInspection.id == inspection_id)
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
    ) -> tuple[Sequence[QualityInspection], int]:
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
            .where(QualityInspection.id.in_(ids))
            .options(self._with_lines())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def list_for_goods_receipt(
        self, tenant_id: UUID, goods_receipt_id: UUID
    ) -> Sequence[QualityInspection]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(QualityInspection.goods_receipt_id == goods_receipt_id)
            .options(self._with_lines())
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def has_approved_for_goods_receipt(self, tenant_id: UUID, goods_receipt_id: UUID) -> bool:
        statement = (
            self._repo.base_query(tenant_id)
            .where(
                QualityInspection.goods_receipt_id == goods_receipt_id,
                QualityInspection.status == QualityInspectionStatus.APPROVED.value,
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> QualityInspection:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, inspection_id: UUID, values: Mapping[str, object]
    ) -> QualityInspection | None:
        return await self._repo.update(tenant_id, inspection_id, values)

    async def soft_delete(self, tenant_id: UUID, inspection_id: UUID) -> QualityInspection | None:
        return await self._repo.soft_delete(tenant_id, inspection_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        inspection_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[QualityInspectionLine]:
        await self.session.execute(
            delete(QualityInspectionLine).where(
                QualityInspectionLine.tenant_id == tenant_id,
                QualityInspectionLine.quality_inspection_id == inspection_id,
            )
        )
        created: builtins.list[QualityInspectionLine] = []
        for values in lines:
            row = QualityInspectionLine(tenant_id=tenant_id, quality_inspection_id=inspection_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created
