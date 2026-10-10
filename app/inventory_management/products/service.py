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
from app.common.services.audit import AuditWriter
from app.common.services.master_usage import assert_master_not_referenced
from app.core.enums import AuditAction, ItemType
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.accounting.service import TaxService
from app.inventory_management.categories.service import CategoryService
from app.inventory_management.products.models import Product
from app.inventory_management.products.repository import ProductRepository
from app.inventory_management.products.schemas import (
    ProductCreate,
    ProductInquiryResponse,
    ProductPriceBulkUpdate,
    ProductRenameSkuRequest,
    ProductResponse,
    ProductUpdate,
    ProductWarehouseQty,
)
from app.inventory_management.units.service import UnitService


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ProductRepository(session)
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
        return [ProductResponse.model_validate(row) for row in rows], total

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
            values = payload.model_dump()
            values["item_type"] = payload.item_type.value
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
        warehouses: list[ProductWarehouseQty] = []
        for row in balances:
            qty_on_hand += row.qty_on_hand
            qty_reserved += row.qty_reserved
            qty_available += row.qty_available
            qty_incoming += row.qty_incoming
            warehouses.append(
                ProductWarehouseQty(
                    warehouse_id=row.warehouse_id,
                    warehouse_name=row.warehouse_name,
                    qty_on_hand=row.qty_on_hand,
                    qty_reserved=row.qty_reserved,
                    qty_available=row.qty_available,
                )
            )
        packing_label: str | None = None
        unit2_breakdown: str | None = None
        if product.secondary_unit_id and product.secondary_unit_factor:
            factor = product.secondary_unit_factor
            if factor > 0:
                cartons = int(qty_on_hand // factor)
                pieces = qty_on_hand - Decimal(cartons) * factor
                unit_code = ""
                if product.unit_id:
                    unit_code = (await self.units.get(tenant_id, product.unit_id)).code
                sec_code = (await self.units.get(tenant_id, product.secondary_unit_id)).code
                packing_label = f"{factor} {unit_code} / {sec_code}"
                unit2_breakdown = f"{cartons} {sec_code} & {pieces} {unit_code}"

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

        return ProductInquiryResponse(
            product_id=product_id,
            packing_label=packing_label,
            qty_on_hand=qty_on_hand,
            qty_reserved=qty_reserved,
            qty_available=qty_available,
            qty_incoming=qty_incoming,
            unit2_breakdown=unit2_breakdown,
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
        )

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
