"""Generic, tenant-isolated async repository primitives."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.utils.datetime import utcnow
from app.db.base import Base


class BaseRepository[ModelT: Base]:
    """Database-only operations for tenant-owned, soft-deletable models."""

    _immutable_fields = frozenset({"id", "tenant_id", "created_at", "updated_at", "deleted_at"})

    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelT],
        *,
        allowed_sort_fields: frozenset[str],
        allowed_filter_fields: frozenset[str] = frozenset(),
        search_fields: frozenset[str] = frozenset(),
    ) -> None:
        """Configure the model and its public query allowlists."""

        self.session = session
        self.model = model
        self.allowed_sort_fields = allowed_sort_fields
        self.allowed_filter_fields = allowed_filter_fields
        self.search_fields = search_fields

        for required_field in ("id", "tenant_id", "deleted_at"):
            self._column(required_field)
        for field in allowed_sort_fields | allowed_filter_fields | search_fields:
            self._column(field)

    def _column(self, name: str) -> InstrumentedAttribute[Any]:
        column = getattr(self.model, name, None)
        if not isinstance(column, InstrumentedAttribute):
            msg = f"{self.model.__name__} has no mapped column {name!r}"
            raise TypeError(msg)
        return column

    @staticmethod
    def _set_attribute(entity: ModelT, name: str, value: object) -> None:
        setattr(entity, name, value)

    def _criteria(
        self,
        tenant_id: UUID,
        *,
        filters: Mapping[str, object] | None = None,
        common_filter: BaseFilter | None = None,
    ) -> list[ColumnElement[bool]]:
        criteria: list[ColumnElement[bool]] = [
            self._column("tenant_id") == tenant_id,
            self._column("deleted_at").is_(None),
        ]

        if filters:
            unknown = filters.keys() - self.allowed_filter_fields
            if unknown:
                fields = ", ".join(sorted(unknown))
                msg = f"filter fields are not allowed: {fields}"
                raise ValueError(msg)
            criteria.extend(self._column(name) == value for name, value in filters.items())

        if common_filter is not None:
            if common_filter.date_from is not None:
                criteria.append(self._column("created_at") >= common_filter.date_from)
            if common_filter.date_to is not None:
                criteria.append(self._column("created_at") <= common_filter.date_to)
            if common_filter.search is not None:
                if not self.search_fields:
                    msg = "search is not supported by this repository"
                    raise ValueError(msg)
                search_term = f"%{common_filter.search}%"
                criteria.append(
                    or_(*(self._column(field).ilike(search_term) for field in self.search_fields))
                )

        return criteria

    def base_query(self, tenant_id: UUID) -> Select[tuple[ModelT]]:
        """Build the mandatory tenant and soft-delete scoped query."""

        return select(self.model).where(*self._criteria(tenant_id))

    async def get(self, tenant_id: UUID, entity_id: UUID) -> ModelT | None:
        """Return one visible entity from the tenant, if it exists."""

        statement = self.base_query(tenant_id).where(self._column("id") == entity_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[ModelT], int]:
        """Return one bounded, allowlist-sorted page and its total count."""

        criteria = self._criteria(
            tenant_id,
            filters=filters,
            common_filter=common_filter,
        )
        sort_by = common_filter.sort_by if common_filter else "created_at"
        sort_order = common_filter.sort_order if common_filter else "desc"
        if sort_by not in self.allowed_sort_fields:
            msg = f"sort field is not allowed: {sort_by}"
            raise ValueError(msg)

        sort_column = self._column(sort_by)
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        statement = (
            select(self.model)
            .where(*criteria)
            .order_by(ordering)
            .offset(page.offset)
            .limit(page.page_size)
        )
        count_statement = select(func.count()).select_from(self.model).where(*criteria)

        result = await self.session.execute(statement)
        total = await self.session.scalar(count_statement)
        return result.scalars().all(), int(total or 0)

    async def create(
        self,
        tenant_id: UUID,
        values: Mapping[str, object],
    ) -> ModelT:
        """Stage a tenant-owned entity and flush without committing."""

        entity = self.model()
        for name, value in values.items():
            if name in self._immutable_fields:
                msg = f"field cannot be set during create: {name}"
                raise ValueError(msg)
            self._column(name)
            self._set_attribute(entity, name, value)
        self._set_attribute(entity, "tenant_id", tenant_id)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(
        self,
        tenant_id: UUID,
        entity_id: UUID,
        values: Mapping[str, object],
    ) -> ModelT | None:
        """Stage changes to a tenant-scoped entity and flush."""

        entity = await self.get(tenant_id, entity_id)
        if entity is None:
            return None
        for name, value in values.items():
            if name in self._immutable_fields:
                msg = f"field cannot be updated: {name}"
                raise ValueError(msg)
            self._column(name)
            self._set_attribute(entity, name, value)
        await self.session.flush()
        return entity

    async def soft_delete(
        self,
        tenant_id: UUID,
        entity_id: UUID,
    ) -> ModelT | None:
        """Mark a tenant-scoped entity deleted and flush."""

        entity = await self.get(tenant_id, entity_id)
        if entity is None:
            return None
        self._set_attribute(entity, "deleted_at", utcnow())
        await self.session.flush()
        return entity
