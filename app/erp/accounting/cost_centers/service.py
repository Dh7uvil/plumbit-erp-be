"""Cost center use cases."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import MASTERS_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.services.master_usage import assert_master_not_referenced
from app.core.enums import AuditAction
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.accounting.cost_centers.models import CostCenter
from app.erp.accounting.cost_centers.repository import CostCenterRepository
from app.erp.accounting.cost_centers.schemas import (
    CostCenterCreate,
    CostCenterResponse,
    CostCenterUpdate,
)


def _cost_center_snapshot(row: CostCenter) -> dict[str, object]:
    return {
        "name": row.name,
        "code": row.code,
        "description": row.description,
        "is_active": row.is_active,
    }


class CostCenterService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CostCenterRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[CostCenterResponse], int]:
        filters = {"is_active": is_active} if is_active is not None else None
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )
        return [CostCenterResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, cost_center_id: UUID) -> CostCenterResponse:
        return CostCenterResponse.model_validate(await self._require(tenant_id, cost_center_id))

    async def require_id(self, tenant_id: UUID, cost_center_id: UUID) -> UUID:
        row = await self._require(tenant_id, cost_center_id)
        if not row.is_active:
            raise ValidationError("Cost center is inactive")
        return cost_center_id

    async def create(
        self, tenant_id: UUID, payload: CostCenterCreate, *, actor_user_id: UUID
    ) -> CostCenterResponse:
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
                raise DuplicateResourceError(
                    "A cost center with this code already exists"
                ) from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=MASTERS_MODULE,
                entity_type="cost_center",
                entity_id=row.id,
                new_values=_cost_center_snapshot(row),
            )
            return CostCenterResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        cost_center_id: UUID,
        payload: CostCenterUpdate,
        *,
        actor_user_id: UUID,
    ) -> CostCenterResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, cost_center_id)
            old_values = _cost_center_snapshot(existing)
            if values.get("is_active") is False and existing.is_active:
                await assert_master_not_referenced(
                    self.session,
                    tenant_id=tenant_id,
                    table_name=CostCenter.__tablename__,
                    record_id=cost_center_id,
                    label="cost center",
                    action="deactivate",
                )
            try:
                row = await self.repo.update(tenant_id, cost_center_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A cost center with this code already exists"
                ) from exc
            if row is None:
                raise ResourceNotFoundError("Cost center not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=MASTERS_MODULE,
                entity_type="cost_center",
                entity_id=row.id,
                old_values=old_values,
                new_values=_cost_center_snapshot(row),
            )
            return CostCenterResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, cost_center_id: UUID, *, actor_user_id: UUID
    ) -> CostCenterResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, cost_center_id)
            await assert_master_not_referenced(
                self.session,
                tenant_id=tenant_id,
                table_name=CostCenter.__tablename__,
                record_id=cost_center_id,
                label="cost center",
            )
            response = CostCenterResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, cost_center_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=MASTERS_MODULE,
                entity_type="cost_center",
                entity_id=cost_center_id,
                old_values=_cost_center_snapshot(row),
            )
            return response

    async def _require(self, tenant_id: UUID, cost_center_id: UUID) -> CostCenter:
        row = await self.repo.get(tenant_id, cost_center_id)
        if row is None:
            raise ResourceNotFoundError("Cost center not found")
        return row
