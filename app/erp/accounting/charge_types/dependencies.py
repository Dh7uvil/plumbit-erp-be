"""Charge type slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.charge_types.service import ChargeTypeService


def get_charge_type_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ChargeTypeService:
    return ChargeTypeService(session)


ChargeTypeServiceDependency = Annotated[ChargeTypeService, Depends(get_charge_type_service)]
