"""Product use cases."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import INVENTORY_MODULE
from app.auth.org_service import OrganizationService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.utils.currency import format_quantity_display
from app.common.services.audit import AuditWriter
from app.common.services.master_usage import assert_master_not_referenced
from app.core.enums import AuditAction, ItemType
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.accounting.service import TaxService
from app.inventory_management.categories.service import CategoryService
from app.inventory_management.products.models import Product
from app.inventory_management.products.inquiry_quantities import (
    build_quantity_rows,
    format_unit2_package_text,
    quantity_unit_breakdown,
)
from app.inventory_management.products.repository import ProductRepository
from app.inventory_management.products.inventory_list_repository import (
    ProductInventoryListRepository,
)
from app.inventory_management.products.list_stats_repository import ProductListStatsRepository
from app.inventory_management.products.schemas import (
    InventoryListFilter,
    ProductCreate,
    ProductInquiryResponse,
    ProductInventoryListRow,
    ProductPriceBulkUpdate,
    ProductRenameSkuRequest,
    ProductResponse,
    ProductUpdate,
    ProductWarehouseQty,
)
from app.core.enums import WarehouseLocationType
from app.inventory_management.units.service import UnitService


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ProductRepository(session)
        self.inventory_list_repo = ProductInventoryListRepository(session)
        self.list_stats = ProductListStatsRepository(session)
        self.units = UnitService(session)
        self.categories = CategoryService(session)
        self.taxes = TaxService(session)
        self.org = OrganizationService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        item_type: str | None = None,
        category_id: UUID | None = None,
        unit_id: UUID | None = None,
        tax_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[ProductResponse], int]:
        filters: dict[str, object] = {}
        if item_type is not None:
            filters["item_type"] = item_type
        if category_id is not None:
            filters["category_id"] = category_id
        if unit_id is not None:
            filters["unit_id"] = unit_id
        if tax_id is not None:
            filters["tax_id"] = tax_id
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        product_ids = [row.id for row in rows]
        stats_map = await self.list_stats.batch(tenant_id, product_ids)
        responses: list[ProductResponse] = []
        for row in rows:
            base = ProductResponse.model_validate(row)
            stats = stats_map.get(row.id)
            if stats is None:
                responses.append(base)
                continue
            responses.append(
                base.model_copy(
                    update={
                        "qty_on_hand": stats.qty_on_hand,
                        "qty_opened": stats.qty_opened,
                        "qty_committed": stats.qty_committed,
                        "net_available": stats.net_available,
                        "shop_qty": stats.shop_qty,
                        "warehouse_qty": stats.warehouse_qty,
                        "ordered_qty": stats.ordered_qty,
                        "last_sale_date": stats.last_sale_date,
                        "last_sale_price": stats.last_sale_price,
                        "last_purchase_date": stats.last_purchase_date,
                        "last_purchase_price": stats.last_purchase_price,
                    }
                )
            )
        return responses, total

    async def sync_avg_cost_from_fifo(
        self, tenant_id: UUID, product_ids: set[UUID] | frozenset[UUID]
    ) -> None:
        """Refresh product purchase_rate from weighted FIFO avg (Winsoft avg cost)."""
        from app.common.utils.currency import quantize_money
        from app.inventory_management.costing.repository import CostingRepository
        from app.inventory_management.stock.repository import StockBalanceRepository

        if not product_ids:
            return
        cost_repo = CostingRepository(self.session)
        balance_repo = StockBalanceRepository(self.session)
        for product_id in product_ids:
            balances, _ = await balance_repo.list(
                tenant_id,
                page=PageParams(page=1, page_size=500),
                filters={"product_id": product_id},
            )
            all_layers = []
            for balance in balances:
                all_layers.extend(
                    await cost_repo.list_positive_fifo(
                        tenant_id, balance.warehouse_id, product_id
                    )
                )
            if not all_layers:
                continue
            total_qty = sum(layer.qty_remaining for layer in all_layers)
            if total_qty <= 0:
                continue
            weighted = sum(layer.qty_remaining * layer.landed_unit_cost for layer in all_layers)
            avg_cost = quantize_money(weighted / total_qty)
            await self.repo.update(tenant_id, product_id, {"purchase_rate": avg_cost})

    async def get(self, tenant_id: UUID, product_id: UUID) -> ProductResponse:
        return ProductResponse.model_validate(await self._require(tenant_id, product_id))

    async def find_by_sku(self, tenant_id: UUID, sku: str) -> ProductResponse | None:
        token = sku.strip()
        if not token:
            return None
        row = await self.repo.get_by_sku(tenant_id, token)
        if row is None:
            return None
        return ProductResponse.model_validate(row)

    async def import_rows(
        self,
        tenant_id: UUID,
        *,
        filename: str | None,
        content: bytes,
        mapping: builtins.list[object],
        actor_user_id: UUID,
    ):
        from app.common.imex.http import mapping_or_suggested
        from app.common.imex.schemas import ImexMappingEntry, ImportResult, ImportRowError
        from app.common.imex.service import mapped_rows, parse_optional_decimal

        entries = [
            item if isinstance(item, ImexMappingEntry) else ImexMappingEntry.model_validate(item)
            for item in mapping
        ]
        resolved = mapping_or_suggested(
            "product", filename=filename, content=content, mapping=entries
        )
        rows = mapped_rows(filename=filename, content=content, mapping=resolved)
        created_ids: builtins.list[UUID] = []
        errors: builtins.list[ImportRowError] = []
        for index, row in enumerate(rows, start=2):
            try:
                sku = (row.get("sku") or "").strip()
                name = (row.get("name") or "").strip()
                if not sku or not name:
                    raise ValidationError("SKU and name are required")
                selling_rate = (
                    parse_optional_decimal(row.get("selling_rate")) or Decimal("0")
                )
                purchase_rate = (
                    parse_optional_decimal(row.get("purchase_rate")) or Decimal("0")
                )
                existing = await self.find_by_sku(tenant_id, sku)
                if existing is not None:
                    await self.update(
                        tenant_id,
                        existing.id,
                        ProductUpdate(
                            name=name,
                            selling_rate=selling_rate,
                            purchase_rate=purchase_rate,
                        ),
                        actor_user_id=actor_user_id,
                    )
                else:
                    created = await self.create(
                        tenant_id,
                        ProductCreate(
                            sku=sku,
                            name=name,
                            selling_rate=selling_rate,
                            purchase_rate=purchase_rate,
                        ),
                        actor_user_id=actor_user_id,
                    )
                    created_ids.append(created.id)
            except (ValidationError, DuplicateResourceError, ValueError) as exc:
                errors.append(ImportRowError(row_number=index, message=str(exc)))
        return ImportResult(
            created_ids=created_ids,
            errors=errors,
            created_count=len(created_ids),
            error_count=len(errors),
        )

    async def get_many(
        self, tenant_id: UUID, product_ids: Sequence[UUID]
    ) -> dict[UUID, ProductResponse]:
        rows = await self.repo.get_many(tenant_id, product_ids)
        return {row.id: ProductResponse.model_validate(row) for row in rows}

    async def search_ids(self, tenant_id: UUID, search: str) -> builtins.list[UUID]:
        return await self.repo.search_ids(tenant_id, search)

    async def ids_by_category(self, tenant_id: UUID, category_id: UUID) -> builtins.list[UUID]:
        return await self.repo.ids_by_category(tenant_id, category_id)

    async def require_stockable(self, tenant_id: UUID, product_id: UUID) -> ProductResponse:
        product = await self.require_active(tenant_id, product_id)
        if product.item_type == ItemType.SERVICE:
            raise ValidationError("Service products cannot be stocked")
        if not product.track_inventory:
            raise ValidationError("Inventory tracking is disabled for this product")
        return product

    async def require_active(self, tenant_id: UUID, product_id: UUID) -> ProductResponse:
        product = await self.get(tenant_id, product_id)
        if not product.is_active:
            raise ValidationError("Product is inactive")
        return product

    async def create(
        self, tenant_id: UUID, payload: ProductCreate, *, actor_user_id: UUID
    ) -> ProductResponse:
        async with transaction(self.session):
            await self._validate_refs(
                tenant_id,
                payload.unit_id,
                payload.category_id,
                payload.tax_id,
                payload.income_account_id,
                payload.purchase_account_id,
            )
            if payload.secondary_unit_id is not None:
                await self._validate_secondary_unit(
                    tenant_id,
                    unit_id=payload.unit_id,
                    secondary_unit_id=payload.secondary_unit_id,
                    secondary_unit_factor=payload.secondary_unit_factor,
                )
            values = payload.model_dump()
            values["item_type"] = payload.item_type.value
            if payload.unit_id is None:
                values["pieces_per_unit"] = None
            if payload.requires_qc is None:
                inbound = await self.org.get_inbound_settings(tenant_id)
                values["requires_qc"] = inbound.qc_required_default
            values["created_by"] = actor_user_id
            values["updated_by"] = actor_user_id
            try:
                row = await self.repo.create(tenant_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A product with this SKU already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="product",
                entity_id=row.id,
                new_values=await self._product_snapshot(tenant_id, row),
            )
            return ProductResponse.model_validate(row)

    async def update(
        self, tenant_id: UUID, product_id: UUID, payload: ProductUpdate, *, actor_user_id: UUID
    ) -> ProductResponse:
        values = payload.model_dump(exclude_unset=True)
        if payload.item_type is not None:
            values["item_type"] = payload.item_type.value
        if "unit_id" in values and values.get("unit_id") is None:
            values["pieces_per_unit"] = None
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, product_id)
            if values.get("is_active") is False and existing.is_active:
                await assert_master_not_referenced(
                    self.session,
                    tenant_id=tenant_id,
                    table_name=Product.__tablename__,
                    record_id=product_id,
                    label="product",
                    action="deactivate",
                    exclude_tables=frozenset({"stock_balances"}),
                )
                from app.inventory_management.stock.service import StockService

                stock = StockService(self.session)
                if await stock.balances.has_nonzero_balance(tenant_id, product_id):
                    raise ValidationError("Cannot deactivate product with stock on hand")
            if "unit_id" in values and values.get("unit_id") != existing.unit_id:
                from app.inventory_management.stock.service import StockService

                if await StockService(self.session).product_has_activity(tenant_id, product_id):
                    raise ValidationError("Cannot change product unit after stock activity")
            if values.get("track_inventory") is False and existing.track_inventory:
                from app.inventory_management.stock.service import StockService

                if await StockService(self.session).product_has_activity(tenant_id, product_id):
                    raise ValidationError(
                        "Cannot turn off inventory tracking after stock movements or balances exist"
                    )
            old_values = await self._product_snapshot(tenant_id, existing)
            await self._validate_refs(
                tenant_id,
                values.get("unit_id"),
                values.get("category_id"),
                values.get("tax_id"),
                values.get("income_account_id"),
                values.get("purchase_account_id"),
            )
            if "secondary_unit_id" in values or "secondary_unit_factor" in values:
                merged_unit_id = (
                    values["unit_id"] if "unit_id" in values else existing.unit_id
                )
                merged_secondary_id = (
                    values["secondary_unit_id"]
                    if "secondary_unit_id" in values
                    else existing.secondary_unit_id
                )
                merged_factor = (
                    values["secondary_unit_factor"]
                    if "secondary_unit_factor" in values
                    else existing.secondary_unit_factor
                )
                await self._validate_secondary_unit(
                    tenant_id,
                    unit_id=merged_unit_id,
                    secondary_unit_id=merged_secondary_id,
                    secondary_unit_factor=merged_factor,
                )
            if values.get("secondary_unit_id") is None and "secondary_unit_id" in values:
                values["secondary_unit_factor"] = None
            try:
                row = await self.repo.update(tenant_id, product_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A product with this SKU already exists") from exc
            if row is None:
                raise ResourceNotFoundError("Product not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="product",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._product_snapshot(tenant_id, row),
            )
            return ProductResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, product_id: UUID, *, actor_user_id: UUID
    ) -> ProductResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, product_id)
            await assert_master_not_referenced(
                self.session,
                tenant_id=tenant_id,
                table_name=Product.__tablename__,
                record_id=product_id,
                label="product",
            )
            response = ProductResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, product_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="product",
                entity_id=product_id,
                old_values=await self._product_snapshot(tenant_id, row),
            )
            return response

    async def _product_snapshot(self, tenant_id: UUID, row: Product) -> dict[str, object]:
        unit_code: str | None = None
        if row.unit_id is not None:
            unit_code = (await self.units.get(tenant_id, row.unit_id)).code
        category_name: str | None = None
        if row.category_id is not None:
            category_name = (await self.categories.get(tenant_id, row.category_id)).name
        tax_name: str | None = None
        if row.tax_id is not None:
            tax_name = (await self.taxes.get(tenant_id, row.tax_id)).name
        return {
            "item_type": row.item_type,
            "sku": row.sku,
            "name": row.name,
            "sales_description": row.sales_description,
            "unit": unit_code,
            "pieces_per_unit": row.pieces_per_unit,
            "category": category_name,
            "selling_rate": row.selling_rate,
            "purchase_rate": row.purchase_rate,
            "purchase_description": row.purchase_description,
            "tax": tax_name,
            "hs_code": row.hs_code,
            "track_inventory": row.track_inventory,
            "requires_qc": row.requires_qc,
            "is_active": row.is_active,
        }

    async def _validate_secondary_unit(
        self,
        tenant_id: UUID,
        *,
        unit_id: UUID | None,
        secondary_unit_id: UUID | None,
        secondary_unit_factor: Decimal | None,
    ) -> None:
        if secondary_unit_id is None:
            return
        await self.units.require_id(tenant_id, secondary_unit_id)
        if unit_id is not None and secondary_unit_id == unit_id:
            raise ValidationError("Unit 2 must differ from the base unit")
        if secondary_unit_factor is None or secondary_unit_factor <= 0:
            raise ValidationError("Enter pieces per unit 2 when unit 2 is set")

    async def _validate_refs(
        self,
        tenant_id: UUID,
        unit_id: UUID | None,
        category_id: UUID | None,
        tax_id: UUID | None,
        income_account_id: UUID | None = None,
        purchase_account_id: UUID | None = None,
    ) -> None:
        if unit_id is not None:
            await self.units.require_id(tenant_id, unit_id)
        if category_id is not None:
            await self.categories.require_id(tenant_id, category_id)
        if tax_id is not None:
            await self.taxes.require_id(tenant_id, tax_id)
        if income_account_id is not None or purchase_account_id is not None:
            from app.erp.accounting.accounts.service import AccountService

            accounts = AccountService(self.session)
            if income_account_id is not None:
                await accounts.require_postable(tenant_id, income_account_id)
            if purchase_account_id is not None:
                await accounts.require_postable(tenant_id, purchase_account_id)

    async def _require(self, tenant_id: UUID, product_id: UUID) -> Product:
        row = await self.repo.get(tenant_id, product_id)
        if row is None:
            raise ResourceNotFoundError("Product not found")
        return row

    async def inquiry(self, tenant_id: UUID, product_id: UUID) -> ProductInquiryResponse:
        from app.common.schemas.pagination import PageParams
        from app.inventory_management.costing.repository import CostingRepository
        from app.inventory_management.history.schemas import TradingHistoryFilter
        from app.inventory_management.history.service import HistoryService
        from app.inventory_management.stock.service import StockService

        product = await self._require(tenant_id, product_id)
        stock = StockService(self.session)
        balances, _ = await stock.list_balances(
            tenant_id,
            page=PageParams(page=1, page_size=200),
            product_id=product_id,
        )
        qty_on_hand = Decimal("0")
        qty_reserved = Decimal("0")
        qty_available = Decimal("0")
        qty_incoming = Decimal("0")
        shop_qty = Decimal("0")
        warehouse_qty = Decimal("0")
        warehouses: list[ProductWarehouseQty] = []
        warehouse_cache: dict[UUID, object] = {}
        for row in balances:
            qty_on_hand += row.qty_on_hand
            qty_reserved += row.qty_reserved
            qty_available += row.qty_available
            qty_incoming += row.qty_incoming
            wh = warehouse_cache.get(row.warehouse_id)
            if wh is None:
                from app.inventory_management.warehouses.service import WarehouseService

                wh = await WarehouseService(self.session).get(tenant_id, row.warehouse_id)
                warehouse_cache[row.warehouse_id] = wh
            if wh.location_type == WarehouseLocationType.SHOP:
                shop_qty += row.qty_on_hand
            else:
                warehouse_qty += row.qty_on_hand
            warehouses.append(
                ProductWarehouseQty(
                    warehouse_id=row.warehouse_id,
                    warehouse_name=row.warehouse_name,
                    qty_on_hand=row.qty_on_hand,
                    qty_reserved=row.qty_reserved,
                    qty_available=row.qty_available,
                )
            )
        qty_opened = await self.inventory_list_repo.draft_opened_for_product(tenant_id, product_id)
        qty_committed = qty_reserved
        net_available = qty_on_hand - qty_opened - qty_committed
        if net_available < 0:
            net_available = Decimal("0")
        packing_label: str | None = None
        unit2_breakdown: str | None = None
        if product.secondary_unit_id and product.secondary_unit_factor:
            factor = product.secondary_unit_factor
            if factor > 0:
                on_hand_breakdown = quantity_unit_breakdown(qty_on_hand, factor)
                unit_code = ""
                if product.unit_id:
                    unit_code = (await self.units.get(tenant_id, product.unit_id)).code
                sec_code = (await self.units.get(tenant_id, product.secondary_unit_id)).code
                packing_label = (
                    f"{format_quantity_display(factor)} {unit_code} / {sec_code}"
                )
                unit2_breakdown = format_unit2_package_text(
                    on_hand_breakdown.unit2_qty,
                    on_hand_breakdown.remainder_qty,
                    unit_code,
                    sec_code,
                )

        avg_cost: Decimal | None = None
        lc_price: Decimal | None = None
        lc_currency: str | None = None
        cost_repo = CostingRepository(self.session)
        all_layers = []
        for wh in warehouses:
            all_layers.extend(
                await cost_repo.list_positive_fifo(tenant_id, wh.warehouse_id, product_id)
            )
        if all_layers:
            total_qty = sum(layer.qty_remaining for layer in all_layers)
            if total_qty > 0:
                weighted = sum(layer.qty_remaining * layer.landed_unit_cost for layer in all_layers)
                avg_cost = weighted / total_qty
            latest = max(all_layers, key=lambda layer: layer.created_at)
            lc_price = latest.landed_unit_cost

        history = HistoryService(self.session)
        history_filter = TradingHistoryFilter(sort_by="document_date", sort_order="desc")
        sales, _ = await history.product_sales_history(
            tenant_id,
            product_id,
            page=PageParams(page=1, page_size=1),
            filters=history_filter,
        )
        purchases, _ = await history.product_purchase_history(
            tenant_id,
            product_id,
            page=PageParams(page=1, page_size=1),
            filters=history_filter,
        )
        last_sale = sales[0] if sales else None
        last_purchase = purchases[0] if purchases else None

        factor = product.secondary_unit_factor if product.secondary_unit_factor else None
        quantity_rows = build_quantity_rows(
            qty_on_hand=qty_on_hand,
            qty_opened=qty_opened,
            qty_committed=qty_committed,
            net_available=net_available,
            factor=factor,
        )
        category_name: str | None = None
        if product.category_id:
            category_name = (await self.categories.get(tenant_id, product.category_id)).name
        tax_name: str | None = None
        tax_rate: Decimal | None = None
        if product.tax_id:
            tax_row = await self.taxes.get(tenant_id, product.tax_id)
            tax_name = tax_row.name
            tax_rate = tax_row.rate
        unit_code: str | None = None
        unit2_code: str | None = None
        if product.unit_id:
            unit_code = (await self.units.get(tenant_id, product.unit_id)).code
        if product.secondary_unit_id:
            unit2_code = (await self.units.get(tenant_id, product.secondary_unit_id)).code

        return ProductInquiryResponse(
            product_id=product_id,
            packing_label=packing_label,
            qty_on_hand=qty_on_hand,
            qty_reserved=qty_reserved,
            qty_available=qty_available,
            qty_incoming=qty_incoming,
            qty_opened=qty_opened,
            qty_committed=qty_committed,
            net_available=net_available,
            ordered_qty=qty_incoming,
            shop_qty=shop_qty,
            warehouse_qty=warehouse_qty,
            unit2_breakdown=unit2_breakdown,
            quantity_rows=quantity_rows,
            warehouses=warehouses,
            avg_cost=avg_cost,
            lc_price=lc_price,
            lc_currency_code=lc_currency,
            last_sale_date=str(last_sale.document_date) if last_sale else None,
            last_sale_price=last_sale.rate if last_sale else None,
            last_sale_quantity=last_sale.quantity if last_sale else None,
            last_purchase_date=str(last_purchase.document_date) if last_purchase else None,
            last_purchase_price=last_purchase.rate if last_purchase else None,
            last_purchase_quantity=last_purchase.quantity if last_purchase else None,
            sku=product.sku,
            name=product.name,
            alias_2=product.alias_2,
            alias_3=product.alias_3,
            alias_4=product.alias_4,
            volume=product.volume,
            brand=product.brand,
            origin_country_code=product.origin_country_code,
            engine=product.engine,
            category_name=category_name,
            tax_name=tax_name,
            tax_rate=tax_rate,
            selling_rate=product.selling_rate,
            price_1=product.price_1,
            price_2=product.price_2,
            purchase_rate=product.purchase_rate,
            net_weight=product.net_weight,
            gross_weight=product.gross_weight,
            rem=product.rem,
            remarks=product.remarks,
            unit_code=unit_code,
            unit2_code=unit2_code,
        )

    async def inventory_list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        filters: InventoryListFilter,
    ) -> tuple[list[ProductInventoryListRow], int]:
        rows, total = await self.inventory_list_repo.list_rows(
            tenant_id,
            page=page,
            search=filters.search,
            search_type=filters.search_type,
            category_id=filters.category_id,
            brand=filters.brand,
            engine=filters.engine,
            tracked_only=filters.tracked_only,
            sort_by=filters.sort_by,
            sort_order=filters.sort_order,
        )
        result: list[ProductInventoryListRow] = []
        for row in rows:
            packing_label: str | None = None
            if row.secondary_unit_id and row.secondary_unit_factor and row.unit_id:
                unit_code = (await self.units.get(tenant_id, row.unit_id)).code
                sec_code = (await self.units.get(tenant_id, row.secondary_unit_id)).code
                packing_label = (
                    f"{format_quantity_display(row.secondary_unit_factor)} "
                    f"{unit_code} / {sec_code}"
                )
            net_avail = Decimal(row.net_available or 0)
            result.append(
                ProductInventoryListRow(
                    product_id=row.id,
                    sku=row.sku,
                    name=row.name,
                    net_quantity=net_avail,
                    net_available=net_avail,
                    volume=row.volume,
                    alias_2=row.alias_2,
                    alias_3=row.alias_3,
                    alias_4=row.alias_4,
                    brand=row.brand,
                    engine=row.engine,
                    packing_label=packing_label,
                    selling_rate=row.selling_rate,
                    price_1=row.price_1,
                    price_2=row.price_2,
                    purchase_rate=row.purchase_rate,
                    avg_cost=row.purchase_rate,
                    ordered_qty=Decimal(row.ordered_qty or 0),
                    shop_qty=Decimal(row.shop_qty or 0),
                    warehouse_qty=Decimal(row.warehouse_qty or 0),
                    qty_on_hand=Decimal(row.qty_on_hand or 0),
                    qty_opened=Decimal(row.qty_opened or 0),
                    qty_committed=Decimal(row.qty_committed or 0),
                )
            )
        return result, total

    async def bulk_update_prices(
        self,
        tenant_id: UUID,
        payload: ProductPriceBulkUpdate,
        *,
        actor_user_id: UUID,
    ) -> list[ProductResponse]:
        updated: list[ProductResponse] = []
        async with transaction(self.session):
            for item in payload.items:
                values = item.model_dump(exclude={"id"}, exclude_unset=True)
                if not values:
                    continue
                values["updated_by"] = actor_user_id
                row = await self.repo.update(tenant_id, item.id, values)
                if row is None:
                    raise ResourceNotFoundError(f"Product {item.id} not found")
                updated.append(ProductResponse.model_validate(row))
        return updated

    async def rename_sku(
        self,
        tenant_id: UUID,
        product_id: UUID,
        payload: ProductRenameSkuRequest,
        *,
        actor_user_id: UUID,
    ) -> ProductResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, product_id)
            old = existing.sku
            try:
                row = await self.repo.update(
                    tenant_id,
                    product_id,
                    {"sku": payload.sku, "updated_by": actor_user_id},
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A product with this SKU already exists") from exc
            if row is None:
                raise ResourceNotFoundError("Product not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="product",
                entity_id=product_id,
                old_values={"sku": old},
                new_values={"sku": payload.sku},
            )
            return ProductResponse.model_validate(row)
