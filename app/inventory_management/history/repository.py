"""Posted delivery-note and goods-receipt history queries. Never a stored counter."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.common.schemas.pagination import PageParams
from app.core.enums import StockDocumentStatus
from app.crm.customers.models import Customer
from app.erp.sales_orders.models import SalesOrder
from app.inventory_management.delivery_notes.models import DeliveryNote, DeliveryNoteLine
from app.inventory_management.goods_receipts.models import GoodsReceipt, GoodsReceiptLine
from app.inventory_management.products.models import Product
from app.inventory_management.sales_returns.models import SalesReturn, SalesReturnLine
from app.inventory_management.stock.models import StockMovement
from app.inventory_management.stock.service import SOURCE_DELIVERY_NOTE

_ZERO = Decimal("0")


class HistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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

    async def product_customers(self, tenant_id: UUID, product_id: UUID) -> Sequence[Any]:
        net_qty = DeliveryNoteLine.quantity - self._posted_return_qty(tenant_id)
        statement = (
            select(
                Customer.id,
                Customer.name,
                func.sum(net_qty),
                func.count(func.distinct(DeliveryNote.id)),
                func.min(DeliveryNote.document_date),
                func.max(DeliveryNote.document_date),
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
            )
            .select_from(DeliveryNoteLine)
            .join(DeliveryNote, DeliveryNote.id == DeliveryNoteLine.delivery_note_id)
            .join(Customer, Customer.id == DeliveryNote.customer_id)
            .outerjoin(SalesOrder, SalesOrder.id == DeliveryNote.sales_order_id)
            .where(
                DeliveryNote.tenant_id == tenant_id,
                DeliveryNote.deleted_at.is_(None),
                DeliveryNote.status == StockDocumentStatus.POSTED.value,
                DeliveryNoteLine.tenant_id == tenant_id,
                DeliveryNoteLine.product_id == product_id,
            )
            .group_by(Customer.id, Customer.name)
            .having(func.sum(net_qty) > 0)
            .order_by(func.max(DeliveryNote.document_date).desc())
        )
        result = await self.session.execute(statement)
        return result.all()

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
    ) -> tuple[Sequence[Any], int]:
        return await self._sales_lines(
            tenant_id,
            page=page,
            product_id=product_id,
            party_id=party_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
        )

    async def customer_products(self, tenant_id: UUID, customer_id: UUID) -> Sequence[Any]:
        net_qty = DeliveryNoteLine.quantity - self._posted_return_qty(tenant_id)
        statement = (
            select(
                Product.id,
                Product.name,
                Product.sku,
                func.sum(net_qty),
                func.count(func.distinct(DeliveryNote.id)),
                func.min(DeliveryNote.document_date),
                func.max(DeliveryNote.document_date),
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
            )
            .select_from(DeliveryNoteLine)
            .join(DeliveryNote, DeliveryNote.id == DeliveryNoteLine.delivery_note_id)
            .join(Product, Product.id == DeliveryNoteLine.product_id)
            .outerjoin(SalesOrder, SalesOrder.id == DeliveryNote.sales_order_id)
            .where(
                DeliveryNote.tenant_id == tenant_id,
                DeliveryNote.deleted_at.is_(None),
                DeliveryNote.status == StockDocumentStatus.POSTED.value,
                DeliveryNote.customer_id == customer_id,
                DeliveryNoteLine.tenant_id == tenant_id,
                DeliveryNoteLine.product_id.is_not(None),
            )
            .group_by(Product.id, Product.name, Product.sku)
            .having(func.sum(net_qty) > 0)
            .order_by(func.max(DeliveryNote.document_date).desc())
        )
        result = await self.session.execute(statement)
        return result.all()

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
    ) -> tuple[Sequence[Any], int]:
        return await self._sales_lines(
            tenant_id,
            page=page,
            product_id=product_id,
            party_id=customer_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
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
    ) -> tuple[Sequence[Any], int]:
        net_qty = DeliveryNoteLine.quantity - self._posted_return_qty(tenant_id)
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
            )
            .select_from(DeliveryNoteLine)
            .join(DeliveryNote, DeliveryNote.id == DeliveryNoteLine.delivery_note_id)
            .join(Product, Product.id == DeliveryNoteLine.product_id)
            .join(Customer, Customer.id == DeliveryNote.customer_id)
            .outerjoin(SalesOrder, SalesOrder.id == DeliveryNote.sales_order_id)
            .where(*criteria)
        )
        count_statement = select(func.count()).select_from(base.subquery())
        statement = (
            base.order_by(DeliveryNote.document_date.desc(), DeliveryNote.created_at.desc())
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
    ) -> tuple[Sequence[Any], int]:
        return await self._purchase_lines(
            tenant_id,
            page=page,
            product_id=product_id,
            party_id=party_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
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
    ) -> tuple[Sequence[Any], int]:
        return await self._purchase_lines(
            tenant_id,
            page=page,
            product_id=product_id,
            party_id=supplier_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
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
    ) -> tuple[Sequence[Any], int]:
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
                GoodsReceiptLine.quantity,
                GoodsReceiptLine.rate,
                GoodsReceipt.posted_by,
            )
            .select_from(GoodsReceiptLine)
            .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.goods_receipt_id)
            .join(Product, Product.id == GoodsReceiptLine.product_id)
            .join(Customer, Customer.id == GoodsReceipt.supplier_id)
            .where(*criteria)
        )
        count_statement = select(func.count()).select_from(base.subquery())
        statement = (
            base.order_by(GoodsReceipt.document_date.desc(), GoodsReceipt.created_at.desc())
            .offset(page.offset)
            .limit(page.page_size)
        )
        rows = (await self.session.execute(statement)).all()
        total = await self.session.scalar(count_statement)
        return rows, int(total or 0)
