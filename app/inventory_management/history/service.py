"""Trading history service. Cost and margin gated behind inventory.cost.read."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import COST_READ
from app.common.schemas.pagination import PageParams
from app.common.utils.currency import quantize_money
from app.core.permissions import has_permission
from app.crm.customers.service import CustomerService
from app.erp.suppliers.service import SupplierService
from app.inventory_management.history.repository import HistoryRepository
from app.inventory_management.history.schemas import (
    TradingHistoryLine,
    TradingPartyAggregate,
    TradingProductAggregate,
)
from app.inventory_management.products.service import ProductService

_ZERO = Decimal("0")


class HistoryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = HistoryRepository(session)
        self.products = ProductService(session)
        self.customers = CustomerService(session)
        self.suppliers = SupplierService(session)
        self._can_read_cost = has_permission(actor_permissions, COST_READ)

    async def product_customers(
        self, tenant_id: UUID, product_id: UUID
    ) -> list[TradingPartyAggregate]:
        await self.products.get(tenant_id, product_id)
        rows = await self.repo.product_customers(tenant_id, product_id)
        return [
            TradingPartyAggregate(
                party_id=row[0],
                party_name=row[1],
                total_quantity=row[2] or _ZERO,
                dispatch_count=int(row[3] or 0),
                first_date=row[4],
                last_date=row[5],
                last_rate=row[6] or _ZERO,
                last_posted_by=row[7],
                salesperson_id=row[8],
            )
            for row in rows
            if row[4] is not None
        ]

    async def product_sales_history(
        self,
        tenant_id: UUID,
        product_id: UUID,
        *,
        page: PageParams,
        party_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[list[TradingHistoryLine], int]:
        await self.products.get(tenant_id, product_id)
        rows, total = await self.repo.product_sales_lines(
            tenant_id,
            product_id,
            page=page,
            party_id=party_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
        )
        return [self._sales_line(row) for row in rows], total

    async def product_purchase_history(
        self,
        tenant_id: UUID,
        product_id: UUID,
        *,
        page: PageParams,
        party_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[list[TradingHistoryLine], int]:
        await self.products.get(tenant_id, product_id)
        rows, total = await self.repo.product_purchase_lines(
            tenant_id,
            product_id,
            page=page,
            party_id=party_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
        )
        return [self._purchase_line(row) for row in rows], total

    async def customer_products(
        self, tenant_id: UUID, customer_id: UUID
    ) -> list[TradingProductAggregate]:
        await self.customers.get(tenant_id, customer_id)
        rows = await self.repo.customer_products(tenant_id, customer_id)
        return [
            TradingProductAggregate(
                product_id=row[0],
                product_name=row[1],
                sku=row[2],
                total_quantity=row[3] or _ZERO,
                dispatch_count=int(row[4] or 0),
                first_date=row[5],
                last_date=row[6],
                last_rate=row[7] or _ZERO,
                last_posted_by=row[8],
                salesperson_id=row[9],
            )
            for row in rows
            if row[5] is not None
        ]

    async def customer_sales_history(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        *,
        page: PageParams,
        product_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[list[TradingHistoryLine], int]:
        await self.customers.get(tenant_id, customer_id)
        rows, total = await self.repo.customer_sales_lines(
            tenant_id,
            customer_id,
            page=page,
            product_id=product_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
        )
        return [self._sales_line(row) for row in rows], total

    async def supplier_purchase_history(
        self,
        tenant_id: UUID,
        supplier_id: UUID,
        *,
        page: PageParams,
        product_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[list[TradingHistoryLine], int]:
        await self.suppliers.get(tenant_id, supplier_id)
        rows, total = await self.repo.supplier_purchase_lines(
            tenant_id,
            supplier_id,
            page=page,
            product_id=product_id,
            warehouse_id=warehouse_id,
            document_date_from=document_date_from,
            document_date_to=document_date_to,
        )
        return [self._purchase_line(row) for row in rows], total

    def _as_decimal(self, value: object) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value or 0))

    def _sales_line(self, row: Any) -> TradingHistoryLine:
        quantity = self._as_decimal(row[9])
        rate = self._as_decimal(row[10])
        raw_cost = row[11]
        unit_cost = None
        margin = None
        if self._can_read_cost and raw_cost is not None:
            unit_cost = self._as_decimal(raw_cost)
            margin = quantize_money((rate - unit_cost) * quantity)
        return TradingHistoryLine(
            document_id=row[0],
            document_number=str(row[1]),
            document_date=row[2],
            product_id=row[3],
            product_name=str(row[4]),
            sku=str(row[5]),
            party_id=row[6],
            party_name=str(row[7]),
            warehouse_id=row[8],
            quantity=quantity,
            rate=rate,
            unit_cost=unit_cost,
            margin=margin,
            posted_by=row[12],
            salesperson_id=row[13],
        )

    def _purchase_line(self, row: Any) -> TradingHistoryLine:
        quantity = self._as_decimal(row[9])
        rate = self._as_decimal(row[10])
        unit_cost = rate if self._can_read_cost else None
        return TradingHistoryLine(
            document_id=row[0],
            document_number=str(row[1]),
            document_date=row[2],
            product_id=row[3],
            product_name=str(row[4]),
            sku=str(row[5]),
            party_id=row[6],
            party_name=str(row[7]),
            warehouse_id=row[8],
            quantity=quantity,
            rate=rate,
            unit_cost=unit_cost,
            margin=None,
            posted_by=row[11],
            salesperson_id=None,
        )
