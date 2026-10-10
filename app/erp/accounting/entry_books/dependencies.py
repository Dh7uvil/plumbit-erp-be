"""Entry book dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.entry_books.service import EntryBookService


def get_entry_book_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EntryBookService:
    return EntryBookService(session)


EntryBookServiceDependency = Annotated[EntryBookService, Depends(get_entry_book_service)]
