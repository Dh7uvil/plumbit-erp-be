"""Note slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.notes.service import NoteService
from app.db.session import get_db


def get_note_service(session: Annotated[AsyncSession, Depends(get_db)]) -> NoteService:
    return NoteService(session)


NoteServiceDependency = Annotated[NoteService, Depends(get_note_service)]
