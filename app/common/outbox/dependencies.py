"""Outbox slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.outbox.service import OutboxService
from app.db.session import get_db


def get_outbox_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> OutboxService:
    return OutboxService(session)


OutboxServiceDependency = Annotated[OutboxService, Depends(get_outbox_service)]
