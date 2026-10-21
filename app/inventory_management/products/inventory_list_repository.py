"""Aggregate inventory list queries for Winsoft-style grids."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.search import (
    PRODUCT_INVENTORY_SEARCH_FIELDS,
    column_ilike,
    ilike_pattern,
)
from app.common.schemas.pagination import PageParams
from app.core.enums import InvoiceDocumentStatus, StockDocumentStatus, WarehouseLocationType
from app.erp.sales_invoices.models import SalesInvoice, SalesInvoiceLine
from app.inventory_management.delivery_notes.models import DeliveryNote, DeliveryNoteLine
from app.inventory_management.products.models import Product
from app.inventory_management.stock.models import StockBalance
from app.inventory_management.warehouses.models import Warehouse

_ZERO = Decimal("0")


class ProductInventoryListRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _draft_opened_subquery(self, tenant_id: UUID):
        si_qty = (
            select(
                SalesInvoiceLine.product_id.label("product_id"),
                func.coalesce(func.sum(SalesInvoiceLine.quantity), 0).label("qty"),
            )
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.sales_invoice_id)
            .where(
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.DRAFT.value,
                SalesInvoiceLine.product_id.is_not(None),
                SalesInvoiceLine.delivery_note_line_id.is_(None),
            )
            .group_by(SalesInvoiceLine.product_id)
        ).subquery()
        dn_qty = (
            select(
                DeliveryNoteLine.product_id.label("product_id"),
                func.coalesce(func.sum(DeliveryNoteLine.quantity), 0).label("qty"),
            )
            .join(DeliveryNote, DeliveryNote.id == DeliveryNoteLine.delivery_note_id)
            .where(
                DeliveryNote.tenant_id == tenant_id,
                DeliveryNote.deleted_at.is_(None),
                DeliveryNote.status == StockDocumentStatus.DRAFT.value,
                DeliveryNoteLine.product_id.is_not(None),
            )
            .group_by(DeliveryNoteLine.product_id)
        ).subquery()
        return si_qty, dn_qty

    async def list_rows(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        search: str | None,
        search_type: str,
        category_id: UUID | None,
        brand: str | None,
        engine: str | None,
        tracked_only: bool,
        sort_by: str,
        sort_order: str,
    ) -> tuple[Sequence[Any], int]:
        si_open, dn_open = self._draft_opened_subquery(tenant_id)
        opened_expr = func.coalesce(si_open.c.qty, 0) + func.coalesce(dn_open.c.qty, 0)
        on_hand_expr = func.coalesce(func.sum(StockBalance.qty_on_hand), 0)
        reserved_expr = func.coalesce(func.sum(StockBalance.qty_reserved), 0)
        incoming_expr = func.coalesce(func.sum(StockBalance.qty_incoming), 0)
        shop_expr = func.coalesce(
            func.sum(
                case(
                    (Warehouse.location_type == WarehouseLocationType.SHOP.value, StockBalance.qty_on_hand),
                    else_=_ZERO,
                )
            ),
            0,
        )
        wh_expr = func.coalesce(
            func.sum(
                case(
                    (
                        Warehouse.location_type == WarehouseLocationType.WAREHOUSE.value,
                        StockBalance.qty_on_hand,
                    ),
                    else_=_ZERO,
                )
            ),
            0,
        )
        net_avail_expr = on_hand_expr - opened_expr - reserved_expr

        criteria: list[ColumnElement[bool]] = [
            Product.tenant_id == tenant_id,
            Product.deleted_at.is_(None),
        ]
        if tracked_only:
            criteria.append(Product.track_inventory.is_(True))
        if category_id is not None:
            criteria.append(Product.category_id == category_id)
        if brand is not None and brand.strip():
            criteria.append(column_ilike(Product.brand, ilike_pattern(brand.strip())))
        if engine is not None and engine.strip():
            criteria.append(column_ilike(Product.engine, ilike_pattern(engine.strip())))
        if search and search.strip():
            pattern = ilike_pattern(search.strip(), prefix_only=search_type == "starts_with")
            criteria.append(
                or_(
                    *[
                        column_ilike(getattr(Product, field), pattern)
                        for field in PRODUCT_INVENTORY_SEARCH_FIELDS
                        if hasattr(Product, field)
                    ]
                )
            )

        base: Select[tuple[object, ...]] = (
            select(
                Product.id,
                Product.sku,
                Product.name,
                Product.volume,
                Product.alias_2,
                Product.alias_3,
                Product.alias_4,
                Product.brand,
                Product.engine,
                Product.selling_rate,
                Product.price_1,
                Product.price_2,
                Product.purchase_rate,
                Product.secondary_unit_id,
                Product.secondary_unit_factor,
                Product.unit_id,
                on_hand_expr.label("qty_on_hand"),
                reserved_expr.label("qty_committed"),
                incoming_expr.label("ordered_qty"),
                opened_expr.label("qty_opened"),
                net_avail_expr.label("net_available"),
                shop_expr.label("shop_qty"),
                wh_expr.label("warehouse_qty"),
            )
            .select_from(Product)
            .outerjoin(si_open, si_open.c.product_id == Product.id)
            .outerjoin(dn_open, dn_open.c.product_id == Product.id)
            .outerjoin(StockBalance, StockBalance.product_id == Product.id)
            .outerjoin(
                Warehouse,
                (Warehouse.id == StockBalance.warehouse_id) & (Warehouse.tenant_id == tenant_id),
            )
            .where(*criteria)
            .group_by(
                Product.id,
                si_open.c.qty,
                dn_open.c.qty,
            )
        )
        count_statement = select(func.count()).select_from(base.subquery())
        sort_map = {
            "sku": Product.sku,
            "name": Product.name,
            "volume": Product.volume,
            "created_at": Product.created_at,
            "net_available": net_avail_expr,
        }
        order_col = sort_map.get(sort_by, Product.sku)
        order_fn = order_col.desc() if sort_order == "desc" else order_col.asc()
        statement = base.order_by(order_fn).offset(page.offset).limit(page.page_size)
        rows = (await self.session.execute(statement)).all()
        total = await self.session.scalar(count_statement)
        return rows, int(total or 0)

    async def draft_opened_for_product(self, tenant_id: UUID, product_id: UUID) -> Decimal:
        si_stmt = (
            select(func.coalesce(func.sum(SalesInvoiceLine.quantity), 0))
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.sales_invoice_id)
            .where(
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.DRAFT.value,
                SalesInvoiceLine.product_id == product_id,
                SalesInvoiceLine.delivery_note_line_id.is_(None),
            )
        )
        dn_stmt = (
            select(func.coalesce(func.sum(DeliveryNoteLine.quantity), 0))
            .join(DeliveryNote, DeliveryNote.id == DeliveryNoteLine.delivery_note_id)
            .where(
                DeliveryNote.tenant_id == tenant_id,
                DeliveryNote.deleted_at.is_(None),
                DeliveryNote.status == StockDocumentStatus.DRAFT.value,
                DeliveryNoteLine.product_id == product_id,
            )
        )
        si_qty = await self.session.scalar(si_stmt)
        dn_qty = await self.session.scalar(dn_stmt)
        return Decimal(si_qty or 0) + Decimal(dn_qty or 0)
