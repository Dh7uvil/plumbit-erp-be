"""Agora route dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.integrations.agora.rtc_service import AgoraRTCService


def get_agora_rtc_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AgoraRTCService:
    return AgoraRTCService(session)


AgoraRTCServiceDependency = Annotated[AgoraRTCService, Depends(get_agora_rtc_service)]
