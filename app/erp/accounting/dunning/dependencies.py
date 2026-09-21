"""FastAPI dependencies for dunning."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.dunning.service import DunningRuleService, DunningService


def get_dunning_rule_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DunningRuleService:
    return DunningRuleService(session)


def get_dunning_service(session: Annotated[AsyncSession, Depends(get_db)]) -> DunningService:
    return DunningService(session)


DunningRuleServiceDependency = Annotated[DunningRuleService, Depends(get_dunning_rule_service)]
DunningServiceDependency = Annotated[DunningService, Depends(get_dunning_service)]
