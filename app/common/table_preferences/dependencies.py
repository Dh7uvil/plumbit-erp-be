"""Slice-level FastAPI dependencies for table preferences."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.table_preferences.service import TablePreferenceService
from app.db.session import get_db


def get_table_preference_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TablePreferenceService:
    return TablePreferenceService(session)


TablePreferenceServiceDependency = Annotated[
    TablePreferenceService, Depends(get_table_preference_service)
]
