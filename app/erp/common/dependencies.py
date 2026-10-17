"""FastAPI dependencies for shared ERP helpers."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.common.party_defaults import PartyDefaultsService


async def get_party_defaults_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PartyDefaultsService:
    return PartyDefaultsService(session)


PartyDefaultsServiceDependency = Annotated[
    PartyDefaultsService, Depends(get_party_defaults_service)
]
