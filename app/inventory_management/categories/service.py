"""Category use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import INVENTORY_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.inventory_management.categories.models import Category
from app.inventory_management.categories.repository import CategoryRepository
from app.inventory_management.categories.schemas import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
)


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CategoryRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        parent_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[CategoryResponse], int]:
        filters: dict[str, object] = {}
        if parent_id is not None:
            filters["parent_id"] = parent_id
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [CategoryResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, category_id: UUID) -> CategoryResponse:
        return CategoryResponse.model_validate(await self._require(tenant_id, category_id))

    async def require_id(self, tenant_id: UUID, category_id: UUID) -> UUID:
        await self._require(tenant_id, category_id)
        return category_id

    async def create(
        self, tenant_id: UUID, payload: CategoryCreate, *, actor_user_id: UUID
    ) -> CategoryResponse:
        async with transaction(self.session):
            if payload.parent_id is not None:
                await self._require(tenant_id, payload.parent_id)
            try:
                row = await self.repo.create(
                    tenant_id,
                    {
                        **payload.model_dump(),
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A category with this code already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="category",
                entity_id=row.id,
                new_values=await self._category_snapshot(tenant_id, row),
            )
            return CategoryResponse.model_validate(row)

    async def update(
        self, tenant_id: UUID, category_id: UUID, payload: CategoryUpdate, *, actor_user_id: UUID
    ) -> CategoryResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, category_id)
            old_values = await self._category_snapshot(tenant_id, existing)
            if values.get("parent_id") is not None:
                if values["parent_id"] == category_id:
                    raise ValidationError("A category cannot be its own parent")
                await self._require(tenant_id, values["parent_id"])
            try:
                row = await self.repo.update(tenant_id, category_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A category with this code already exists") from exc
            if row is None:
                raise ResourceNotFoundError("Category not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="category",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._category_snapshot(tenant_id, row),
            )
            return CategoryResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, category_id: UUID, *, actor_user_id: UUID
    ) -> CategoryResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, category_id)
            if await self.repo.count_children(tenant_id, category_id) > 0:
                raise ValidationError("Cannot delete a category that still has children")
            response = CategoryResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, category_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="category",
                entity_id=category_id,
                old_values=await self._category_snapshot(tenant_id, row),
            )
            return response

    async def _category_snapshot(self, tenant_id: UUID, row: Category) -> dict[str, object]:
        parent_name: str | None = None
        if row.parent_id is not None:
            parent = await self.repo.get(tenant_id, row.parent_id)
            if parent is not None:
                parent_name = parent.name
        return {
            "name": row.name,
            "code": row.code,
            "parent": parent_name,
            "is_active": row.is_active,
        }

    async def _require(self, tenant_id: UUID, category_id: UUID) -> Category:
        row = await self.repo.get(tenant_id, category_id)
        if row is None:
            raise ResourceNotFoundError("Category not found")
        return row
