"""Pipeline and stage use cases."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import CRM_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.services.master_usage import assert_master_not_referenced
from app.core.enums import AuditAction, PipelineStageKind
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.crm.pipelines.models import Pipeline
from app.crm.pipelines.repository import PipelineRepository, PipelineStageRepository
from app.crm.pipelines.schemas import (
    PipelineCreate,
    PipelineListItemResponse,
    PipelineResponse,
    PipelineStageCreate,
    PipelineStageResponse,
    PipelineStageUpdate,
    PipelineUpdate,
)
from app.db.session import transaction


def _pipeline_snapshot(row: Pipeline) -> dict[str, object]:
    return {
        "name": row.name,
        "is_default": row.is_default,
        "is_active": row.is_active,
    }


def _stage_snapshot(row: object) -> dict[str, object]:
    return {
        "name": row.name,
        "sort_order": row.sort_order,
        "probability": row.probability,
        "stage_kind": row.stage_kind,
    }


class PipelineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PipelineRepository(session)
        self.stages = PipelineStageRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
        is_default: bool | None = None,
    ) -> tuple[list[PipelineListItemResponse], int]:
        filters: dict[str, object] = {}
        if is_active is not None:
            filters["is_active"] = is_active
        if is_default is not None:
            filters["is_default"] = is_default
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
        )
        return [PipelineListItemResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, pipeline_id: UUID) -> PipelineResponse:
        row = await self._require(tenant_id, pipeline_id)
        stage_rows = await self.stages.list_for_pipeline(tenant_id, pipeline_id)
        response = PipelineResponse.model_validate(row)
        response.stages = [PipelineStageResponse.model_validate(stage) for stage in stage_rows]
        return response

    async def create(
        self, tenant_id: UUID, payload: PipelineCreate, *, actor_user_id: UUID
    ) -> PipelineResponse:
        async with transaction(self.session):
            if payload.is_default:
                await self.repo.clear_default_except(tenant_id)
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
                    "A pipeline with this name already exists"
                ) from exc
            if not payload.is_default:
                await self._ensure_default_exists(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=CRM_MODULE,
                entity_type="pipeline",
                entity_id=row.id,
                new_values=_pipeline_snapshot(row),
            )
            return await self.get(tenant_id, row.id)

    async def update(
        self,
        tenant_id: UUID,
        pipeline_id: UUID,
        payload: PipelineUpdate,
        *,
        actor_user_id: UUID,
    ) -> PipelineResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, pipeline_id)
            old_values = _pipeline_snapshot(existing)
            if values.get("is_active") is False and existing.is_active:
                await assert_master_not_referenced(
                    self.session,
                    tenant_id=tenant_id,
                    table_name=Pipeline.__tablename__,
                    record_id=pipeline_id,
                    label="pipeline",
                    action="deactivate",
                )
            if values.get("is_default") is True:
                await self.repo.clear_default_except(tenant_id, except_pipeline_id=pipeline_id)
            if values.get("is_default") is False and existing.is_default:
                raise ValidationError("Assign another default pipeline before clearing this one")
            try:
                row = await self.repo.update(tenant_id, pipeline_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A pipeline with this name already exists"
                ) from exc
            if row is None:
                raise ResourceNotFoundError("Pipeline not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="pipeline",
                entity_id=row.id,
                old_values=old_values,
                new_values=_pipeline_snapshot(row),
            )
            return await self.get(tenant_id, pipeline_id)

    async def delete(
        self, tenant_id: UUID, pipeline_id: UUID, *, actor_user_id: UUID
    ) -> PipelineResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, pipeline_id)
            if row.is_default:
                raise ValidationError("Cannot delete the default pipeline")
            await assert_master_not_referenced(
                self.session,
                tenant_id=tenant_id,
                table_name=Pipeline.__tablename__,
                record_id=pipeline_id,
                label="pipeline",
            )
            response = await self.get(tenant_id, pipeline_id)
            await self.repo.soft_delete(tenant_id, pipeline_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=CRM_MODULE,
                entity_type="pipeline",
                entity_id=pipeline_id,
                old_values=_pipeline_snapshot(row),
            )
            return response

    async def create_stage(
        self,
        tenant_id: UUID,
        pipeline_id: UUID,
        payload: PipelineStageCreate,
        *,
        actor_user_id: UUID,
    ) -> PipelineStageResponse:
        async with transaction(self.session):
            await self._require(tenant_id, pipeline_id)
            stage_values = payload.model_dump()
            stage_values["stage_kind"] = payload.stage_kind.value
            try:
                row = await self.stages.create(
                    tenant_id,
                    {
                        "pipeline_id": pipeline_id,
                        **stage_values,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A stage with this name already exists in the pipeline"
                ) from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=CRM_MODULE,
                entity_type="pipeline_stage",
                entity_id=row.id,
                new_values=_stage_snapshot(row),
            )
            return PipelineStageResponse.model_validate(row)

    async def update_stage(
        self,
        tenant_id: UUID,
        pipeline_id: UUID,
        stage_id: UUID,
        payload: PipelineStageUpdate,
        *,
        actor_user_id: UUID,
    ) -> PipelineStageResponse:
        values = payload.model_dump(exclude_unset=True)
        if "stage_kind" in values and values["stage_kind"] is not None:
            values["stage_kind"] = values["stage_kind"].value
        async with transaction(self.session):
            await self._require(tenant_id, pipeline_id)
            existing = await self.stages.get(tenant_id, pipeline_id, stage_id)
            if existing is None:
                raise ResourceNotFoundError("Pipeline stage not found")
            old_values = _stage_snapshot(existing)
            try:
                row = await self.stages.update(tenant_id, pipeline_id, stage_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A stage with this name already exists in the pipeline"
                ) from exc
            if row is None:
                raise ResourceNotFoundError("Pipeline stage not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="pipeline_stage",
                entity_id=row.id,
                old_values=old_values,
                new_values=_stage_snapshot(row),
            )
            return PipelineStageResponse.model_validate(row)

    async def delete_stage(
        self,
        tenant_id: UUID,
        pipeline_id: UUID,
        stage_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> PipelineStageResponse:
        async with transaction(self.session):
            await self._require(tenant_id, pipeline_id)
            existing = await self.stages.get(tenant_id, pipeline_id, stage_id)
            if existing is None:
                raise ResourceNotFoundError("Pipeline stage not found")
            if existing.stage_kind in {
                PipelineStageKind.WON.value,
                PipelineStageKind.LOST.value,
            }:
                raise ValidationError("Cannot delete closed won or closed lost stages")
            response = PipelineStageResponse.model_validate(existing)
            await self.stages.delete(tenant_id, pipeline_id, stage_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=CRM_MODULE,
                entity_type="pipeline_stage",
                entity_id=stage_id,
                old_values=_stage_snapshot(existing),
            )
            return response

    async def _ensure_default_exists(self, tenant_id: UUID, pipeline_id: UUID) -> None:
        rows, _total = await self.repo.list(
            tenant_id,
            page=PageParams(page=1, page_size=1),
            filters={"is_default": True},
        )
        if rows:
            return
        await self.repo.update(tenant_id, pipeline_id, {"is_default": True})

    async def _require(self, tenant_id: UUID, pipeline_id: UUID) -> Pipeline:
        row = await self.repo.get(tenant_id, pipeline_id)
        if row is None:
            raise ResourceNotFoundError("Pipeline not found")
        return row
