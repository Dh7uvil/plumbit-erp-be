"""Integration tests for lead service numbering."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.crm.leads.schemas import LeadCreate
from app.crm.leads.service import LeadService
from app.db.session import async_session_factory
from tests.conftest import provision_admin


@pytest.mark.asyncio
async def test_lead_numbers_are_unique_per_tenant() -> None:
    tenant_id, _email, _password = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        actor_user_id = (
            await session.execute(select(User.id).where(User.tenant_id == tenant_uuid).limit(1))
        ).scalar_one()
        service = LeadService(session)
        first = await service.create(
            tenant_uuid,
            LeadCreate(first_name="One"),
            actor_user_id=actor_user_id,
        )
        second = await service.create(
            tenant_uuid,
            LeadCreate(first_name="Two"),
            actor_user_id=actor_user_id,
        )
    assert first.lead_number != second.lead_number
    assert first.lead_number.startswith("LEAD-")
    assert second.lead_number.startswith("LEAD-")
