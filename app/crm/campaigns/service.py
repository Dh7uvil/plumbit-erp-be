"""Campaign use cases."""

from __future__ import annotations

import builtins
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import CRM_MODULE
from app.auth.models import User
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.services.master_usage import assert_master_not_referenced
from app.core.enums import (
    AuditAction,
    CampaignMemberStatus,
    CampaignMemberType,
    CampaignStatus,
    CampaignType,
    LeadStatus,
)
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.crm.campaigns.models import Campaign, CampaignMember
from app.crm.campaigns.repository import CampaignMemberRepository, CampaignRepository
from app.crm.campaigns.schemas import (
    CampaignCreate,
    CampaignMemberCreate,
    CampaignMemberResponse,
    CampaignMemberUpdate,
    CampaignResponse,
    CampaignRoiResponse,
    CampaignUpdate,
)
from app.crm.campaigns.workflow import compute_roi_percent
from app.db.session import transaction


class CampaignService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        repo: CampaignRepository | None = None,
    ) -> None:
        self.session = session
        self.repo = repo or CampaignRepository(session)
        self.members = CampaignMemberRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        campaign_type: str | None = None,
        owner_id: UUID | None = None,
    ) -> tuple[builtins.list[CampaignResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if campaign_type is not None:
            filters["campaign_type"] = campaign_type
        if owner_id is not None:
            filters["owner_id"] = owner_id
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, campaign_id: UUID) -> CampaignResponse:
        return self._to_response(await self._require(tenant_id, campaign_id))

    async def require_id(self, tenant_id: UUID, campaign_id: UUID) -> UUID:
        row = await self._require(tenant_id, campaign_id)
        if row.status == CampaignStatus.CANCELLED.value:
            raise ValidationError("Campaign is cancelled")
        return campaign_id

    async def create(
        self, tenant_id: UUID, payload: CampaignCreate, *, actor_user_id: UUID
    ) -> CampaignResponse:
        async with transaction(self.session):
            if payload.owner_id is not None:
                await self._require_owner(tenant_id, payload.owner_id)
            values = payload.model_dump()
            values["campaign_type"] = payload.campaign_type.value
            values["status"] = payload.status.value
            values["created_by"] = actor_user_id
            values["updated_by"] = actor_user_id
            try:
                row = await self.repo.create(tenant_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A campaign with this name already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=CRM_MODULE,
                entity_type="campaign",
                entity_id=row.id,
                new_values=self._snapshot(row),
            )
            return self._to_response(row)

    async def update(
        self,
        tenant_id: UUID,
        campaign_id: UUID,
        payload: CampaignUpdate,
        *,
        actor_user_id: UUID,
    ) -> CampaignResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            existing = await self._require(tenant_id, campaign_id)
            start_date = values.get("start_date", existing.start_date)
            end_date = values.get("end_date", existing.end_date)
            if start_date is not None and end_date is not None and end_date < start_date:
                raise ValidationError("end_date must be on or after start_date")
            if "owner_id" in values and payload.owner_id is not None:
                await self._require_owner(tenant_id, payload.owner_id)
            if "campaign_type" in values and payload.campaign_type is not None:
                values["campaign_type"] = payload.campaign_type.value
            if "status" in values and payload.status is not None:
                values["status"] = payload.status.value
            values["updated_by"] = actor_user_id
            old_values = self._snapshot(existing)
            try:
                row = await self.repo.update(tenant_id, campaign_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A campaign with this name already exists") from exc
            if row is None:
                raise ResourceNotFoundError("Campaign not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="campaign",
                entity_id=row.id,
                old_values=old_values,
                new_values=self._snapshot(row),
            )
            return self._to_response(row)

    async def delete(
        self, tenant_id: UUID, campaign_id: UUID, *, actor_user_id: UUID
    ) -> CampaignResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, campaign_id)
            await self.members.delete_for_campaign(tenant_id, campaign_id)
            await assert_master_not_referenced(
                self.session,
                tenant_id=tenant_id,
                table_name=Campaign.__tablename__,
                record_id=campaign_id,
                label="campaign",
                exclude_tables=frozenset({"crm_campaign_members"}),
            )
            response = self._to_response(row)
            await self.repo.soft_delete(tenant_id, campaign_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=CRM_MODULE,
                entity_type="campaign",
                entity_id=campaign_id,
                old_values=self._snapshot(row),
            )
            return response

    async def list_members(
        self,
        tenant_id: UUID,
        campaign_id: UUID,
        *,
        page: PageParams,
    ) -> tuple[builtins.list[CampaignMemberResponse], int]:
        await self._require(tenant_id, campaign_id)
        rows, total = await self.members.list(tenant_id, campaign_id, page=page)
        return [await self._to_member_response(tenant_id, row) for row in rows], total

    async def add_member(
        self,
        tenant_id: UUID,
        campaign_id: UUID,
        payload: CampaignMemberCreate,
        *,
        actor_user_id: UUID,
    ) -> CampaignMemberResponse:
        async with transaction(self.session):
            await self._require(tenant_id, campaign_id)
            await self._validate_member(tenant_id, payload.member_type, payload.member_id)
            try:
                row = await self.members.create(
                    tenant_id,
                    {
                        "campaign_id": campaign_id,
                        "member_type": payload.member_type.value,
                        "member_id": payload.member_id,
                        "member_status": payload.member_status.value,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("This member is already on the campaign") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=CRM_MODULE,
                entity_type="campaign_member",
                entity_id=row.id,
                new_values=self._member_snapshot(row),
            )
            return await self._to_member_response(tenant_id, row)

    async def update_member(
        self,
        tenant_id: UUID,
        campaign_id: UUID,
        member_id: UUID,
        payload: CampaignMemberUpdate,
        *,
        actor_user_id: UUID,
    ) -> CampaignMemberResponse:
        async with transaction(self.session):
            await self._require(tenant_id, campaign_id)
            existing = await self.members.get(tenant_id, campaign_id, member_id)
            if existing is None:
                raise ResourceNotFoundError("Campaign member not found")
            old_values = self._member_snapshot(existing)
            row = await self.members.update(
                tenant_id,
                campaign_id,
                member_id,
                {"member_status": payload.member_status.value},
            )
            if row is None:
                raise ResourceNotFoundError("Campaign member not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="campaign_member",
                entity_id=row.id,
                old_values=old_values,
                new_values=self._member_snapshot(row),
            )
            return await self._to_member_response(tenant_id, row)

    async def remove_member(
        self,
        tenant_id: UUID,
        campaign_id: UUID,
        member_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> CampaignMemberResponse:
        async with transaction(self.session):
            await self._require(tenant_id, campaign_id)
            row = await self.members.get(tenant_id, campaign_id, member_id)
            if row is None:
                raise ResourceNotFoundError("Campaign member not found")
            response = await self._to_member_response(tenant_id, row)
            await self.members.delete(tenant_id, campaign_id, member_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=CRM_MODULE,
                entity_type="campaign_member",
                entity_id=member_id,
                old_values=self._member_snapshot(row),
            )
            return response

    async def roi(self, tenant_id: UUID, campaign_id: UUID) -> CampaignRoiResponse:
        row = await self._require(tenant_id, campaign_id)
        from app.crm.leads.service import LeadService
        from app.crm.opportunities.service import OpportunityService

        member_count = await self.members.count(tenant_id, campaign_id)
        converted_leads = await LeadService(self.session).count_for_campaign(
            tenant_id, campaign_id, status=LeadStatus.CONVERTED.value
        )
        won_count, won_value = await OpportunityService(self.session).won_attribution_for_campaign(
            tenant_id, campaign_id
        )
        actual_cost = row.actual_cost
        return CampaignRoiResponse(
            campaign_id=row.id,
            member_count=member_count,
            converted_leads=converted_leads,
            won_opportunity_count=won_count,
            won_opportunity_value=won_value,
            budgeted_cost=row.budgeted_cost,
            actual_cost=actual_cost,
            expected_revenue=row.expected_revenue,
            roi=compute_roi_percent(won_opportunity_value=won_value, actual_cost=actual_cost),
        )

    def _to_response(self, row: Campaign) -> CampaignResponse:
        return CampaignResponse.model_validate(row).model_copy(
            update={
                "campaign_type": CampaignType(row.campaign_type),
                "status": CampaignStatus(row.status),
            }
        )

    async def _to_member_response(
        self, tenant_id: UUID, row: CampaignMember
    ) -> CampaignMemberResponse:
        member_type = CampaignMemberType(row.member_type)
        return CampaignMemberResponse.model_validate(row).model_copy(
            update={
                "member_type": member_type,
                "member_status": CampaignMemberStatus(row.member_status),
                "member_label": await self._member_label(tenant_id, member_type, row.member_id),
            }
        )

    async def _require(self, tenant_id: UUID, campaign_id: UUID) -> Campaign:
        row = await self.repo.get(tenant_id, campaign_id)
        if row is None:
            raise ResourceNotFoundError("Campaign not found")
        return row

    async def _require_owner(self, tenant_id: UUID, owner_id: UUID) -> None:
        statement = select(User.id).where(User.tenant_id == tenant_id, User.id == owner_id)
        result = await self.session.execute(statement)
        if result.scalar_one_or_none() is None:
            raise ValidationError("Owner not found")

    async def _validate_member(
        self,
        tenant_id: UUID,
        member_type: CampaignMemberType,
        member_id: UUID,
    ) -> None:
        try:
            if member_type is CampaignMemberType.LEAD:
                from app.crm.leads.service import LeadService

                await LeadService(self.session).get(tenant_id, member_id)
                return
            if member_type is CampaignMemberType.CONTACT:
                from app.crm.contacts.service import ContactService

                await ContactService(self.session).get(tenant_id, member_id)
                return
        except ResourceNotFoundError as exc:
            raise ValidationError(f"Related {member_type.value} was not found") from exc
        raise ValidationError("member_type is not allowed")

    async def _member_label(
        self,
        tenant_id: UUID,
        member_type: CampaignMemberType,
        member_id: UUID,
    ) -> str | None:
        try:
            if member_type is CampaignMemberType.LEAD:
                from app.crm.leads.service import LeadService

                lead = await LeadService(self.session).get(tenant_id, member_id)
                return lead.display_name
            if member_type is CampaignMemberType.CONTACT:
                from app.crm.contacts.service import ContactService

                contact = await ContactService(self.session).get(tenant_id, member_id)
                return contact.name
        except ResourceNotFoundError:
            return None
        return None

    def _snapshot(self, row: Campaign) -> dict[str, object]:
        return {
            "name": row.name,
            "campaign_type": row.campaign_type,
            "status": row.status,
            "start_date": row.start_date.isoformat() if row.start_date else None,
            "end_date": row.end_date.isoformat() if row.end_date else None,
            "budgeted_cost": str(row.budgeted_cost) if row.budgeted_cost is not None else None,
            "actual_cost": str(row.actual_cost) if row.actual_cost is not None else None,
            "expected_revenue": (
                str(row.expected_revenue) if row.expected_revenue is not None else None
            ),
            "owner_id": str(row.owner_id) if row.owner_id else None,
        }

    def _member_snapshot(self, row: CampaignMember) -> dict[str, object]:
        return {
            "campaign_id": str(row.campaign_id),
            "member_type": row.member_type,
            "member_id": str(row.member_id),
            "member_status": row.member_status,
        }
