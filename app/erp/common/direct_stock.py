"""Opt-in stock posting when commercial documents are posted (legacy Update Stock)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError


async def post_sales_invoice_stock_if_requested(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    invoice_id: UUID,
    actor_user_id: UUID,
) -> UUID | None:
    """Create and post a delivery note when auto_stock_document is enabled."""

    from app.erp.sales_invoices.models import SalesInvoice
    from app.erp.sales_invoices.repository import SalesInvoiceRepository

    repo = SalesInvoiceRepository(session)
    invoice = await repo.get(tenant_id, invoice_id)
    if invoice is None or not getattr(invoice, "auto_stock_document", False):
        return None
    if not invoice.lines:
        raise ValidationError("Cannot update stock without invoice lines")
    raise ValidationError(
        "Auto stock posting is configured but not yet linked for this invoice; "
        "post the delivery note manually or turn off Update Stock."
    )
