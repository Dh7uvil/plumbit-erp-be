from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.salesmen.service import SalesmanService


def get_salesman_service(session: Annotated[AsyncSession, Depends(get_db)]) -> SalesmanService:
    return SalesmanService(session)


SalesmanServiceDependency = Annotated[SalesmanService, Depends(get_salesman_service)]
