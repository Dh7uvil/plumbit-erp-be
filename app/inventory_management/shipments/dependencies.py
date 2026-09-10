"""Shipment slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.shipments.service import ShipmentService


def get_shipment_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> ShipmentService:
    return ShipmentService(session, actor_permissions=current_user.permissions)


ShipmentServiceDependency = Annotated[ShipmentService, Depends(get_shipment_service)]
