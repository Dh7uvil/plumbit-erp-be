"""Inventory as-of and ranged reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.common.utils.currency import quantize_money, quantize_quantity
from app.common.utils.datetime import utcnow
from app.core.enums import AccountSystemRole, StockMovementType
from app.core.exceptions import ValidationError
from app.crm.customers.models import Customer
from app.erp.accounting.reports.schemas import (
    PurchaseSuggestionLine,
    PurchaseSuggestionResponse,
    StockAgingBucketTotals,
    StockAgingLine,
    StockAgingResponse,
    StockMovementReportLine,
    StockMovementReportResponse,
    StockValuationGlResponse,
    StockValuationLine,
    StockValuationResponse,
)
from app.erp.supplier_products.models import SupplierProduct
from app.inventory_management.costing.models import StockCostLayer
from app.inventory_management.products.models import Product
from app.inventory_management.stock.availability import available_qty
from app.inventory_management.stock.models import StockBalance, StockMovement
from app.inventory_management.warehouses.models import Warehouse

_ZERO = Decimal("0")
_HOLD_TYPES = frozenset({StockMovementType.QC_HOLD.value, StockMovementType.QC_RELEASE.value})


class InventoryReports:
    async def stock_valuation(
        self,
        tenant_id: UUID,
        *,
        as_of: date | None = None,
        warehouse_id: UUID | None = None,
        product_id: UUID | None = None,
        category_id: UUID | None = None,
    ) -> StockValuationResponse:
        as_of_date = as_of or utcnow().date()
        layers, products, warehouses = await self._valuation_layers(
            tenant_id,
            as_of=as_of_date,
            warehouse_id=warehouse_id,
            product_id=product_id,
            category_id=category_id,
        )
        lines: list[StockValuationLine] = []
        total_qty = _ZERO
        total_value = _ZERO
        for layer in layers:
            if layer.qty_remaining == _ZERO:
                continue
            product = products.get(layer.product_id)
            warehouse = warehouses.get(layer.warehouse_id)
            value = quantize_money(layer.qty_remaining * layer.landed_unit_cost)
            qty = quantize_quantity(layer.qty_remaining)
            total_qty += qty
            total_value += value
            lines.append(
                StockValuationLine(
                    warehouse_id=layer.warehouse_id,
                    warehouse_code=warehouse.code if warehouse else "",
                    warehouse_name=warehouse.name if warehouse else "",
                    product_id=layer.product_id,
                    sku=product.sku if product else "",
                    product_name=product.name if product else "",
                    category_id=product.category_id if product else None,
                    qty_remaining=qty,
                    landed_unit_cost=layer.landed_unit_cost,
                    stock_value=value,
                    document_date=layer.document_date,
                    layer_id=layer.id,
                )
            )
        return StockValuationResponse(
            as_of=as_of_date,
            total_qty=quantize_quantity(total_qty),
            total_value=quantize_money(total_value),
            lines=lines,
        )

    async def stock_valuation_gl(
        self,
        tenant_id: UUID,
        *,
        as_of: date | None = None,
        warehouse_id: UUID | None = None,
        product_id: UUID | None = None,
        category_id: UUID | None = None,
    ) -> StockValuationGlResponse:
        valuation = await self.stock_valuation(
            tenant_id,
            as_of=as_of,
            warehouse_id=warehouse_id,
            product_id=product_id,
            category_id=category_id,
        )
        inventory = await self.accounts.repo.get_by_system_role(
            tenant_id, AccountSystemRole.INVENTORY.value
        )
        gl_balance = _ZERO
        account_id = None
        if inventory is not None:
            account_id = inventory.id
            closing = await self._sum_by_account(
                tenant_id, end=valuation.as_of, account_id=inventory.id
            )
            debit, credit = closing.get(inventory.id, (_ZERO, _ZERO))
            gl_balance = self._signed(inventory.account_type, debit, credit)
        return StockValuationGlResponse(
            as_of=valuation.as_of,
            inventory_account_id=account_id,
            valuation_total=valuation.total_value,
            gl_balance=gl_balance,
            difference=quantize_money(valuation.total_value - gl_balance),
        )

    async def stock_movement_report(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        warehouse_id: UUID | None = None,
        product_id: UUID | None = None,
        category_id: UUID | None = None,
    ) -> StockMovementReportResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        statement = select(StockMovement).where(
            StockMovement.tenant_id == tenant_id,
            StockMovement.document_date <= to_date,
            StockMovement.movement_type.notin_(_HOLD_TYPES),
        )
        if warehouse_id is not None:
            statement = statement.where(StockMovement.warehouse_id == warehouse_id)
        if product_id is not None:
            statement = statement.where(StockMovement.product_id == product_id)
        movements = list((await self.session.execute(statement)).scalars().all())
        product_ids = {row.product_id for row in movements}
        products = await self._products_by_id(tenant_id, product_ids)
        if category_id is not None:
            allowed = {
                item_id
                for item_id, product in products.items()
                if product.category_id == category_id
            }
            movements = [row for row in movements if row.product_id in allowed]
            products = {item_id: products[item_id] for item_id in allowed}
        warehouse_ids = {row.warehouse_id for row in movements}
        warehouses = await self._warehouses_by_id(tenant_id, warehouse_ids)
        buckets: dict[tuple[UUID, UUID], dict[str, Decimal]] = defaultdict(
            lambda: {
                "opening_qty": _ZERO,
                "opening_value": _ZERO,
                "qty_in": _ZERO,
                "value_in": _ZERO,
                "qty_out": _ZERO,
                "value_out": _ZERO,
            }
        )
        for row in movements:
            key = (row.warehouse_id, row.product_id)
            qty = row.qty
            value = row.value if row.value is not None else _ZERO
            if row.document_date < from_date:
                buckets[key]["opening_qty"] += qty
                buckets[key]["opening_value"] += value
                continue
            if qty >= _ZERO:
                buckets[key]["qty_in"] += qty
                buckets[key]["value_in"] += value
            else:
                buckets[key]["qty_out"] += -qty
                buckets[key]["value_out"] += -value
        lines: list[StockMovementReportLine] = []
        tot_oq = tot_ov = tot_cq = tot_cv = _ZERO
        for (wh_id, prod_id), totals in sorted(
            buckets.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))
        ):
            opening_qty = quantize_quantity(totals["opening_qty"])
            opening_value = quantize_money(totals["opening_value"])
            qty_in = quantize_quantity(totals["qty_in"])
            value_in = quantize_money(totals["value_in"])
            qty_out = quantize_quantity(totals["qty_out"])
            value_out = quantize_money(totals["value_out"])
            closing_qty = quantize_quantity(opening_qty + qty_in - qty_out)
            closing_value = quantize_money(opening_value + value_in - value_out)
            product = products.get(prod_id)
            warehouse = warehouses.get(wh_id)
            tot_oq += opening_qty
            tot_ov += opening_value
            tot_cq += closing_qty
            tot_cv += closing_value
            lines.append(
                StockMovementReportLine(
                    warehouse_id=wh_id,
                    warehouse_code=warehouse.code if warehouse else "",
                    warehouse_name=warehouse.name if warehouse else "",
                    product_id=prod_id,
                    sku=product.sku if product else "",
                    product_name=product.name if product else "",
                    opening_qty=opening_qty,
                    opening_value=opening_value,
                    qty_in=qty_in,
                    value_in=value_in,
                    qty_out=qty_out,
                    value_out=value_out,
                    closing_qty=closing_qty,
                    closing_value=closing_value,
                )
            )
        return StockMovementReportResponse(
            from_date=from_date,
            to_date=to_date,
            lines=lines,
            total_opening_qty=quantize_quantity(tot_oq),
            total_opening_value=quantize_money(tot_ov),
            total_closing_qty=quantize_quantity(tot_cq),
            total_closing_value=quantize_money(tot_cv),
        )

    async def stock_aging(
        self,
        tenant_id: UUID,
        *,
        as_of: date | None = None,
        warehouse_id: UUID | None = None,
        product_id: UUID | None = None,
        category_id: UUID | None = None,
    ) -> StockAgingResponse:
        as_of_date = as_of or utcnow().date()
        layers, products, warehouses = await self._valuation_layers(
            tenant_id,
            as_of=as_of_date,
            warehouse_id=warehouse_id,
            product_id=product_id,
            category_id=category_id,
        )
        lines: list[StockAgingLine] = []
        totals = StockAgingBucketTotals()
        for layer in layers:
            if layer.qty_remaining == _ZERO:
                continue
            days = (as_of_date - layer.document_date).days
            if days <= 30:
                bucket = "days_0_30"
            elif days <= 60:
                bucket = "days_31_60"
            elif days <= 90:
                bucket = "days_61_90"
            else:
                bucket = "days_91_plus"
            value = quantize_money(layer.qty_remaining * layer.landed_unit_cost)
            qty = quantize_quantity(layer.qty_remaining)
            current = getattr(totals, bucket)
            setattr(totals, bucket, quantize_money(current + value))
            totals.total = quantize_money(totals.total + value)
            product = products.get(layer.product_id)
            warehouse = warehouses.get(layer.warehouse_id)
            lines.append(
                StockAgingLine(
                    warehouse_id=layer.warehouse_id,
                    warehouse_code=warehouse.code if warehouse else "",
                    warehouse_name=warehouse.name if warehouse else "",
                    product_id=layer.product_id,
                    sku=product.sku if product else "",
                    product_name=product.name if product else "",
                    layer_id=layer.id,
                    document_date=layer.document_date,
                    days=days,
                    bucket=bucket,
                    qty_remaining=qty,
                    stock_value=value,
                )
            )
        return StockAgingResponse(as_of=as_of_date, lines=lines, totals=totals)

    async def purchase_suggestions(
        self,
        tenant_id: UUID,
        *,
        warehouse_id: UUID | None = None,
        product_id: UUID | None = None,
        category_id: UUID | None = None,
    ) -> PurchaseSuggestionResponse:
        as_of_date = utcnow().date()
        statement = select(StockBalance).where(StockBalance.tenant_id == tenant_id)
        if warehouse_id is not None:
            statement = statement.where(StockBalance.warehouse_id == warehouse_id)
        if product_id is not None:
            statement = statement.where(StockBalance.product_id == product_id)
        balances = list((await self.session.execute(statement)).scalars().all())
        products = await self._products_by_id(tenant_id, {row.product_id for row in balances})
        if category_id is not None:
            balances = [
                row
                for row in balances
                if products.get(row.product_id) is not None
                and products[row.product_id].category_id == category_id
            ]
        warehouses = await self._warehouses_by_id(tenant_id, {row.warehouse_id for row in balances})
        preferred = await self._preferred_suppliers(tenant_id, {row.product_id for row in balances})
        lines: list[PurchaseSuggestionLine] = []
        for row in balances:
            if row.reorder_level is None:
                continue
            available = available_qty(row.qty_on_hand, row.qty_reserved, row.qty_quality_hold)
            if available > row.reorder_level:
                continue
            if row.reorder_qty is not None and row.reorder_qty > _ZERO:
                suggested = row.reorder_qty
            else:
                shortfall = row.reorder_level - available
                suggested = shortfall if shortfall > _ZERO else row.reorder_level
            suggested = quantize_quantity(suggested)
            if suggested <= _ZERO:
                continue
            product = products.get(row.product_id)
            warehouse = warehouses.get(row.warehouse_id)
            supplier_id, supplier_name = preferred.get(row.product_id, (None, None))
            lines.append(
                PurchaseSuggestionLine(
                    warehouse_id=row.warehouse_id,
                    warehouse_code=warehouse.code if warehouse else "",
                    warehouse_name=warehouse.name if warehouse else "",
                    product_id=row.product_id,
                    sku=product.sku if product else "",
                    product_name=product.name if product else "",
                    qty_on_hand=row.qty_on_hand,
                    qty_available=available,
                    reorder_level=row.reorder_level,
                    reorder_qty=row.reorder_qty,
                    suggested_qty=suggested,
                    preferred_supplier_id=supplier_id,
                    preferred_supplier_name=supplier_name,
                )
            )
        return PurchaseSuggestionResponse(as_of=as_of_date, lines=lines)

    async def _valuation_layers(
        self,
        tenant_id: UUID,
        *,
        as_of: date,
        warehouse_id: UUID | None,
        product_id: UUID | None,
        category_id: UUID | None,
    ) -> tuple[list[StockCostLayer], dict[UUID, Product], dict[UUID, Warehouse]]:
        statement = select(StockCostLayer).where(
            StockCostLayer.tenant_id == tenant_id,
            StockCostLayer.document_date <= as_of,
        )
        if warehouse_id is not None:
            statement = statement.where(StockCostLayer.warehouse_id == warehouse_id)
        if product_id is not None:
            statement = statement.where(StockCostLayer.product_id == product_id)
        statement = statement.order_by(
            StockCostLayer.warehouse_id,
            StockCostLayer.product_id,
            StockCostLayer.document_date,
            StockCostLayer.created_at,
        )
        layers = list((await self.session.execute(statement)).scalars().all())
        products = await self._products_by_id(tenant_id, {row.product_id for row in layers})
        if category_id is not None:
            allowed = {
                item_id
                for item_id, product in products.items()
                if product.category_id == category_id
            }
            layers = [row for row in layers if row.product_id in allowed]
            products = {item_id: products[item_id] for item_id in allowed}
        warehouses = await self._warehouses_by_id(tenant_id, {row.warehouse_id for row in layers})
        return layers, products, warehouses

    async def _products_by_id(self, tenant_id: UUID, ids: set[UUID]) -> dict[UUID, Product]:
        if not ids:
            return {}
        rows = (
            (
                await self.session.execute(
                    select(Product).where(Product.tenant_id == tenant_id, Product.id.in_(list(ids)))
                )
            )
            .scalars()
            .all()
        )
        return {row.id: row for row in rows}

    async def _warehouses_by_id(self, tenant_id: UUID, ids: set[UUID]) -> dict[UUID, Warehouse]:
        if not ids:
            return {}
        rows = (
            (
                await self.session.execute(
                    select(Warehouse).where(
                        Warehouse.tenant_id == tenant_id, Warehouse.id.in_(list(ids))
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.id: row for row in rows}

    async def _preferred_suppliers(
        self, tenant_id: UUID, product_ids: set[UUID]
    ) -> dict[UUID, tuple[UUID | None, str | None]]:
        if not product_ids:
            return {}
        rows = (
            await self.session.execute(
                select(SupplierProduct, Customer.name)
                .join(Customer, Customer.id == SupplierProduct.supplier_id)
                .where(
                    SupplierProduct.tenant_id == tenant_id,
                    SupplierProduct.deleted_at.is_(None),
                    SupplierProduct.product_id.in_(list(product_ids)),
                    SupplierProduct.is_preferred_supplier.is_(True),
                )
            )
        ).all()
        return {link.product_id: (link.supplier_id, name) for link, name in rows}
