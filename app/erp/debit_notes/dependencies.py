"""Debit note slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.debit_notes.service import DebitNoteService


def get_debit_note_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> DebitNoteService:
    return DebitNoteService(session, actor_permissions=current_user.permissions)


DebitNoteServiceDependency = Annotated[DebitNoteService, Depends(get_debit_note_service)]
