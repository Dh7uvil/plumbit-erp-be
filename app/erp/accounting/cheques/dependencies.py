"""Cheque slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.accounting.cheques.service import ChequeService


def get_cheque_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> ChequeService:
    return ChequeService(session, actor_permissions=current_user.permissions)


ChequeServiceDependency = Annotated[ChequeService, Depends(get_cheque_service)]
