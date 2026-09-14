"""Resolve posted inventory journals by source document."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundError
from app.erp.accounting.ledger.schemas import JournalEntryResponse
from app.erp.accounting.ledger.service import JournalEntryService


async def journal_for_source(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    source_type: str,
    source_id: UUID,
    label: str,
    actor_permissions: frozenset[str] = frozenset(),
) -> JournalEntryResponse:
    journals = JournalEntryService(session, actor_permissions=actor_permissions)
    entry = await journals.repo.get_posted_for_source(tenant_id, source_type, source_id)
    if entry is None:
        raise ResourceNotFoundError(f"{label} has no journal entry")
    return await journals.get(tenant_id, entry.id)
