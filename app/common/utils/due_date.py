"""Derive AR/AP due dates from payment terms."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundError
from app.erp.accounting.repository import PaymentTermRepository


async def due_date_from_terms(
    session: AsyncSession,
    tenant_id: UUID,
    payment_terms_id: UUID | None,
    document_date: date,
) -> date | None:
    """Return document_date + payment-term days, or None when no term is set."""

    if payment_terms_id is None:
        return None
    term = await PaymentTermRepository(session).get(tenant_id, payment_terms_id)
    if term is None:
        raise ResourceNotFoundError("Payment term not found")
    return document_date + timedelta(days=term.days)
