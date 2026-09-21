"""Integration tests for activity service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth.catalog import ACTIVITY_DELETE, ACTIVITY_UPDATE
from app.auth.models import User
from app.common.schemas.pagination import PageParams
from app.core.enums import ActivityStatus, ActivityType, CrmRelatedEntityType
from app.core.exceptions import InvalidStatusTransitionError
from app.crm.activities.schemas import ActivityComplete, ActivityCreate
from app.crm.activities.service import ActivityService
from app.crm.leads.schemas import LeadCreate
from app.crm.leads.service import LeadService
from app.db.session import async_session_factory
from tests.conftest import provision_admin


@pytest.mark.asyncio
async def test_activity_complete_and_overdue_filter() -> None:
    tenant_id, _email, _password = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    permissions = frozenset({ACTIVITY_UPDATE, ACTIVITY_DELETE})
    async with async_session_factory() as session:
        actor_user_id = (
            await session.execute(select(User.id).where(User.tenant_id == tenant_uuid).limit(1))
        ).scalar_one()
        lead = await LeadService(session).create(
            tenant_uuid,
            LeadCreate(company_name="Activity Co"),
            actor_user_id=actor_user_id,
        )
        service = ActivityService(session, actor_permissions=permissions)
        past_due = datetime.now(UTC) - timedelta(days=1)
        created = await service.create(
            tenant_uuid,
            ActivityCreate(
                activity_type=ActivityType.TASK,
                subject="Follow up",
                related_entity_type=CrmRelatedEntityType.LEAD,
                related_entity_id=lead.id,
                due_at=past_due,
                owner_id=actor_user_id,
            ),
            actor_user_id=actor_user_id,
        )
        assert created.status is ActivityStatus.OPEN
        assert "complete" in created.available_actions

        overdue, total = await service.list(
            tenant_uuid, page=PageParams(page=1, page_size=25), overdue=True
        )
        assert total == 1
        assert overdue[0].id == created.id

        completed = await service.complete(
            tenant_uuid,
            created.id,
            ActivityComplete(outcome="Reached"),
            actor_user_id=actor_user_id,
        )
        assert completed.status is ActivityStatus.COMPLETED
        assert completed.outcome == "Reached"
        assert completed.available_actions == []

        with pytest.raises(InvalidStatusTransitionError):
            await service.complete(
                tenant_uuid, created.id, ActivityComplete(), actor_user_id=actor_user_id
            )
