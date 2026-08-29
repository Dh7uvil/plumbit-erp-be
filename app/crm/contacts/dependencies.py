"""Contact slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.contacts.service import ContactService
from app.db.session import get_db


def get_contact_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ContactService:
    return ContactService(session)


ContactServiceDependency = Annotated[ContactService, Depends(get_contact_service)]
