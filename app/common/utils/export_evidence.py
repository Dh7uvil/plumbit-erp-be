"""FTA export-evidence probe: BL/AWB number or customs/BL attachments on the shipment."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.attachments.models import Attachment
from app.core.enums import AttachmentCategory, AttachmentEntityType
from app.inventory_management.delivery_notes.models import DeliveryNote
from app.inventory_management.shipments.models import Shipment

_EVIDENCE_CATEGORIES = frozenset(
    {AttachmentCategory.BL_DOCUMENT.value, AttachmentCategory.CUSTOMS_DOC.value}
)


async def has_export_evidence(
    session: AsyncSession,
    tenant_id: UUID,
    delivery_note_ids: Sequence[UUID],
) -> bool:
    """True when every delivery note is on a shipment with BL/AWB or customs evidence."""

    if not delivery_note_ids:
        return True
    notes = list(
        (
            await session.execute(
                select(DeliveryNote).where(
                    DeliveryNote.tenant_id == tenant_id,
                    DeliveryNote.id.in_(list(delivery_note_ids)),
                    DeliveryNote.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    )
    if len(notes) != len(set(delivery_note_ids)):
        return False
    shipment_ids = [note.shipment_id for note in notes if note.shipment_id is not None]
    if len(shipment_ids) != len(notes):
        return False
    unique_ids = list(set(shipment_ids))
    shipments = list(
        (
            await session.execute(
                select(Shipment).where(
                    Shipment.tenant_id == tenant_id,
                    Shipment.id.in_(unique_ids),
                    Shipment.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    )
    by_id = {row.id: row for row in shipments}
    missing = [shipment_id for shipment_id in unique_ids if shipment_id not in by_id]
    if missing:
        return False
    need_attachment = [
        shipment.id for shipment in shipments if not (shipment.bl_awb_number or "").strip()
    ]
    if not need_attachment:
        return True
    evidenced = set(
        (
            await session.execute(
                select(Attachment.entity_id).where(
                    Attachment.tenant_id == tenant_id,
                    Attachment.entity_type == AttachmentEntityType.SHIPMENT.value,
                    Attachment.entity_id.in_(need_attachment),
                    Attachment.category.in_(_EVIDENCE_CATEGORIES),
                    Attachment.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    )
    return all(shipment_id in evidenced for shipment_id in need_attachment)
