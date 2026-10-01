"""Search dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.search.service import SearchService
from app.db.session import get_db


def get_search_service(session: Annotated[AsyncSession, Depends(get_db)]) -> SearchService:
    return SearchService(session)


SearchServiceDependency = Annotated[SearchService, Depends(get_search_service)]
