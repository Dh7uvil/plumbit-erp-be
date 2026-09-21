"""Pipeline slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.pipelines.service import PipelineService
from app.db.session import get_db


def get_pipeline_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PipelineService:
    return PipelineService(session)


PipelineServiceDependency = Annotated[PipelineService, Depends(get_pipeline_service)]
