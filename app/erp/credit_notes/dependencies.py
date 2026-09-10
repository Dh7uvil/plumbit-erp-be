"""Credit note slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.credit_notes.service import CreditNoteService


def get_credit_note_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> CreditNoteService:
    return CreditNoteService(session, actor_permissions=current_user.permissions)


CreditNoteServiceDependency = Annotated[CreditNoteService, Depends(get_credit_note_service)]
