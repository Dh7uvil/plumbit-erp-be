"""CRM setup masters seeded for every tenant."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.foundations.defaults import (
    DEFAULT_LEAD_SOURCES,
    DEFAULT_PIPELINE_NAME,
    DEFAULT_PIPELINE_STAGES,
)
from app.crm.lead_sources.models import LeadSource
from app.crm.pipelines.models import Pipeline, PipelineStage


async def seed_crm_foundations(session: AsyncSession, tenant_id: UUID) -> None:
    """Insert default pipeline, stages, and lead sources when missing."""

    existing_pipeline = (
        await session.execute(
            select(Pipeline.id).where(
                Pipeline.tenant_id == tenant_id,
                Pipeline.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing_pipeline is None:
        pipeline = Pipeline(
            tenant_id=tenant_id,
            name=DEFAULT_PIPELINE_NAME,
            is_default=True,
        )
        session.add(pipeline)
        await session.flush()
        for name, sort_order, probability, stage_kind in DEFAULT_PIPELINE_STAGES:
            session.add(
                PipelineStage(
                    tenant_id=tenant_id,
                    pipeline_id=pipeline.id,
                    name=name,
                    sort_order=sort_order,
                    probability=probability,
                    stage_kind=stage_kind.value,
                )
            )

    existing_lead_sources = set(
        (
            await session.execute(
                select(LeadSource.name).where(
                    LeadSource.tenant_id == tenant_id,
                    LeadSource.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for name in DEFAULT_LEAD_SOURCES:
        if name in existing_lead_sources:
            continue
        session.add(LeadSource(tenant_id=tenant_id, name=name))

    await session.flush()
