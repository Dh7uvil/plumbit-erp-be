"""Revalue FIFO layers from purchase invoice + linked cost sheet / voucher debits (org currency)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.currency import quantize_money
from app.core.enums import CostSheetStatus
from app.erp.accounting.ledger.inventory_posting import SOURCE_GOODS_RECEIPT
from app.erp.accounting.vouchers.models import Voucher
from app.erp.cost_sheets.models import CostSheet, CostSheetJournalLine
from app.erp.purchase_invoices.models import PurchaseInvoice, PurchaseInvoiceLine
from app.inventory_management.costing.service import CostingService
from app.inventory_management.products.service import ProductService

_ZERO = Decimal("0")


async def _linked_debit_total_org(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    purchase_invoice_id: UUID,
) -> Decimal:
    total = _ZERO
    voucher_rows = (
        await session.execute(
            select(Voucher).where(
                Voucher.tenant_id == tenant_id,
                Voucher.deleted_at.is_(None),
                Voucher.is_posted.is_(True),
                Voucher.source_document_type == "PURCHASE_INVOICE",
                Voucher.source_document_id == purchase_invoice_id,
            )
        )
    ).scalars()
    for row in voucher_rows:
        total += row.base_amount

    cs_rows = (
        await session.execute(
            select(CostSheet).where(
                CostSheet.tenant_id == tenant_id,
                CostSheet.deleted_at.is_(None),
                CostSheet.status == CostSheetStatus.CONFIRMED.value,
                CostSheet.journal_entry_id.isnot(None),
                CostSheet.source_document_type == "PURCHASE_INVOICE",
                CostSheet.source_document_id == purchase_invoice_id,
            )
        )
    ).scalars()
    for sheet in cs_rows:
        debits = (
            await session.execute(
                select(CostSheetJournalLine.debit).where(
                    CostSheetJournalLine.tenant_id == tenant_id,
                    CostSheetJournalLine.cost_sheet_id == sheet.id,
                )
            )
        ).scalars()
        total += sum((value for value in debits), _ZERO)
    return quantize_money(total)


async def refresh_purchase_invoice_landed_costs(
    session: AsyncSession,
    tenant_id: UUID,
    purchase_invoice_id: UUID,
) -> None:
    """Apply PI product line costs plus allocated linked debits to FIFO layers."""
    invoice = (
        await session.execute(
            select(PurchaseInvoice).where(
                PurchaseInvoice.tenant_id == tenant_id,
                PurchaseInvoice.id == purchase_invoice_id,
                PurchaseInvoice.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if invoice is None or not invoice.is_posted:
        return

    product_lines = [
        line
        for line in invoice.lines
        if line.line_type == "PRODUCT"
        and line.product_id is not None
        and line.quantity > _ZERO
    ]
    if not product_lines:
        return

    rate = invoice.exchange_rate
    base_goods = quantize_money(
        sum((quantize_money(line.amount * rate) for line in product_lines), _ZERO)
    )
    extra = await _linked_debit_total_org(
        session, tenant_id, purchase_invoice_id=purchase_invoice_id
    )

    costing = CostingService(session)
    product_ids: set[UUID] = set()

    for line in product_lines:
        line_base = quantize_money(line.amount * rate)
        share = line_base / base_goods if base_goods > _ZERO else _ZERO
        allocated_extra = quantize_money(extra * share)
        line_total = quantize_money(line_base + allocated_extra)
        landed_unit = quantize_money(line_total / line.quantity)

        receipt_id = line.goods_receipt_id
        receipt_line_id = line.goods_receipt_line_id
        if receipt_id is None or receipt_line_id is None:
            continue
        layers = await costing.layers_for_source(
            tenant_id,
            SOURCE_GOODS_RECEIPT,
            receipt_id,
            source_line_id=receipt_line_id,
        )
        for layer in layers:
            if layer.qty_remaining <= _ZERO:
                continue
            await costing.revalue(tenant_id, layer.id, landed_unit)
        product_ids.add(line.product_id)

    if product_ids:
        await ProductService(session).sync_avg_cost_from_fifo(tenant_id, product_ids)
