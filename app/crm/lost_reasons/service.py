"""Lost reason use cases."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import CRM_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.services.master_usage import assert_master_not_referenced
from app.core.enums import AuditAction
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.crm.lost_reasons.models import LostReason
from app.crm.lost_reasons.repository import LostReasonRepository
from app.crm.lost_reasons.schemas import LostReasonCreate, LostReasonResponse, LostReasonUpdate
from app.db.session import transaction


def _lost_reason_snapshot(row: LostReason) -> dict[str, object]:
    return {
        "name": row.name,
        "description": row.description,
        "is_active": row.is_active,
    }


class LostReasonService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = LostReasonRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[LostReasonResponse], int]:
        filters = {"is_active": is_active} if is_active is not None else None
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )
        return [LostReasonResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, lost_reason_id: UUID) -> LostReasonResponse:
        return LostReasonResponse.model_validate(await self._require(tenant_id, lost_reason_id))

    async def require_id(self, tenant_id: UUID, lost_reason_id: UUID) -> UUID:
        row = await self._require(tenant_id, lost_reason_id)
        if not row.is_active:
            raise ValidationError("Lost reason is inactive")
        return lost_reason_id

    async def create(
        self, tenant_id: UUID, payload: LostReasonCreate, *, actor_user_id: UUID
    ) -> LostReasonResponse:
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
                    "A lost reason with this name already exists"
                ) from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=CRM_MODULE,
                entity_type="lost_reason",
                entity_id=row.id,
                new_values=_lost_reason_snapshot(row),
            )
            return LostReasonResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        lost_reason_id: UUID,
        payload: LostReasonUpdate,
        *,
        actor_user_id: UUID,
    ) -> LostReasonResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, lost_reason_id)
            old_values = _lost_reason_snapshot(existing)
            if values.get("is_active") is False and existing.is_active:
                await assert_master_not_referenced(
                    self.session,
                    tenant_id=tenant_id,
                    table_name=LostReason.__tablename__,
                    record_id=lost_reason_id,
                    label="lost reason",
                    action="deactivate",
                )
            try:
                row = await self.repo.update(tenant_id, lost_reason_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A lost reason with this name already exists"
                ) from exc
            if row is None:
                raise ResourceNotFoundError("Lost reason not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="lost_reason",
                entity_id=row.id,
                old_values=old_values,
                new_values=_lost_reason_snapshot(row),
            )
            return LostReasonResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, lost_reason_id: UUID, *, actor_user_id: UUID
    ) -> LostReasonResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, lost_reason_id)
            await assert_master_not_referenced(
                self.session,
                tenant_id=tenant_id,
                table_name=LostReason.__tablename__,
                record_id=lost_reason_id,
                label="lost reason",
            )
            response = LostReasonResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, lost_reason_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=CRM_MODULE,
                entity_type="lost_reason",
                entity_id=lost_reason_id,
                old_values=_lost_reason_snapshot(row),
            )
            return response

    async def _require(self, tenant_id: UUID, lost_reason_id: UUID) -> LostReason:
        row = await self.repo.get(tenant_id, lost_reason_id)
        if row is None:
            raise ResourceNotFoundError("Lost reason not found")
        return row
