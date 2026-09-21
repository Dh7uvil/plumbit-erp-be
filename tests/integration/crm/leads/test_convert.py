"""Integration tests for lead conversion orchestration."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.core.enums import LeadStatus
from app.crm.leads.schemas import LeadConvert, LeadConvertContact, LeadConvertCustomerCreate
from app.crm.leads.service import LeadService
from app.crm.leads.schemas import LeadCreate
from app.db.session import async_session_factory
from tests.conftest import provision_admin


@pytest.mark.asyncio
async def test_convert_marks_lead_converted() -> None:
    tenant_id, _email, _password = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        actor_user_id = (
            await session.execute(select(User.id).where(User.tenant_id == tenant_uuid).limit(1))
        ).scalar_one()
        service = LeadService(session, actor_permissions=frozenset({"crm.lead.convert"}))
        lead = await service.create(
            tenant_uuid,
            LeadCreate(company_name="Integration Convert"),
            actor_user_id=actor_user_id,
        )
        result = await service.convert(
            tenant_uuid,
            lead.id,
            LeadConvert(
                new_customer=LeadConvertCustomerCreate(name="Integration Convert"),
                contact=LeadConvertContact(name="Primary Contact", is_primary=True),
            ),
            actor_user_id=actor_user_id,
            expected_version=lead.version,
            idempotency_key="integration-convert-key",
            request_hash="hash",
            endpoint="/api/v1/leads/convert",
        )
    assert result.lead.status == LeadStatus.CONVERTED
    assert result.customer_id == result.lead.converted_customer_id
    assert result.contact_id == result.lead.converted_contact_id
