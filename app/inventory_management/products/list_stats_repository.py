"""Batch stock and trading snapshots for product list screens."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from dataclasses import replace

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import InvoiceDocumentStatus, StockDocumentStatus, WarehouseLocationType
from app.erp.sales_invoices.models import SalesInvoice, SalesInvoiceLine
from app.inventory_management.delivery_notes.models import DeliveryNote, DeliveryNoteLine
from app.inventory_management.goods_receipts.models import GoodsReceipt, GoodsReceiptLine
from app.inventory_management.stock.models import StockBalance
from app.inventory_management.warehouses.models import Warehouse

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ProductListStats:
    qty_on_hand: Decimal = _ZERO
    qty_opened: Decimal = _ZERO
    qty_committed: Decimal = _ZERO
    net_available: Decimal = _ZERO
    shop_qty: Decimal = _ZERO
    warehouse_qty: Decimal = _ZERO
    ordered_qty: Decimal = _ZERO
    last_sale_date: date | None = None
    last_sale_price: Decimal | None = None
    last_purchase_date: date | None = None
    last_purchase_price: Decimal | None = None


class ProductListStatsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def batch(self, tenant_id: UUID, product_ids: Sequence[UUID]) -> dict[UUID, ProductListStats]:
        if not product_ids:
            return {}
        ids = list(product_ids)
        result: dict[UUID, ProductListStats] = {pid: ProductListStats() for pid in ids}

        stock_rows = (
            await self.session.execute(
                select(
                    StockBalance.product_id,
                    func.coalesce(func.sum(StockBalance.qty_on_hand), 0),
                    func.coalesce(func.sum(StockBalance.qty_reserved), 0),
                    func.coalesce(func.sum(StockBalance.qty_incoming), 0),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    Warehouse.location_type == WarehouseLocationType.SHOP.value,
                                    StockBalance.qty_on_hand,
                                ),
                                else_=_ZERO,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    Warehouse.location_type
                                    == WarehouseLocationType.WAREHOUSE.value,
                                    StockBalance.qty_on_hand,
                                ),
                                else_=_ZERO,
                            )
                        ),
                        0,
                    ),
                )
                .outerjoin(Warehouse, Warehouse.id == StockBalance.warehouse_id)
                .where(
                    StockBalance.tenant_id == tenant_id,
                    StockBalance.product_id.in_(ids),
                )
                .group_by(StockBalance.product_id)
            )
        ).all()
        for row in stock_rows:
            pid, on_hand, reserved, incoming, shop, wh = row
            on_hand = Decimal(on_hand or 0)
            reserved = Decimal(reserved or 0)
            result[pid] = ProductListStats(
                qty_on_hand=on_hand,
                qty_committed=reserved,
                ordered_qty=Decimal(incoming or 0),
                shop_qty=Decimal(shop or 0),
                warehouse_qty=Decimal(wh or 0),
                qty_opened=result[pid].qty_opened,
                net_available=on_hand - result[pid].qty_opened - reserved,
                last_sale_date=result[pid].last_sale_date,
                last_sale_price=result[pid].last_sale_price,
                last_purchase_date=result[pid].last_purchase_date,
                last_purchase_price=result[pid].last_purchase_price,
            )

        si_open = (
            await self.session.execute(
                select(
                    SalesInvoiceLine.product_id,
                    func.coalesce(func.sum(SalesInvoiceLine.quantity), 0),
                )
                .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.sales_invoice_id)
                .where(
                    SalesInvoice.tenant_id == tenant_id,
                    SalesInvoice.deleted_at.is_(None),
                    SalesInvoice.status == InvoiceDocumentStatus.DRAFT.value,
                    SalesInvoiceLine.product_id.in_(ids),
                    SalesInvoiceLine.delivery_note_line_id.is_(None),
                )
                .group_by(SalesInvoiceLine.product_id)
            )
        ).all()
        dn_open = (
            await self.session.execute(
                select(
                    DeliveryNoteLine.product_id,
                    func.coalesce(func.sum(DeliveryNoteLine.quantity), 0),
                )
                .join(DeliveryNote, DeliveryNote.id == DeliveryNoteLine.delivery_note_id)
                .where(
                    DeliveryNote.tenant_id == tenant_id,
                    DeliveryNote.deleted_at.is_(None),
                    DeliveryNote.status == StockDocumentStatus.DRAFT.value,
                    DeliveryNoteLine.product_id.in_(ids),
                )
                .group_by(DeliveryNoteLine.product_id)
            )
        ).all()
        opened_by_product: dict[UUID, Decimal] = {pid: _ZERO for pid in ids}
        for pid, qty in si_open + dn_open:
            if pid is not None:
                opened_by_product[pid] = opened_by_product.get(pid, _ZERO) + Decimal(qty or 0)

        for pid in ids:
            stats = result[pid]
            opened = opened_by_product.get(pid, _ZERO)
            net = stats.qty_on_hand - opened - stats.qty_committed
            if net < 0:
                net = _ZERO
            result[pid] = ProductListStats(
                qty_on_hand=stats.qty_on_hand,
                qty_opened=opened,
                qty_committed=stats.qty_committed,
                net_available=net,
                shop_qty=stats.shop_qty,
                warehouse_qty=stats.warehouse_qty,
                ordered_qty=stats.ordered_qty,
                last_sale_date=stats.last_sale_date,
                last_sale_price=stats.last_sale_price,
                last_purchase_date=stats.last_purchase_date,
                last_purchase_price=stats.last_purchase_price,
            )

        last_sale = (
            await self.session.execute(
                select(
                    DeliveryNoteLine.product_id,
                    func.max(DeliveryNote.document_date),
                )
                .join(DeliveryNote, DeliveryNote.id == DeliveryNoteLine.delivery_note_id)
                .where(
                    DeliveryNote.tenant_id == tenant_id,
                    DeliveryNote.deleted_at.is_(None),
                    DeliveryNote.status == StockDocumentStatus.POSTED.value,
                    DeliveryNoteLine.product_id.in_(ids),
                )
                .group_by(DeliveryNoteLine.product_id)
            )
        ).all()
        sale_dates = {pid: dt for pid, dt in last_sale if pid is not None}

        for pid, sale_date in sale_dates.items():
            if sale_date is None:
                continue
            rate_row = await self.session.execute(
                select(DeliveryNoteLine.rate)
                .join(DeliveryNote, DeliveryNote.id == DeliveryNoteLine.delivery_note_id)
                .where(
                    DeliveryNote.tenant_id == tenant_id,
                    DeliveryNote.deleted_at.is_(None),
                    DeliveryNote.status == StockDocumentStatus.POSTED.value,
                    DeliveryNoteLine.product_id == pid,
                    DeliveryNote.document_date == sale_date,
                )
                .order_by(DeliveryNote.created_at.desc())
                .limit(1)
            )
            rate = rate_row.scalar_one_or_none()
            stats = result[pid]
            result[pid] = replace(
                stats,
                last_sale_date=sale_date,
                last_sale_price=Decimal(rate) if rate is not None else None,
            )

        last_pur = (
            await self.session.execute(
                select(
                    GoodsReceiptLine.product_id,
                    func.max(GoodsReceipt.document_date),
                )
                .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.goods_receipt_id)
                .where(
                    GoodsReceipt.tenant_id == tenant_id,
                    GoodsReceipt.deleted_at.is_(None),
                    GoodsReceipt.status == StockDocumentStatus.POSTED.value,
                    GoodsReceiptLine.product_id.in_(ids),
                )
                .group_by(GoodsReceiptLine.product_id)
            )
        ).all()
        for pid, pur_date in last_pur:
            if pid is None or pur_date is None:
                continue
            rate_row = await self.session.execute(
                select(GoodsReceiptLine.rate)
                .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.goods_receipt_id)
                .where(
                    GoodsReceipt.tenant_id == tenant_id,
                    GoodsReceipt.deleted_at.is_(None),
                    GoodsReceipt.status == StockDocumentStatus.POSTED.value,
                    GoodsReceiptLine.product_id == pid,
                    GoodsReceipt.document_date == pur_date,
                )
                .order_by(GoodsReceipt.created_at.desc())
                .limit(1)
            )
            rate = rate_row.scalar_one_or_none()
            stats = result[pid]
            result[pid] = replace(
                stats,
                last_purchase_date=pur_date,
                last_purchase_price=Decimal(rate) if rate is not None else None,
            )

        return result
