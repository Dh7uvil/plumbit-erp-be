"""Integration tests for pipeline service and repository."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.core.enums import PipelineStageKind
from app.common.schemas.pagination import PageParams
from app.crm.pipelines.schemas import PipelineStageCreate
from app.crm.pipelines.service import PipelineService
from app.db.session import async_session_factory, transaction
from tests.conftest import provision_admin


@pytest.mark.asyncio
async def test_add_stage_to_default_pipeline() -> None:
    tenant_id, _email, _password = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session, transaction(session):
        actor_user_id = (
            await session.execute(select(User.id).where(User.tenant_id == tenant_uuid).limit(1))
        ).scalar_one()
        service = PipelineService(session)
        pipelines, _total = await service.list(
            tenant_uuid,
            page=PageParams(page=1, page_size=1),
            is_default=True,
        )
        assert pipelines
        pipeline_id = pipelines[0].id
        stage = await service.create_stage(
            tenant_uuid,
            pipeline_id,
            PipelineStageCreate(
                name="Custom intro",
                sort_order=0,
                probability="5",
                stage_kind=PipelineStageKind.OPEN,
            ),
            actor_user_id=actor_user_id,
        )
        assert stage.pipeline_id == pipeline_id
