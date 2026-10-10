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
    actor_permissions: frozenset[str] | None = None,
) -> UUID | None:
    """Create and post a delivery note when auto_stock_document is enabled."""

    from app.erp.sales_invoices.models import SalesInvoice
    from app.erp.sales_invoices.repository import SalesInvoiceRepository
    from app.inventory_management.delivery_notes.service import DeliveryNoteService

    repo = SalesInvoiceRepository(session)
    invoice = await repo.get(tenant_id, invoice_id)
    if invoice is None or not getattr(invoice, "auto_stock_document", False):
        return None
    if not invoice.lines:
        raise ValidationError("Cannot update stock without invoice lines")
    product_lines = [line for line in invoice.lines if line.product_id is not None]
    if not product_lines:
        raise ValidationError("Cannot update stock without product lines on the invoice")

    delivery = DeliveryNoteService(session, actor_permissions=actor_permissions)
    return await delivery.create_and_post_from_sales_invoice_auto_stock(
        tenant_id,
        invoice_id=invoice_id,
        actor_user_id=actor_user_id,
    )


async def cancel_sales_invoice_auto_stock_if_any(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    invoice_id: UUID,
    actor_user_id: UUID,
    reason: str | None = None,
    actor_permissions: frozenset[str] | None = None,
) -> None:
    """Cancel delivery notes that were auto-created from this invoice (Update Stock)."""

    from app.inventory_management.delivery_notes.service import DeliveryNoteService

    delivery = DeliveryNoteService(session, actor_permissions=actor_permissions)
    await delivery.cancel_auto_stock_notes_for_sales_invoice(
        tenant_id,
        invoice_id=invoice_id,
        actor_user_id=actor_user_id,
        reason=reason,
    )


async def post_purchase_invoice_stock_if_requested(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    invoice_id: UUID,
    actor_user_id: UUID,
    actor_permissions: frozenset[str] | None = None,
) -> UUID | None:
    """Create and post a goods receipt when auto_stock_document is enabled."""

    from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository
    from app.inventory_management.goods_receipts.service import GoodsReceiptService

    repo = PurchaseInvoiceRepository(session)
    invoice = await repo.get(tenant_id, invoice_id)
    if invoice is None or not getattr(invoice, "auto_stock_document", False):
        return None
    product_lines = [
        line
        for line in invoice.lines
        if line.product_id is not None and line.line_type == "PRODUCT"
    ]
    if not product_lines:
        raise ValidationError("Cannot update stock without product lines on the purchase invoice")

    receipts = GoodsReceiptService(session, actor_permissions=actor_permissions)
    return await receipts.create_and_post_from_purchase_invoice_auto_stock(
        tenant_id,
        invoice_id=invoice_id,
        actor_user_id=actor_user_id,
    )


async def cancel_purchase_invoice_auto_stock_if_any(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    invoice_id: UUID,
    actor_user_id: UUID,
    reason: str | None = None,
    actor_permissions: frozenset[str] | None = None,
) -> None:
    from app.inventory_management.goods_receipts.service import GoodsReceiptService

    receipts = GoodsReceiptService(session, actor_permissions=actor_permissions)
    await receipts.cancel_auto_stock_receipts_for_purchase_invoice(
        tenant_id,
        invoice_id=invoice_id,
        actor_user_id=actor_user_id,
        reason=reason,
    )
