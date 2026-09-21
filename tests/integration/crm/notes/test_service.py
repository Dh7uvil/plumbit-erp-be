"""Integration tests for note service."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.core.enums import CrmRelatedEntityType
from app.crm.leads.schemas import LeadCreate
from app.crm.leads.service import LeadService
from app.crm.notes.schemas import NoteCreate
from app.crm.notes.service import NoteService
from app.db.session import async_session_factory
from tests.conftest import provision_admin


@pytest.mark.asyncio
async def test_note_create_on_lead() -> None:
    tenant_id, _email, _password = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        actor_user_id = (
            await session.execute(select(User.id).where(User.tenant_id == tenant_uuid).limit(1))
        ).scalar_one()
        lead = await LeadService(session).create(
            tenant_uuid,
            LeadCreate(company_name="Note Co"),
            actor_user_id=actor_user_id,
        )
        note = await NoteService(session).create(
            tenant_uuid,
            NoteCreate(
                body="Discussed pricing",
                related_entity_type=CrmRelatedEntityType.LEAD,
                related_entity_id=lead.id,
            ),
            actor_user_id=actor_user_id,
        )
    assert note.body == "Discussed pricing"
    assert note.related_entity_type is CrmRelatedEntityType.LEAD
    assert note.created_by == actor_user_id
