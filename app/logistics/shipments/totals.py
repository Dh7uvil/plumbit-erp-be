"""Roll up package weights and counts onto a shipment header."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.currency import quantize_quantity
from app.core.enums import PackageStatus
from app.inventory_management.delivery_notes.repository import DeliveryNoteRepository
from app.inventory_management.packages.repository import PackageRepository
from app.logistics.shipments.repository import ShipmentRepository

_ZERO = Decimal("0")


async def apply_shipment_package_totals(
    session: AsyncSession, tenant_id: UUID, shipment_id: UUID
) -> None:
    """Overwrite shipment weight and package-count fields from attached packages.

    Empty shipments (no delivery notes) keep all three fields null. Notes with no
    active packages store ``total_packages = 0`` and null weights.
    """

    shipment = await ShipmentRepository(session).get(tenant_id, shipment_id)
    if shipment is None:
        return
    notes = await DeliveryNoteRepository(session).list_for_shipment(tenant_id, shipment_id)
    if not notes:
        shipment.gross_weight = None
        shipment.net_weight = None
        shipment.total_packages = None
        await session.flush()
        return

    packages = await PackageRepository(session).list_for_delivery_notes(
        tenant_id, [note.id for note in notes]
    )
    active = [pkg for pkg in packages if pkg.status != PackageStatus.CANCELLED.value]
    shipment.total_packages = len(active)
    has_gross = any(pkg.gross_weight is not None for pkg in active)
    has_net = any(pkg.net_weight is not None for pkg in active)
    shipment.gross_weight = (
        quantize_quantity(sum((pkg.gross_weight or _ZERO) for pkg in active)) if has_gross else None
    )
    shipment.net_weight = (
        quantize_quantity(sum((pkg.net_weight or _ZERO) for pkg in active)) if has_net else None
    )
    await session.flush()
