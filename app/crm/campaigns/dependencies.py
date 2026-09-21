"""Campaign slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.campaigns.service import CampaignService
from app.db.session import get_db


def get_campaign_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CampaignService:
    return CampaignService(session)


CampaignServiceDependency = Annotated[CampaignService, Depends(get_campaign_service)]
