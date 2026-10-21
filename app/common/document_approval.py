"""Per-document approval when org settings require workflow for non-admin creators."""

from __future__ import annotations

from uuid import UUID


def effective_document_requires_approval(
    org_requires: bool,
    created_by: UUID | None,
    admin_creator_ids: frozenset[UUID],
) -> bool:
    """Return whether this document must follow submit/approve before send/confirm/issue."""
    if not org_requires:
        return False
    if created_by is not None and created_by in admin_creator_ids:
        return False
    return True
