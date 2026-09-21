"""Integration tests for opportunity service numbering."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.crm.opportunities.schemas import OpportunityCreate
from app.crm.opportunities.service import OpportunityService
from app.db.session import async_session_factory
from tests.conftest import provision_admin


@pytest.mark.asyncio
async def test_opportunity_numbers_are_unique_per_tenant() -> None:
    tenant_id, _email, _password = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        actor_user_id = (
            await session.execute(select(User.id).where(User.tenant_id == tenant_uuid).limit(1))
        ).scalar_one()
        service = OpportunityService(session)
        first = await service.create(
            tenant_uuid,
            OpportunityCreate(name="First deal"),
            actor_user_id=actor_user_id,
        )
        second = await service.create(
            tenant_uuid,
            OpportunityCreate(name="Second deal"),
            actor_user_id=actor_user_id,
        )
    assert first.opportunity_number != second.opportunity_number
    assert first.opportunity_number.startswith("OPP-")
    assert second.opportunity_number.startswith("OPP-")
