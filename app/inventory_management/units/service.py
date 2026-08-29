"""Unit of measure use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import INVENTORY_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.db.session import transaction
from app.inventory_management.units.models import Unit
from app.inventory_management.units.repository import UnitRepository
from app.inventory_management.units.schemas import UnitCreate, UnitResponse, UnitUpdate


class UnitService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UnitRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[UnitResponse], int]:
        filters = {"is_active": is_active} if is_active is not None else None
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )
        return [UnitResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, unit_id: UUID) -> UnitResponse:
        return UnitResponse.model_validate(await self._require(tenant_id, unit_id))

    async def require_id(self, tenant_id: UUID, unit_id: UUID) -> UUID:
        await self._require(tenant_id, unit_id)
        return unit_id

    async def create(
        self, tenant_id: UUID, payload: UnitCreate, *, actor_user_id: UUID
    ) -> UnitResponse:
        async with transaction(self.session):
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
                raise DuplicateResourceError("A unit with this code already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="unit",
                entity_id=row.id,
                new_values={"code": row.code},
            )
            return UnitResponse.model_validate(row)

    async def update(
        self, tenant_id: UUID, unit_id: UUID, payload: UnitUpdate, *, actor_user_id: UUID
    ) -> UnitResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            await self._require(tenant_id, unit_id)
            row = await self.repo.update(tenant_id, unit_id, values)
            if row is None:
                raise ResourceNotFoundError("Unit not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="unit",
                entity_id=row.id,
                new_values={"name": row.name},
            )
            return UnitResponse.model_validate(row)

    async def delete(self, tenant_id: UUID, unit_id: UUID, *, actor_user_id: UUID) -> UnitResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, unit_id)
            response = UnitResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, unit_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="unit",
                entity_id=unit_id,
                old_values={"code": row.code},
            )
            return response

    async def _require(self, tenant_id: UUID, unit_id: UUID) -> Unit:
        row = await self.repo.get(tenant_id, unit_id)
        if row is None:
            raise ResourceNotFoundError("Unit not found")
        return row
