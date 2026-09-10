"""Delivery note slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.delivery_notes.service import DeliveryNoteService


def get_delivery_note_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> DeliveryNoteService:
    return DeliveryNoteService(session, actor_permissions=current_user.permissions)


DeliveryNoteServiceDependency = Annotated[DeliveryNoteService, Depends(get_delivery_note_service)]
