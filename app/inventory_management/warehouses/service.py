"""Warehouse use cases."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import INVENTORY_MODULE
from app.auth.org_service import OrganizationService
from app.auth.schemas import AddressPayload, format_address_label
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AddressType, AuditAction
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.db.session import transaction
from app.inventory_management.warehouses.models import Warehouse
from app.inventory_management.warehouses.repository import WarehouseRepository
from app.inventory_management.warehouses.schemas import (
    WarehouseCreate,
    WarehouseResponse,
    WarehouseUpdate,
)


class WarehouseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WarehouseRepository(session)
        self.org = OrganizationService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
        is_default: bool | None = None,
    ) -> tuple[list[WarehouseResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        if is_default is not None:
            filters["is_default"] = is_default
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [item for item in await self._to_responses(tenant_id, rows)], total

    async def get(self, tenant_id: UUID, warehouse_id: UUID) -> WarehouseResponse:
        row = await self._require(tenant_id, warehouse_id)
        return await self._to_response(tenant_id, row)

    async def require_id(self, tenant_id: UUID, warehouse_id: UUID) -> UUID:
        await self._require(tenant_id, warehouse_id)
        return warehouse_id

    async def create(
        self, tenant_id: UUID, payload: WarehouseCreate, *, actor_user_id: UUID
    ) -> WarehouseResponse:
        async with transaction(self.session):
            make_default = payload.is_default or (await self.repo.count(tenant_id) == 0)
            if make_default:
                await self.repo.clear_other_defaults(tenant_id)
            address_id = await self.org.upsert_address(
                tenant_id,
                None,
                payload.address,
                address_type=AddressType.WAREHOUSE,
            )
            try:
                row = await self.repo.create(
                    tenant_id,
                    {
                        "code": payload.code,
                        "name": payload.name,
                        "phone": payload.phone,
                        "address_id": address_id,
                        "is_default": make_default,
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A warehouse with this code already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="warehouse",
                entity_id=row.id,
                new_values=await self._warehouse_snapshot(tenant_id, row),
            )
            return await self._to_response(tenant_id, row)

    async def update(
        self,
        tenant_id: UUID,
        warehouse_id: UUID,
        payload: WarehouseUpdate,
        *,
        actor_user_id: UUID,
    ) -> WarehouseResponse:
        values = payload.model_dump(exclude_unset=True)
        address_payload = values.pop("address", None)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            row = await self._require(tenant_id, warehouse_id)
            old_values = await self._warehouse_snapshot(tenant_id, row)
            if address_payload is not None:
                values["address_id"] = await self.org.upsert_address(
                    tenant_id,
                    row.address_id,
                    AddressPayload.model_validate(address_payload),
                    address_type=AddressType.WAREHOUSE,
                )
            if values.get("is_default") is True:
                await self.repo.clear_other_defaults(tenant_id, keep_id=warehouse_id)
            try:
                updated = await self.repo.update(tenant_id, warehouse_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A warehouse with this code already exists") from exc
            if updated is None:
                raise ResourceNotFoundError("Warehouse not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="warehouse",
                entity_id=updated.id,
                old_values=old_values,
                new_values=await self._warehouse_snapshot(tenant_id, updated),
            )
            return await self._to_response(tenant_id, updated)

    async def delete(
        self, tenant_id: UUID, warehouse_id: UUID, *, actor_user_id: UUID
    ) -> WarehouseResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, warehouse_id)
            response = await self._to_response(tenant_id, row)
            await self.repo.soft_delete(tenant_id, warehouse_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="warehouse",
                entity_id=warehouse_id,
                old_values=await self._warehouse_snapshot(tenant_id, row),
            )
            return response

    async def _warehouse_snapshot(self, tenant_id: UUID, row: Warehouse) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "code": row.code,
            "name": row.name,
            "phone": row.phone,
            "is_default": row.is_default,
            "is_active": row.is_active,
        }
        if row.address_id is not None:
            address = format_address_label(await self.org.get_address(tenant_id, row.address_id))
            if address is not None:
                snapshot["address"] = address
        return snapshot

    async def _to_response(self, tenant_id: UUID, row: Warehouse) -> WarehouseResponse:
        responses = await self._to_responses(tenant_id, (row,))
        return responses[0]

    async def _to_responses(
        self, tenant_id: UUID, rows: Sequence[Warehouse]
    ) -> Sequence[WarehouseResponse]:
        address_ids = [row.address_id for row in rows if row.address_id is not None]
        addresses = await self.org.get_addresses(tenant_id, address_ids)
        return [
            WarehouseResponse(
                id=row.id,
                tenant_id=row.tenant_id,
                code=row.code,
                name=row.name,
                phone=row.phone,
                address=addresses.get(row.address_id) if row.address_id is not None else None,
                is_default=row.is_default,
                is_active=row.is_active,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def _require(self, tenant_id: UUID, warehouse_id: UUID) -> Warehouse:
        row = await self.repo.get(tenant_id, warehouse_id)
        if row is None:
            raise ResourceNotFoundError("Warehouse not found")
        return row
