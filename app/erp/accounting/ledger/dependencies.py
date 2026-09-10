"""Journal entry slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.accounting.ledger.service import JournalEntryService


def get_journal_entry_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> JournalEntryService:
    return JournalEntryService(session, actor_permissions=current_user.permissions)


JournalEntryServiceDependency = Annotated[
    JournalEntryService, Depends(get_journal_entry_service)
]
