"""Lead source use cases."""

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
from app.crm.lead_sources.models import LeadSource
from app.crm.lead_sources.repository import LeadSourceRepository
from app.crm.lead_sources.schemas import LeadSourceCreate, LeadSourceResponse, LeadSourceUpdate
from app.db.session import transaction


def _lead_source_snapshot(row: LeadSource) -> dict[str, object]:
    return {
        "name": row.name,
        "description": row.description,
        "is_active": row.is_active,
    }


class LeadSourceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = LeadSourceRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[LeadSourceResponse], int]:
        filters = {"is_active": is_active} if is_active is not None else None
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )
        return [LeadSourceResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, lead_source_id: UUID) -> LeadSourceResponse:
        return LeadSourceResponse.model_validate(await self._require(tenant_id, lead_source_id))

    async def require_id(self, tenant_id: UUID, lead_source_id: UUID) -> UUID:
        row = await self._require(tenant_id, lead_source_id)
        if not row.is_active:
            raise ValidationError("Lead source is inactive")
        return lead_source_id

    async def create(
        self, tenant_id: UUID, payload: LeadSourceCreate, *, actor_user_id: UUID
    ) -> LeadSourceResponse:
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
                    "A lead source with this name already exists"
                ) from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=CRM_MODULE,
                entity_type="lead_source",
                entity_id=row.id,
                new_values=_lead_source_snapshot(row),
            )
            return LeadSourceResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        lead_source_id: UUID,
        payload: LeadSourceUpdate,
        *,
        actor_user_id: UUID,
    ) -> LeadSourceResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, lead_source_id)
            old_values = _lead_source_snapshot(existing)
            if values.get("is_active") is False and existing.is_active:
                await assert_master_not_referenced(
                    self.session,
                    tenant_id=tenant_id,
                    table_name=LeadSource.__tablename__,
                    record_id=lead_source_id,
                    label="lead source",
                    action="deactivate",
                )
            try:
                row = await self.repo.update(tenant_id, lead_source_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A lead source with this name already exists"
                ) from exc
            if row is None:
                raise ResourceNotFoundError("Lead source not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="lead_source",
                entity_id=row.id,
                old_values=old_values,
                new_values=_lead_source_snapshot(row),
            )
            return LeadSourceResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, lead_source_id: UUID, *, actor_user_id: UUID
    ) -> LeadSourceResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, lead_source_id)
            await assert_master_not_referenced(
                self.session,
                tenant_id=tenant_id,
                table_name=LeadSource.__tablename__,
                record_id=lead_source_id,
                label="lead source",
            )
            response = LeadSourceResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, lead_source_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=CRM_MODULE,
                entity_type="lead_source",
                entity_id=lead_source_id,
                old_values=_lead_source_snapshot(row),
            )
            return response

    async def _require(self, tenant_id: UUID, lead_source_id: UUID) -> LeadSource:
        row = await self.repo.get(tenant_id, lead_source_id)
        if row is None:
            raise ResourceNotFoundError("Lead source not found")
        return row
