"""Revalue FIFO layers from purchase invoice + linked cost sheet / voucher debits (org currency)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.pagination import PageParams
from app.common.utils.currency import quantize_money
from app.core.enums import CostSheetMode, CostSheetStatus
from app.erp.accounting.ledger.inventory_posting import SOURCE_GOODS_RECEIPT
from app.erp.accounting.vouchers.models import Voucher
from app.erp.cost_sheets.models import CostSheet, CostSheetJournalLine
from app.erp.purchase_invoices.models import PurchaseInvoice
from app.inventory_management.costing.repository import CostingRepository
from app.inventory_management.costing.service import CostingService
from app.inventory_management.products.repository import ProductRepository
from app.inventory_management.products.service import ProductService
from app.inventory_management.stock.repository import StockBalanceRepository

_ZERO = Decimal("0")


async def _product_has_fifo_layers(
    session: AsyncSession,
    tenant_id: UUID,
    product_id: UUID,
) -> bool:
    balance_repo = StockBalanceRepository(session)
    cost_repo = CostingRepository(session)
    balances, _ = await balance_repo.list(
        tenant_id,
        page=PageParams(page=1, page_size=500),
        filters={"product_id": product_id},
    )
    for balance in balances:
        layers = await cost_repo.list_positive_fifo(
            tenant_id, balance.warehouse_id, product_id
        )
        if layers:
            return True
    return False


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
                CostSheet.sheet_mode == CostSheetMode.JOURNAL.value,
                or_(
                    (
                        CostSheet.source_document_type == "PURCHASE_INVOICE"
                    )
                    & (CostSheet.source_document_id == purchase_invoice_id),
                    CostSheet.purchase_invoice_id == purchase_invoice_id,
                ),
            )
        )
    ).scalars()
    seen_sheet_ids: set[UUID] = set()
    for sheet in cs_rows:
        if sheet.id in seen_sheet_ids:
            continue
        seen_sheet_ids.add(sheet.id)
        fx = sheet.exchange_rate if sheet.exchange_rate is not None else Decimal("1")
        line_rows = (
            await session.execute(
                select(CostSheetJournalLine.debit, CostSheetJournalLine.capitalize).where(
                    CostSheetJournalLine.tenant_id == tenant_id,
                    CostSheetJournalLine.cost_sheet_id == sheet.id,
                )
            )
        ).all()
        for debit, capitalize in line_rows:
            if not capitalize:
                continue
            amount = quantize_money(debit)
            if amount <= _ZERO:
                continue
            total += quantize_money(amount * fx)
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
    product_ids_revalued: set[UUID] = set()
    fallback_cost: dict[UUID, tuple[Decimal, Decimal]] = {}

    for line in product_lines:
        assert line.product_id is not None
        line_base = quantize_money(line.amount * rate)
        share = line_base / base_goods if base_goods > _ZERO else _ZERO
        allocated_extra = quantize_money(extra * share)
        line_total = quantize_money(line_base + allocated_extra)
        landed_unit = quantize_money(line_total / line.quantity)

        receipt_id = line.goods_receipt_id
        receipt_line_id = line.goods_receipt_line_id
        revalued = False
        if receipt_id is not None and receipt_line_id is not None:
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
                revalued = True
        if revalued:
            product_ids_revalued.add(line.product_id)
        else:
            prev_total, prev_qty = fallback_cost.get(line.product_id, (_ZERO, _ZERO))
            fallback_cost[line.product_id] = (
                prev_total + line_total,
                prev_qty + line.quantity,
            )

    if product_ids_revalued:
        await ProductService(session).sync_avg_cost_from_fifo(tenant_id, product_ids_revalued)

    product_repo = ProductRepository(session)
    for product_id, (line_total, line_qty) in fallback_cost.items():
        if product_id in product_ids_revalued:
            continue
        if line_qty <= _ZERO:
            continue
        if await _product_has_fifo_layers(session, tenant_id, product_id):
            continue
        avg = quantize_money(line_total / line_qty)
        await product_repo.update(tenant_id, product_id, {"purchase_rate": avg})
