"""Package queries."""

import builtins
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import PackageStatus
from app.inventory_management.packages.models import Package, PackageLine

_ZERO = Decimal("0")


class PackageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            Package,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "document_number", "status"}
            ),
            allowed_filter_fields=frozenset({"status", "sales_order_id", "delivery_note_id"}),
            search_fields=frozenset(
                {"document_number", "package_number", "notes", "shipping_marks"}
            ),
        )

    def _with_lines(self) -> Any:
        return selectinload(Package.lines)

    async def get(
        self, tenant_id: UUID, package_id: UUID, *, for_update: bool = False
    ) -> Package | None:
        statement = (
            self._repo.base_query(tenant_id)
            .where(Package.id == package_id)
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
    ) -> tuple[Sequence[Package], int]:
        rows, total = await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )
        if not rows:
            return rows, total
        ids = [row.id for row in rows]
        statement = (
            self._repo.base_query(tenant_id).where(Package.id.in_(ids)).options(self._with_lines())
        )
        loaded = {item.id: item for item in (await self.session.execute(statement)).scalars().all()}
        ordered = [loaded[row.id] for row in rows if row.id in loaded]
        return ordered, total

    async def list_for_sales_order(
        self, tenant_id: UUID, sales_order_id: UUID
    ) -> Sequence[Package]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(Package.sales_order_id == sales_order_id)
            .options(self._with_lines())
            .order_by(Package.created_at)
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def list_for_delivery_note(
        self, tenant_id: UUID, delivery_note_id: UUID
    ) -> Sequence[Package]:
        statement = (
            self._repo.base_query(tenant_id)
            .where(Package.delivery_note_id == delivery_note_id)
            .options(self._with_lines())
            .order_by(Package.created_at)
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def packed_qty_by_sales_order_line(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        *,
        exclude_package_id: UUID | None = None,
    ) -> dict[UUID, Decimal]:
        statement = (
            select(
                PackageLine.sales_order_line_id,
                func.coalesce(func.sum(PackageLine.quantity), 0),
            )
            .join(Package, Package.id == PackageLine.package_id)
            .where(
                Package.tenant_id == tenant_id,
                Package.sales_order_id == sales_order_id,
                Package.deleted_at.is_(None),
                Package.status != PackageStatus.CANCELLED.value,
                PackageLine.tenant_id == tenant_id,
            )
        )
        if exclude_package_id is not None:
            statement = statement.where(Package.id != exclude_package_id)
        statement = statement.group_by(PackageLine.sales_order_line_id)
        result = await self.session.execute(statement)
        packed: dict[UUID, Decimal] = {}
        for line_id, qty in result.all():
            packed[line_id] = qty if isinstance(qty, Decimal) else Decimal(str(qty or 0))
        return packed

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> Package:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, package_id: UUID, values: Mapping[str, object]
    ) -> Package | None:
        return await self._repo.update(tenant_id, package_id, values)

    async def soft_delete(self, tenant_id: UUID, package_id: UUID) -> Package | None:
        return await self._repo.soft_delete(tenant_id, package_id)

    async def replace_lines(
        self,
        tenant_id: UUID,
        package_id: UUID,
        lines: Sequence[Mapping[str, object]],
    ) -> builtins.list[PackageLine]:
        await self.session.execute(
            delete(PackageLine).where(
                PackageLine.tenant_id == tenant_id,
                PackageLine.package_id == package_id,
            )
        )
        created: builtins.list[PackageLine] = []
        for values in lines:
            row = PackageLine(tenant_id=tenant_id, package_id=package_id)
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created
