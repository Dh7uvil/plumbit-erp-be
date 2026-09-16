"""Posted delivery-note and goods-receipt history queries. Never a stored counter."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, asc, desc, func, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.search import column_ilike, ilike_pattern
from app.common.schemas.pagination import PageParams
from app.core.enums import InvoiceDocumentStatus, StockDocumentStatus
from app.crm.customers.models import Customer
from app.erp.purchase_invoices.models import PurchaseInvoice, PurchaseInvoiceLine
from app.erp.sales_invoices.models import SalesInvoice, SalesInvoiceLine
from app.erp.sales_orders.models import SalesOrder
from app.inventory_management.delivery_notes.models import DeliveryNote, DeliveryNoteLine
from app.inventory_management.goods_receipts.models import GoodsReceipt, GoodsReceiptLine
from app.inventory_management.products.models import Product
from app.inventory_management.purchase_returns.models import PurchaseReturn, PurchaseReturnLine
from app.inventory_management.sales_returns.models import SalesReturn, SalesReturnLine
from app.inventory_management.stock.models import StockMovement
from app.inventory_management.stock.service import SOURCE_DELIVERY_NOTE

_ZERO = Decimal("0")


def _ordered(expr: ColumnElement[Any], sort_order: str):
    return desc(expr) if sort_order == "desc" else asc(expr)


class HistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _search_pattern(search: str | None) -> str | None:
        if not search:
            return None
        return ilike_pattern(search)

    def _posted_return_qty(self, tenant_id: UUID) -> ColumnElement[Decimal]:
        return func.coalesce(
            select(func.coalesce(func.sum(SalesReturnLine.quantity), _ZERO))
            .join(SalesReturn, SalesReturn.id == SalesReturnLine.sales_return_id)
            .where(
                SalesReturnLine.delivery_note_line_id == DeliveryNoteLine.id,
                SalesReturn.tenant_id == tenant_id,
                SalesReturn.deleted_at.is_(None),
                SalesReturn.status == StockDocumentStatus.POSTED.value,
            )
            .correlate(DeliveryNoteLine)
            .scalar_subquery(),
            _ZERO,
        )

    def _posted_purchase_return_qty(self, tenant_id: UUID) -> ColumnElement[Decimal]:
        return func.coalesce(
            select(func.coalesce(func.sum(PurchaseReturnLine.quantity), _ZERO))
            .join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnLine.purchase_return_id)
            .where(
                PurchaseReturnLine.goods_receipt_line_id == GoodsReceiptLine.id,
                PurchaseReturn.tenant_id == tenant_id,
                PurchaseReturn.deleted_at.is_(None),
                PurchaseReturn.status == StockDocumentStatus.POSTED.value,
            )
            .correlate(GoodsReceiptLine)
            .scalar_subquery(),
            _ZERO,
        )

    def _outbound_unit_cost(self, tenant_id: UUID) -> ColumnElement[Decimal | None]:
        return (
            select(StockMovement.unit_cost)
            .where(
                StockMovement.tenant_id == tenant_id,
                StockMovement.source_type == SOURCE_DELIVERY_NOTE,
                StockMovement.source_id == DeliveryNote.id,
                StockMovement.source_line_id == DeliveryNoteLine.id,
                StockMovement.qty < 0,
            )
            .order_by(StockMovement.occurred_at.desc())
            .limit(1)
            .correlate(DeliveryNote, DeliveryNoteLine)
            .scalar_subquery()
        )

    def _posted_invoice_qty_for_dn_line(self, tenant_id: UUID) -> ColumnElement[Decimal]:
        return func.coalesce(
            select(func.coalesce(func.sum(SalesInvoiceLine.quantity), _ZERO))
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.sales_invoice_id)
            .where(
                SalesInvoiceLine.delivery_note_line_id == DeliveryNoteLine.id,
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                SalesInvoiceLine.tenant_id == tenant_id,
            )
            .correlate(DeliveryNoteLine)
            .scalar_subquery(),
            _ZERO,
        )

    def _posted_invoice_amount_for_dn_line(self, tenant_id: UUID) -> ColumnElement[Decimal]:
        return func.coalesce(
            select(func.coalesce(func.sum(SalesInvoiceLine.amount), _ZERO))
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.sales_invoice_id)
            .where(
                SalesInvoiceLine.delivery_note_line_id == DeliveryNoteLine.id,
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                SalesInvoiceLine.tenant_id == tenant_id,
            )
            .correlate(DeliveryNoteLine)
            .scalar_subquery(),
            _ZERO,
        )

    def _posted_bill_amount_for_grn_line(self, tenant_id: UUID) -> ColumnElement[Decimal]:
        return func.coalesce(
            select(func.coalesce(func.sum(PurchaseInvoiceLine.amount), _ZERO))
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
            .where(
                PurchaseInvoiceLine.goods_receipt_line_id == GoodsReceiptLine.id,
                PurchaseInvoice.tenant_id == tenant_id,
                PurchaseInvoice.deleted_at.is_(None),
                PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
                PurchaseInvoiceLine.tenant_id == tenant_id,
            )
            .correlate(GoodsReceiptLine)
            .scalar_subquery(),
            _ZERO,
        )

    def _invoice_stats_by_customer(self, tenant_id: UUID, product_id: UUID):
        return (
            select(
                SalesInvoice.customer_id.label("customer_id"),
                func.coalesce(func.sum(SalesInvoiceLine.quantity), _ZERO).label(
                    "invoiced_quantity"
                ),
                func.coalesce(func.sum(SalesInvoiceLine.amount), _ZERO).label("revenue"),
            )
            .select_from(SalesInvoiceLine)
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.sales_invoice_id)
            .where(
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                SalesInvoiceLine.tenant_id == tenant_id,
                SalesInvoiceLine.product_id == product_id,
            )
            .group_by(SalesInvoice.customer_id)
            .subquery()
        )

    def _invoice_stats_by_product(self, tenant_id: UUID, customer_id: UUID):
        return (
            select(
                SalesInvoiceLine.product_id.label("product_id"),
                func.coalesce(func.sum(SalesInvoiceLine.quantity), _ZERO).label(
                    "invoiced_quantity"
                ),
                func.coalesce(func.sum(SalesInvoiceLine.amount), _ZERO).label("revenue"),
            )
            .select_from(SalesInvoiceLine)
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.sales_invoice_id)
            .where(
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                SalesInvoice.customer_id == customer_id,
                SalesInvoiceLine.tenant_id == tenant_id,
                SalesInvoiceLine.product_id.is_not(None),
            )
            .group_by(SalesInvoiceLine.product_id)
            .subquery()
        )

    async def product_customers(
        self,
        tenant_id: UUID,
        product_id: UUID,
        *,
        page: PageParams,
        search: str | None = None,
        sort_by: str = "last_date",
        sort_order: str = "desc",
    ) -> tuple[Sequence[Any], int]:
        net_qty = DeliveryNoteLine.quantity - self._posted_return_qty(tenant_id)
        invoice_stats = self._invoice_stats_by_customer(tenant_id, product_id)
        last_date = func.max(DeliveryNote.document_date)
        total_quantity = func.sum(net_qty)
        dispatch_count = func.count(func.distinct(DeliveryNote.id))
        statement = (
            select(
                Customer.id,
                Customer.name,
                total_quantity,
                dispatch_count,
                func.min(DeliveryNote.document_date),
                last_date,
                func.array_agg(
                    aggregate_order_by(
                        DeliveryNoteLine.rate,
                        DeliveryNote.document_date.desc(),
                        DeliveryNote.created_at.desc(),
                    )
                )[1],
                func.array_agg(
                    aggregate_order_by(
                        DeliveryNote.posted_by,
                        DeliveryNote.document_date.desc(),
                        DeliveryNote.created_at.desc(),
                    )
                )[1],
                func.array_agg(
                    aggregate_order_by(
                        SalesOrder.salesperson_id,
                        DeliveryNote.document_date.desc(),
                        DeliveryNote.created_at.desc(),
                    )
                )[1],
                func.coalesce(invoice_stats.c.invoiced_quantity, _ZERO),
                func.coalesce(invoice_stats.c.revenue, _ZERO),
            )
            .select_from(DeliveryNoteLine)
            .join(DeliveryNote, DeliveryNote.id == DeliveryNoteLine.delivery_note_id)
            .join(Customer, Customer.id == DeliveryNote.customer_id)
            .outerjoin(SalesOrder, SalesOrder.id == DeliveryNote.sales_order_id)
            .outerjoin(invoice_stats, invoice_stats.c.customer_id == Customer.id)
            .where(
                DeliveryNote.tenant_id == tenant_id,
                DeliveryNote.deleted_at.is_(None),
                DeliveryNote.status == StockDocumentStatus.POSTED.value,
                DeliveryNoteLine.tenant_id == tenant_id,
                DeliveryNoteLine.product_id == product_id,
            )
            .group_by(
                Customer.id,
                Customer.name,
                invoice_stats.c.invoiced_quantity,
                invoice_stats.c.revenue,
            )
            .having(func.sum(net_qty) > 0)
        )
        pattern = self._search_pattern(search)
        if pattern is not None:
            statement = statement.where(column_ilike(Customer.name, pattern))
        count_statement = select(func.count()).select_from(statement.subquery())
        sort_map = {
            "party_name": Customer.name,
            "total_quantity": total_quantity,
            "revenue": func.coalesce(invoice_stats.c.revenue, _ZERO),
            "last_date": last_date,
            "dispatch_count": dispatch_count,
        }
        order_expr = sort_map.get(sort_by, last_date)
        statement = (
            statement.order_by(_ordered(order_expr, sort_order), Customer.name.asc())
            .offset(page.offset)
            .limit(page.page_size)
        )
        rows = (await self.session.execute(statement)).all()
        total = await self.session.scalar(count_statement)
        return rows, int(total or 0)

    async def product_sales_lines(
        self,
        tenant_id: UUID,
        product_id: UUID,
        *,
        page: PageParams,
        party_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
        search: str | None = None,
        sort_by: str = "document_date",
        sort_order: str = "desc",
    ) -> tuple[Sequence[Any], int]:
        return await self._sales_lines(
            tenant_id,
            page=page,
            product_id=product_id,
            party_id=party_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def customer_products(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        *,
        page: PageParams,
        search: str | None = None,
        sort_by: str = "last_date",
        sort_order: str = "desc",
    ) -> tuple[Sequence[Any], int]:
        net_qty = DeliveryNoteLine.quantity - self._posted_return_qty(tenant_id)
        invoice_stats = self._invoice_stats_by_product(tenant_id, customer_id)
        last_date = func.max(DeliveryNote.document_date)
        total_quantity = func.sum(net_qty)
        dispatch_count = func.count(func.distinct(DeliveryNote.id))
        statement = (
            select(
                Product.id,
                Product.name,
                Product.sku,
                total_quantity,
                dispatch_count,
                func.min(DeliveryNote.document_date),
                last_date,
                func.array_agg(
                    aggregate_order_by(
                        DeliveryNoteLine.rate,
                        DeliveryNote.document_date.desc(),
                        DeliveryNote.created_at.desc(),
                    )
                )[1],
                func.array_agg(
                    aggregate_order_by(
                        DeliveryNote.posted_by,
                        DeliveryNote.document_date.desc(),
                        DeliveryNote.created_at.desc(),
                    )
                )[1],
                func.array_agg(
                    aggregate_order_by(
                        SalesOrder.salesperson_id,
                        DeliveryNote.document_date.desc(),
                        DeliveryNote.created_at.desc(),
                    )
                )[1],
                func.coalesce(invoice_stats.c.invoiced_quantity, _ZERO),
                func.coalesce(invoice_stats.c.revenue, _ZERO),
            )
            .select_from(DeliveryNoteLine)
            .join(DeliveryNote, DeliveryNote.id == DeliveryNoteLine.delivery_note_id)
            .join(Product, Product.id == DeliveryNoteLine.product_id)
            .outerjoin(SalesOrder, SalesOrder.id == DeliveryNote.sales_order_id)
            .outerjoin(invoice_stats, invoice_stats.c.product_id == Product.id)
            .where(
                DeliveryNote.tenant_id == tenant_id,
                DeliveryNote.deleted_at.is_(None),
                DeliveryNote.status == StockDocumentStatus.POSTED.value,
                DeliveryNote.customer_id == customer_id,
                DeliveryNoteLine.tenant_id == tenant_id,
                DeliveryNoteLine.product_id.is_not(None),
            )
            .group_by(
                Product.id,
                Product.name,
                Product.sku,
                invoice_stats.c.invoiced_quantity,
                invoice_stats.c.revenue,
            )
            .having(func.sum(net_qty) > 0)
        )
        pattern = self._search_pattern(search)
        if pattern is not None:
            statement = statement.where(
                or_(column_ilike(Product.sku, pattern), column_ilike(Product.name, pattern))
            )
        count_statement = select(func.count()).select_from(statement.subquery())
        sort_map = {
            "sku": Product.sku,
            "product_name": Product.name,
            "total_quantity": total_quantity,
            "revenue": func.coalesce(invoice_stats.c.revenue, _ZERO),
            "last_date": last_date,
            "dispatch_count": dispatch_count,
        }
        order_expr = sort_map.get(sort_by, last_date)
        statement = (
            statement.order_by(_ordered(order_expr, sort_order), Product.sku.asc())
            .offset(page.offset)
            .limit(page.page_size)
        )
        rows = (await self.session.execute(statement)).all()
        total = await self.session.scalar(count_statement)
        return rows, int(total or 0)

    async def customer_sales_lines(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        *,
        page: PageParams,
        product_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
        search: str | None = None,
        sort_by: str = "document_date",
        sort_order: str = "desc",
    ) -> tuple[Sequence[Any], int]:
        return await self._sales_lines(
            tenant_id,
            page=page,
            product_id=product_id,
            party_id=customer_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def _sales_lines(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        product_id: UUID | None,
        party_id: UUID | None,
        warehouse_id: UUID | None,
        document_date_from: date | None,
        document_date_to: date | None,
        search: str | None = None,
        sort_by: str = "document_date",
        sort_order: str = "desc",
    ) -> tuple[Sequence[Any], int]:
        net_qty = DeliveryNoteLine.quantity - self._posted_return_qty(tenant_id)
        invoiced_amount = self._posted_invoice_amount_for_dn_line(tenant_id)
        criteria: list[ColumnElement[bool]] = [
            DeliveryNote.tenant_id == tenant_id,
            DeliveryNote.deleted_at.is_(None),
            DeliveryNote.status == StockDocumentStatus.POSTED.value,
            DeliveryNoteLine.tenant_id == tenant_id,
            DeliveryNoteLine.product_id.is_not(None),
            net_qty > 0,
        ]
        if product_id is not None:
            criteria.append(DeliveryNoteLine.product_id == product_id)
        if party_id is not None:
            criteria.append(DeliveryNote.customer_id == party_id)
        if warehouse_id is not None:
            criteria.append(DeliveryNote.warehouse_id == warehouse_id)
        if document_date_from is not None:
            criteria.append(DeliveryNote.document_date >= document_date_from)
        if document_date_to is not None:
            criteria.append(DeliveryNote.document_date <= document_date_to)
        pattern = self._search_pattern(search)
        if pattern is not None:
            criteria.append(
                or_(
                    column_ilike(DeliveryNote.document_number, pattern),
                    column_ilike(Customer.name, pattern),
                    column_ilike(Product.name, pattern),
                    column_ilike(Product.sku, pattern),
                )
            )
        base: Select[tuple[object, ...]] = (
            select(
                DeliveryNote.id,
                DeliveryNote.document_number,
                DeliveryNote.document_date,
                Product.id,
                Product.name,
                Product.sku,
                Customer.id,
                Customer.name,
                DeliveryNote.warehouse_id,
                net_qty,
                DeliveryNoteLine.rate,
                self._outbound_unit_cost(tenant_id),
                DeliveryNote.posted_by,
                SalesOrder.salesperson_id,
                self._posted_invoice_qty_for_dn_line(tenant_id),
                invoiced_amount,
            )
            .select_from(DeliveryNoteLine)
            .join(DeliveryNote, DeliveryNote.id == DeliveryNoteLine.delivery_note_id)
            .join(Product, Product.id == DeliveryNoteLine.product_id)
            .join(Customer, Customer.id == DeliveryNote.customer_id)
            .outerjoin(SalesOrder, SalesOrder.id == DeliveryNote.sales_order_id)
            .where(*criteria)
        )
        count_statement = select(func.count()).select_from(base.subquery())
        sort_map = {
            "document_date": DeliveryNote.document_date,
            "document_number": DeliveryNote.document_number,
            "quantity": net_qty,
            "rate": DeliveryNoteLine.rate,
            "revenue": invoiced_amount,
            "party_name": Customer.name,
            "product_name": Product.name,
            "sku": Product.sku,
        }
        order_expr = sort_map.get(sort_by, DeliveryNote.document_date)
        statement = (
            base.order_by(_ordered(order_expr, sort_order), DeliveryNote.created_at.desc())
            .offset(page.offset)
            .limit(page.page_size)
        )
        rows = (await self.session.execute(statement)).all()
        total = await self.session.scalar(count_statement)
        return rows, int(total or 0)

    async def product_purchase_lines(
        self,
        tenant_id: UUID,
        product_id: UUID,
        *,
        page: PageParams,
        party_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
        search: str | None = None,
        sort_by: str = "document_date",
        sort_order: str = "desc",
    ) -> tuple[Sequence[Any], int]:
        return await self._purchase_lines(
            tenant_id,
            page=page,
            product_id=product_id,
            party_id=party_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def supplier_purchase_lines(
        self,
        tenant_id: UUID,
        supplier_id: UUID,
        *,
        page: PageParams,
        product_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
        search: str | None = None,
        sort_by: str = "document_date",
        sort_order: str = "desc",
    ) -> tuple[Sequence[Any], int]:
        return await self._purchase_lines(
            tenant_id,
            page=page,
            product_id=product_id,
            party_id=supplier_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def _purchase_lines(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        product_id: UUID | None,
        party_id: UUID | None,
        warehouse_id: UUID | None,
        document_date_from: date | None,
        document_date_to: date | None,
        search: str | None = None,
        sort_by: str = "document_date",
        sort_order: str = "desc",
    ) -> tuple[Sequence[Any], int]:
        quantity = GoodsReceiptLine.quantity - self._posted_purchase_return_qty(tenant_id)
        billed_amount = self._posted_bill_amount_for_grn_line(tenant_id)
        criteria: list[ColumnElement[bool]] = [
            GoodsReceipt.tenant_id == tenant_id,
            GoodsReceipt.deleted_at.is_(None),
            GoodsReceipt.status == StockDocumentStatus.POSTED.value,
            GoodsReceiptLine.tenant_id == tenant_id,
            GoodsReceiptLine.product_id.is_not(None),
        ]
        if product_id is not None:
            criteria.append(GoodsReceiptLine.product_id == product_id)
        if party_id is not None:
            criteria.append(GoodsReceipt.supplier_id == party_id)
        if warehouse_id is not None:
            criteria.append(GoodsReceipt.warehouse_id == warehouse_id)
        if document_date_from is not None:
            criteria.append(GoodsReceipt.document_date >= document_date_from)
        if document_date_to is not None:
            criteria.append(GoodsReceipt.document_date <= document_date_to)
        pattern = self._search_pattern(search)
        if pattern is not None:
            criteria.append(
                or_(
                    column_ilike(GoodsReceipt.document_number, pattern),
                    column_ilike(Customer.name, pattern),
                    column_ilike(Product.name, pattern),
                    column_ilike(Product.sku, pattern),
                )
            )
        base: Select[tuple[object, ...]] = (
            select(
                GoodsReceipt.id,
                GoodsReceipt.document_number,
                GoodsReceipt.document_date,
                Product.id,
                Product.name,
                Product.sku,
                Customer.id,
                Customer.name,
                GoodsReceipt.warehouse_id,
                quantity,
                GoodsReceiptLine.rate,
                GoodsReceipt.posted_by,
                billed_amount,
            )
            .select_from(GoodsReceiptLine)
            .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.goods_receipt_id)
            .join(Product, Product.id == GoodsReceiptLine.product_id)
            .join(Customer, Customer.id == GoodsReceipt.supplier_id)
            .where(*criteria)
        )
        count_statement = select(func.count()).select_from(base.subquery())
        sort_map = {
            "document_date": GoodsReceipt.document_date,
            "document_number": GoodsReceipt.document_number,
            "quantity": quantity,
            "rate": GoodsReceiptLine.rate,
            "revenue": billed_amount,
            "party_name": Customer.name,
            "product_name": Product.name,
            "sku": Product.sku,
        }
        order_expr = sort_map.get(sort_by, GoodsReceipt.document_date)
        statement = (
            base.order_by(_ordered(order_expr, sort_order), GoodsReceipt.created_at.desc())
            .offset(page.offset)
            .limit(page.page_size)
        )
        rows = (await self.session.execute(statement)).all()
        total = await self.session.scalar(count_statement)
        return rows, int(total or 0)
