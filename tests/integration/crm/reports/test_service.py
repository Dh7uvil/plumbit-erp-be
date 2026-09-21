"""Integration tests for CRM report aggregates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.common.schemas.pagination import PageParams
from app.core.enums import ActivityType, CrmRelatedEntityType, LeadStatus, PipelineStageKind
from app.crm.activities.schemas import ActivityCreate
from app.crm.activities.service import ActivityService
from app.crm.leads.schemas import LeadCreate, LeadStatusChange
from app.crm.leads.service import LeadService
from app.crm.opportunities.schemas import OpportunityCreate
from app.crm.opportunities.service import OpportunityService
from app.crm.pipelines.service import PipelineService
from app.crm.reports.service import CrmReportService
from app.db.session import async_session_factory
from app.erp.exchange_rates.service import CurrencyService
from tests.conftest import provision_admin


async def _actor_and_pipeline(session, tenant_uuid: UUID):
    actor_user_id = (
        await session.execute(select(User.id).where(User.tenant_id == tenant_uuid).limit(1))
    ).scalar_one()
    pipelines = PipelineService(session)
    listed, _total = await pipelines.list(
        tenant_uuid, page=PageParams(page=1, page_size=1), is_default=True
    )
    pipeline = await pipelines.get(tenant_uuid, listed[0].id)
    open_stage = next(
        stage for stage in pipeline.stages if stage.stage_kind == PipelineStageKind.OPEN
    )
    currency_id = (await CurrencyService(session).get_base(tenant_uuid)).id
    return actor_user_id, pipeline, open_stage, currency_id


@pytest.mark.asyncio
async def test_pipeline_funnel_and_dashboard_aggregates() -> None:
    tenant_id, _email, _password = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        actor_user_id, pipeline, open_stage, currency_id = await _actor_and_pipeline(
            session, tenant_uuid
        )
        await OpportunityService(session).create(
            tenant_uuid,
            OpportunityCreate(
                name="Open deal",
                pipeline_id=pipeline.id,
                stage_id=open_stage.id,
                amount=Decimal("200.0000"),
                currency_id=currency_id,
                probability=Decimal("50.0000"),
                expected_close_date=date.today().replace(day=1),
            ),
            actor_user_id=actor_user_id,
        )
        reports = CrmReportService(session)
        pipeline_report = await reports.sales_pipeline(tenant_uuid, pipeline_id=pipeline.id)
        assert pipeline_report.opportunity_count == 1
        assert pipeline_report.total_amount == Decimal("200.0000")
        assert pipeline_report.total_weighted_amount == Decimal("100.0000")
        funnel = await reports.sales_funnel(tenant_uuid, pipeline_id=pipeline.id)
        assert funnel.pipeline_id == pipeline.id
        assert sum(line.opportunity_count for line in funnel.lines) == 1
        dashboard = await reports.dashboard(tenant_uuid)
        assert dashboard.open_pipeline_count == 1
        assert dashboard.open_pipeline_value == Decimal("200.0000")
        assert dashboard.closing_this_month_count == 1


@pytest.mark.asyncio
async def test_win_loss_lead_conversion_and_activity_reports() -> None:
    tenant_id, _email, _password = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        actor_user_id, pipeline, open_stage, currency_id = await _actor_and_pipeline(
            session, tenant_uuid
        )
        opportunities = OpportunityService(session)
        created = await opportunities.create(
            tenant_uuid,
            OpportunityCreate(
                name="Won deal",
                pipeline_id=pipeline.id,
                stage_id=open_stage.id,
                amount=Decimal("80.0000"),
                currency_id=currency_id,
                expected_close_date=date(2026, 9, 15),
            ),
            actor_user_id=actor_user_id,
        )
        await opportunities.win(
            tenant_uuid,
            created.id,
            actor_user_id=actor_user_id,
            expected_version=created.version,
        )
        leads = LeadService(session)
        new_lead = await leads.create(
            tenant_uuid,
            LeadCreate(company_name="New Co"),
            actor_user_id=actor_user_id,
        )
        contacted = await leads.create(
            tenant_uuid,
            LeadCreate(company_name="Contacted Co"),
            actor_user_id=actor_user_id,
        )
        await leads.change_status(
            tenant_uuid,
            contacted.id,
            LeadStatusChange(status=LeadStatus.CONTACTED),
            actor_user_id=actor_user_id,
            expected_version=contacted.version,
        )
        await ActivityService(session).create(
            tenant_uuid,
            ActivityCreate(
                activity_type=ActivityType.TASK,
                subject="Follow up",
                related_entity_type=CrmRelatedEntityType.LEAD,
                related_entity_id=new_lead.id,
            ),
            actor_user_id=actor_user_id,
        )
        reports = CrmReportService(session)
        win_loss = await reports.win_loss(
            tenant_uuid, from_date=date(2026, 9, 1), to_date=date(2026, 9, 30)
        )
        assert win_loss.won_count == 1
        assert win_loss.won_amount == Decimal("80.0000")
        conversion = await reports.lead_conversion(
            tenant_uuid, from_date=date(2020, 1, 1), to_date=date(2030, 1, 1)
        )
        assert conversion.lead_count >= 2
        assert conversion.converted_count == 0
        statuses = {line.group_key for line in conversion.lines}
        assert LeadStatus.NEW.value in statuses
        assert LeadStatus.CONTACTED.value in statuses
        activity = await reports.sales_activity(
            tenant_uuid, from_date=date(2020, 1, 1), to_date=date(2030, 1, 1)
        )
        assert activity.activity_count >= 1
        assert activity.open_count >= 1
