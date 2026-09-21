"""Opportunity use cases."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    CRM_MODULE,
    OPPORTUNITY_DELETE,
    OPPORTUNITY_UPDATE,
)
from app.auth.models import User
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.pagination import PageParams as Pagination
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction, OpportunityStatus, PipelineStageKind
from app.core.exceptions import DocumentStaleError, ResourceNotFoundError, ValidationError
from app.core.permissions import has_permission
from app.crm.contacts.service import ContactService
from app.crm.customers.service import CustomerService
from app.crm.lead_sources.service import LeadSourceService
from app.crm.leads.repository import LeadRepository
from app.crm.lost_reasons.service import LostReasonService
from app.crm.opportunities.codes import allocate_opportunity_number
from app.crm.opportunities.models import Opportunity
from app.crm.opportunities.repository import (
    OpportunityRepository,
    OpportunityStageHistoryRepository,
)
from app.crm.opportunities.schemas import (
    OpportunityCreate,
    OpportunityLose,
    OpportunityResponse,
    OpportunityStageChange,
    OpportunityUpdate,
)
from app.crm.opportunities.workflow import (
    allowed_target_stage_ids,
    assert_editable,
    assert_lost_reason_required,
    assert_reopen_allowed,
    assert_stage_move_allowed,
    default_reopen_stage,
    find_stage_by_kind,
    status_for_stage_kind,
)
from app.crm.pipelines.models import PipelineStage
from app.crm.pipelines.repository import PipelineRepository, PipelineStageRepository
from app.db.session import transaction
from app.erp.exchange_rates.service import CurrencyService


class OpportunityService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
        repo: OpportunityRepository | None = None,
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = repo or OpportunityRepository(session)
        self.stage_history = OpportunityStageHistoryRepository(session)
        self.pipelines = PipelineRepository(session)
        self.stages = PipelineStageRepository(session)
        self.customers = CustomerService(session)
        self.contacts = ContactService(session)
        self.lead_sources = LeadSourceService(session)
        self.lost_reasons = LostReasonService(session)
        self.leads = LeadRepository(session)
        self.currencies = CurrencyService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        pipeline_id: UUID | None = None,
        stage_id: UUID | None = None,
        owner_id: UUID | None = None,
        customer_id: UUID | None = None,
        source_id: UUID | None = None,
        campaign_id: UUID | None = None,
    ) -> tuple[builtins.list[OpportunityResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if pipeline_id is not None:
            filters["pipeline_id"] = pipeline_id
        if stage_id is not None:
            filters["stage_id"] = stage_id
        if owner_id is not None:
            filters["owner_id"] = owner_id
        if customer_id is not None:
            filters["customer_id"] = customer_id
        if source_id is not None:
            filters["source_id"] = source_id
        if campaign_id is not None:
            filters["campaign_id"] = campaign_id
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [await self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, opportunity_id: UUID) -> OpportunityResponse:
        return await self._to_response(await self._require(tenant_id, opportunity_id))

    async def won_attribution_for_campaign(
        self, tenant_id: UUID, campaign_id: UUID
    ) -> tuple[int, Decimal]:
        return await self.repo.won_attribution_for_campaign(tenant_id, campaign_id)

    async def list_quotations(
        self,
        tenant_id: UUID,
        opportunity_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
    ) -> tuple[builtins.list[object], int]:
        from app.erp.quotation.service import QuotationService

        await self._require(tenant_id, opportunity_id)
        quotations = QuotationService(self.session, actor_permissions=self.actor_permissions)
        return await quotations.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            opportunity_id=opportunity_id,
        )

    async def create(
        self, tenant_id: UUID, payload: OpportunityCreate, *, actor_user_id: UUID
    ) -> OpportunityResponse:
        async with transaction(self.session):
            return await self.create_record(tenant_id, payload, actor_user_id=actor_user_id)

    async def create_record(
        self, tenant_id: UUID, payload: OpportunityCreate, *, actor_user_id: UUID
    ) -> OpportunityResponse:
        pipeline_id, stage = await self._resolve_pipeline_and_stage(
            tenant_id, payload.pipeline_id, payload.stage_id
        )
        await self._validate_references(tenant_id, payload, pipeline_id=pipeline_id)
        if stage.stage_kind in {
            PipelineStageKind.WON.value,
            PipelineStageKind.LOST.value,
        }:
            raise ValidationError("New opportunities must start in an open stage")
        opportunity_number = await allocate_opportunity_number(self.session, tenant_id)
        status = status_for_stage_kind(stage.stage_kind).value
        probability = payload.probability
        if probability is None:
            probability = stage.probability
        row = await self.repo.create(
            tenant_id,
            {
                **payload.model_dump(exclude={"pipeline_id", "stage_id"}),
                "pipeline_id": pipeline_id,
                "stage_id": stage.id,
                "opportunity_number": opportunity_number,
                "status": status,
                "probability": probability,
                "created_by": actor_user_id,
                "updated_by": actor_user_id,
            },
        )
        now = datetime.now(UTC)
        await self.stage_history.append(
            tenant_id,
            opportunity_id=row.id,
            from_stage_id=None,
            to_stage_id=stage.id,
            changed_by=actor_user_id,
            changed_at=now,
            duration_days=None,
        )
        await self.audit.write(
            tenant_id=tenant_id,
            user_id=actor_user_id,
            action=AuditAction.CREATE,
            module=CRM_MODULE,
            entity_type="opportunity",
            entity_id=row.id,
            new_values=await self._snapshot(row),
        )
        return await self._to_response(row)

    async def update(
        self,
        tenant_id: UUID,
        opportunity_id: UUID,
        payload: OpportunityUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> OpportunityResponse:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, opportunity_id, for_update=True)
            assert_editable(OpportunityStatus(existing.status))
            self._assert_version(existing, expected_version)
            merged = self._merge_update(existing, payload)
            await self._validate_references(
                tenant_id,
                merged,
                pipeline_id=existing.pipeline_id,
                skip_pipeline_stage=True,
            )
            old_values = await self._snapshot(existing)
            values["version"] = existing.version + 1
            row = await self.repo.update(tenant_id, opportunity_id, values)
            if row is None:
                raise ResourceNotFoundError("Opportunity not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="opportunity",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(row),
            )
            return await self._to_response(row)

    async def change_stage(
        self,
        tenant_id: UUID,
        opportunity_id: UUID,
        payload: OpportunityStageChange,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> OpportunityResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, opportunity_id, for_update=True)
            self._assert_version(row, expected_version)
            from_stage = await self._require_stage(tenant_id, row.pipeline_id, row.stage_id)
            to_stage = await self._require_stage(tenant_id, row.pipeline_id, payload.stage_id)
            current_status = OpportunityStatus(row.status)
            assert_stage_move_allowed(
                current_status=current_status,
                pipeline_id=row.pipeline_id,
                from_stage=from_stage,
                to_stage=to_stage,
            )
            assert_lost_reason_required(to_stage, payload.lost_reason_id)
            if payload.lost_reason_id is not None:
                await self.lost_reasons.require_id(tenant_id, payload.lost_reason_id)
            return await self._apply_stage_change(
                tenant_id,
                row,
                from_stage=from_stage,
                to_stage=to_stage,
                lost_reason_id=payload.lost_reason_id,
                actor_user_id=actor_user_id,
            )

    async def win(
        self,
        tenant_id: UUID,
        opportunity_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> OpportunityResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, opportunity_id, for_update=True)
            self._assert_version(row, expected_version)
            stages = await self.stages.list_for_pipeline(tenant_id, row.pipeline_id)
            won_stage = find_stage_by_kind(stages, PipelineStageKind.WON)
            if won_stage is None:
                raise ValidationError("Pipeline has no closed won stage")
            from_stage = await self._require_stage(tenant_id, row.pipeline_id, row.stage_id)
            return await self._apply_stage_change(
                tenant_id,
                row,
                from_stage=from_stage,
                to_stage=won_stage,
                lost_reason_id=None,
                actor_user_id=actor_user_id,
            )

    async def lose(
        self,
        tenant_id: UUID,
        opportunity_id: UUID,
        payload: OpportunityLose,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> OpportunityResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, opportunity_id, for_update=True)
            self._assert_version(row, expected_version)
            await self.lost_reasons.require_id(tenant_id, payload.lost_reason_id)
            stages = await self.stages.list_for_pipeline(tenant_id, row.pipeline_id)
            lost_stage = find_stage_by_kind(stages, PipelineStageKind.LOST)
            if lost_stage is None:
                raise ValidationError("Pipeline has no closed lost stage")
            from_stage = await self._require_stage(tenant_id, row.pipeline_id, row.stage_id)
            return await self._apply_stage_change(
                tenant_id,
                row,
                from_stage=from_stage,
                to_stage=lost_stage,
                lost_reason_id=payload.lost_reason_id,
                actor_user_id=actor_user_id,
            )

    async def reopen(
        self,
        tenant_id: UUID,
        opportunity_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> OpportunityResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, opportunity_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_reopen_allowed(OpportunityStatus(row.status))
            stages = await self.stages.list_for_pipeline(tenant_id, row.pipeline_id)
            target = default_reopen_stage(stages)
            if target is None:
                raise ValidationError("Pipeline has no open stage to reopen into")
            from_stage = await self._require_stage(tenant_id, row.pipeline_id, row.stage_id)
            return await self._apply_stage_change(
                tenant_id,
                row,
                from_stage=from_stage,
                to_stage=target,
                lost_reason_id=None,
                actor_user_id=actor_user_id,
                from_closed=True,
            )

    async def delete(
        self, tenant_id: UUID, opportunity_id: UUID, *, actor_user_id: UUID
    ) -> OpportunityResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, opportunity_id)
            assert_editable(OpportunityStatus(row.status))
            response = await self._to_response(row)
            await self.repo.soft_delete(tenant_id, opportunity_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=CRM_MODULE,
                entity_type="opportunity",
                entity_id=opportunity_id,
                old_values=await self._snapshot(row),
            )
            return response

    async def _apply_stage_change(
        self,
        tenant_id: UUID,
        row: Opportunity,
        *,
        from_stage: PipelineStage,
        to_stage: PipelineStage,
        lost_reason_id: UUID | None,
        actor_user_id: UUID,
        from_closed: bool = False,
    ) -> OpportunityResponse:
        current_status = OpportunityStatus(row.status)
        if from_closed:
            assert_reopen_allowed(current_status)
            if to_stage.stage_kind != PipelineStageKind.OPEN.value:
                raise ValidationError("Reopen must target an open pipeline stage")
        else:
            assert_stage_move_allowed(
                current_status=current_status,
                pipeline_id=row.pipeline_id,
                from_stage=from_stage,
                to_stage=to_stage,
            )
        assert_lost_reason_required(to_stage, lost_reason_id)
        old_values = await self._snapshot(row)
        now = datetime.now(UTC)
        duration_days = await self._duration_since_last_change(tenant_id, row.id, now)
        new_status = status_for_stage_kind(to_stage.stage_kind)
        update_values: dict[str, object] = {
            "stage_id": to_stage.id,
            "status": new_status.value,
            "probability": to_stage.probability,
            "version": row.version + 1,
            "updated_by": actor_user_id,
        }
        if new_status == OpportunityStatus.LOST:
            update_values["lost_reason_id"] = lost_reason_id
        else:
            update_values["lost_reason_id"] = None
        updated = await self.repo.update(tenant_id, row.id, update_values)
        if updated is None:
            raise ResourceNotFoundError("Opportunity not found")
        await self.stage_history.append(
            tenant_id,
            opportunity_id=updated.id,
            from_stage_id=from_stage.id,
            to_stage_id=to_stage.id,
            changed_by=actor_user_id,
            changed_at=now,
            duration_days=duration_days,
        )
        await self.audit.write(
            tenant_id=tenant_id,
            user_id=actor_user_id,
            action=AuditAction.UPDATE,
            module=CRM_MODULE,
            entity_type="opportunity",
            entity_id=updated.id,
            old_values=old_values,
            new_values=await self._snapshot(updated),
        )
        return await self._to_response(updated)

    def available_actions_for(
        self,
        row: Opportunity,
        stages: builtins.list[PipelineStage],
    ) -> builtins.list[str]:
        status = OpportunityStatus(row.status)
        actions: builtins.list[str] = []
        if status == OpportunityStatus.OPEN:
            if has_permission(self.actor_permissions, OPPORTUNITY_UPDATE):
                for stage_id in allowed_target_stage_ids(
                    status=status,
                    current_stage_id=row.stage_id,
                    stages=stages,
                ):
                    actions.append(f"move_stage:{stage_id}")
                if find_stage_by_kind(stages, PipelineStageKind.WON) is not None:
                    actions.append("win")
                if find_stage_by_kind(stages, PipelineStageKind.LOST) is not None:
                    actions.append("lose")
                actions.append("update")
            if has_permission(self.actor_permissions, OPPORTUNITY_DELETE):
                actions.append("delete")
        elif has_permission(self.actor_permissions, OPPORTUNITY_UPDATE):
            actions.append("reopen")
        return actions

    async def _to_response(self, row: Opportunity) -> OpportunityResponse:
        stages = await self.stages.list_for_pipeline(row.tenant_id, row.pipeline_id)
        status = OpportunityStatus(row.status)
        base = OpportunityResponse.model_validate(row)
        return base.model_copy(
            update={
                "status": status,
                "available_actions": self.available_actions_for(row, stages),
            }
        )

    def _assert_version(self, row: Opportunity, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _require(
        self, tenant_id: UUID, opportunity_id: UUID, *, for_update: bool = False
    ) -> Opportunity:
        row = await self.repo.get(tenant_id, opportunity_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Opportunity not found")
        return row

    async def _require_stage(
        self, tenant_id: UUID, pipeline_id: UUID, stage_id: UUID
    ) -> PipelineStage:
        stage = await self.stages.get(tenant_id, pipeline_id, stage_id)
        if stage is None:
            raise ValidationError("Pipeline stage not found")
        return stage

    async def _resolve_pipeline_and_stage(
        self,
        tenant_id: UUID,
        pipeline_id: UUID | None,
        stage_id: UUID | None,
    ) -> tuple[UUID, PipelineStage]:
        resolved_pipeline_id = pipeline_id
        if resolved_pipeline_id is None:
            rows, _total = await self.pipelines.list(
                tenant_id,
                page=Pagination(page=1, page_size=1),
                filters={"is_default": True, "is_active": True},
            )
            if not rows:
                raise ValidationError("No default pipeline configured")
            resolved_pipeline_id = rows[0].id
        pipeline = await self.pipelines.get(tenant_id, resolved_pipeline_id)
        if pipeline is None or not pipeline.is_active:
            raise ValidationError("Pipeline not found")
        if stage_id is not None:
            stage = await self.stages.get(tenant_id, resolved_pipeline_id, stage_id)
            if stage is None:
                raise ValidationError("Pipeline stage not found")
            return resolved_pipeline_id, stage
        stages = await self.stages.list_for_pipeline(tenant_id, resolved_pipeline_id)
        first_open = default_reopen_stage(stages)
        if first_open is None:
            raise ValidationError("Pipeline has no open stage")
        return resolved_pipeline_id, first_open

    async def _validate_references(
        self,
        tenant_id: UUID,
        payload: OpportunityCreate | OpportunityUpdate,
        *,
        pipeline_id: UUID,
        skip_pipeline_stage: bool = False,
    ) -> None:
        if isinstance(payload, OpportunityCreate) and not skip_pipeline_stage:
            _ = pipeline_id
        if getattr(payload, "customer_id", None) is not None:
            await self.customers.get(tenant_id, payload.customer_id)  # type: ignore[arg-type]
        if getattr(payload, "contact_id", None) is not None:
            contact = await self.contacts.get(tenant_id, payload.contact_id)  # type: ignore[arg-type]
            if payload.customer_id is not None and contact.customer_id != payload.customer_id:
                raise ValidationError("Contact does not belong to the selected customer")
        if getattr(payload, "source_id", None) is not None:
            await self.lead_sources.require_id(tenant_id, payload.source_id)  # type: ignore[arg-type]
        if getattr(payload, "campaign_id", None) is not None:
            from app.crm.campaigns.service import CampaignService

            await CampaignService(self.session).require_id(
                tenant_id,
                payload.campaign_id,  # type: ignore[arg-type]
            )
        if getattr(payload, "owner_id", None) is not None:
            await self._require_owner(tenant_id, payload.owner_id)  # type: ignore[arg-type]
        if getattr(payload, "currency_id", None) is not None:
            await self.currencies.require_id(tenant_id, payload.currency_id)  # type: ignore[arg-type]
        if isinstance(payload, OpportunityCreate) and payload.lead_id is not None:
            lead = await self.leads.get(tenant_id, payload.lead_id)
            if lead is None:
                raise ValidationError("Lead not found")

    async def _require_owner(self, tenant_id: UUID, owner_id: UUID) -> None:
        statement = select(User.id).where(User.tenant_id == tenant_id, User.id == owner_id)
        result = await self.session.execute(statement)
        if result.scalar_one_or_none() is None:
            raise ValidationError("Owner not found")

    async def _duration_since_last_change(
        self, tenant_id: UUID, opportunity_id: UUID, now: datetime
    ) -> int | None:
        latest = await self.stage_history.latest_for_opportunity(tenant_id, opportunity_id)
        if latest is None:
            return None
        delta = now - latest.changed_at
        return max(delta.days, 0)

    async def _snapshot(self, row: Opportunity) -> dict[str, object]:
        return {
            "opportunity_number": row.opportunity_number,
            "name": row.name,
            "customer_id": str(row.customer_id) if row.customer_id else None,
            "contact_id": str(row.contact_id) if row.contact_id else None,
            "pipeline_id": str(row.pipeline_id),
            "stage_id": str(row.stage_id),
            "amount": str(row.amount) if row.amount is not None else None,
            "currency_id": str(row.currency_id) if row.currency_id else None,
            "probability": str(row.probability) if row.probability is not None else None,
            "expected_close_date": (
                row.expected_close_date.isoformat() if row.expected_close_date else None
            ),
            "status": row.status,
            "lost_reason_id": str(row.lost_reason_id) if row.lost_reason_id else None,
            "owner_id": str(row.owner_id) if row.owner_id else None,
            "source_id": str(row.source_id) if row.source_id else None,
            "lead_id": str(row.lead_id) if row.lead_id else None,
            "campaign_id": str(row.campaign_id) if row.campaign_id else None,
            "version": row.version,
        }

    def _merge_update(self, existing: Opportunity, payload: OpportunityUpdate) -> OpportunityCreate:
        data = {
            "name": existing.name,
            "customer_id": existing.customer_id,
            "contact_id": existing.contact_id,
            "pipeline_id": existing.pipeline_id,
            "stage_id": existing.stage_id,
            "amount": existing.amount,
            "currency_id": existing.currency_id,
            "probability": existing.probability,
            "expected_close_date": existing.expected_close_date,
            "owner_id": existing.owner_id,
            "source_id": existing.source_id,
            "lead_id": existing.lead_id,
            "campaign_id": existing.campaign_id,
        }
        data.update(payload.model_dump(exclude_unset=True, exclude={"version"}))
        return OpportunityCreate.model_validate(data)
