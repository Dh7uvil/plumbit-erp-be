"""Integration tests for campaign service."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.core.enums import CampaignMemberType, CampaignStatus, CampaignType
from app.core.exceptions import DuplicateResourceError, ValidationError
from app.crm.campaigns.schemas import (
    CampaignCreate,
    CampaignMemberCreate,
)
from app.crm.campaigns.service import CampaignService
from app.crm.leads.schemas import LeadCreate
from app.crm.leads.service import LeadService
from app.db.session import async_session_factory
from tests.conftest import provision_admin


@pytest.mark.asyncio
async def test_campaign_members_and_roi() -> None:
    tenant_id, _email, _password = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        actor_user_id = (
            await session.execute(select(User.id).where(User.tenant_id == tenant_uuid).limit(1))
        ).scalar_one()
        campaigns = CampaignService(session)
        leads = LeadService(session)
        campaign = await campaigns.create(
            tenant_uuid,
            CampaignCreate(
                name="Spring email",
                campaign_type=CampaignType.EMAIL,
                status=CampaignStatus.ACTIVE,
                actual_cost=Decimal("50.0000"),
                expected_revenue=Decimal("200.0000"),
            ),
            actor_user_id=actor_user_id,
        )
        lead = await leads.create(
            tenant_uuid,
            LeadCreate(company_name="Campaign Co", campaign_id=campaign.id),
            actor_user_id=actor_user_id,
        )
        member = await campaigns.add_member(
            tenant_uuid,
            campaign.id,
            CampaignMemberCreate(
                member_type=CampaignMemberType.LEAD,
                member_id=lead.id,
            ),
            actor_user_id=actor_user_id,
        )
        assert member.member_type is CampaignMemberType.LEAD
        with pytest.raises(DuplicateResourceError):
            await campaigns.add_member(
                tenant_uuid,
                campaign.id,
                CampaignMemberCreate(
                    member_type=CampaignMemberType.LEAD,
                    member_id=lead.id,
                ),
                actor_user_id=actor_user_id,
            )
        roi = await campaigns.roi(tenant_uuid, campaign.id)
        assert roi.member_count == 1
        assert roi.converted_leads == 0
        assert roi.won_opportunity_value == Decimal("0")
        assert roi.roi == Decimal("-100.0000")


@pytest.mark.asyncio
async def test_cancelled_campaign_cannot_be_attributed() -> None:
    tenant_id, _email, _password = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        actor_user_id = (
            await session.execute(select(User.id).where(User.tenant_id == tenant_uuid).limit(1))
        ).scalar_one()
        campaigns = CampaignService(session)
        campaign = await campaigns.create(
            tenant_uuid,
            CampaignCreate(
                name="Cancelled push",
                campaign_type=CampaignType.SOCIAL,
                status=CampaignStatus.CANCELLED,
            ),
            actor_user_id=actor_user_id,
        )
        with pytest.raises(ValidationError):
            await LeadService(session).create(
                tenant_uuid,
                LeadCreate(company_name="No campaign", campaign_id=campaign.id),
                actor_user_id=actor_user_id,
            )
