"""Product use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import INVENTORY_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.db.session import transaction
from app.erp.accounting.service import TaxService
from app.inventory_management.categories.service import CategoryService
from app.inventory_management.products.models import Product
from app.inventory_management.products.repository import ProductRepository
from app.inventory_management.products.schemas import ProductCreate, ProductResponse, ProductUpdate
from app.inventory_management.units.service import UnitService


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ProductRepository(session)
        self.units = UnitService(session)
        self.categories = CategoryService(session)
        self.taxes = TaxService(session)
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

    async def create(
        self, tenant_id: UUID, payload: ProductCreate, *, actor_user_id: UUID
    ) -> ProductResponse:
        async with transaction(self.session):
            await self._validate_refs(
                tenant_id, payload.unit_id, payload.category_id, payload.tax_id
            )
            values = payload.model_dump()
            values["item_type"] = payload.item_type.value
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
            old_values = await self._product_snapshot(tenant_id, existing)
            await self._validate_refs(
                tenant_id,
                values.get("unit_id"),
                values.get("category_id"),
                values.get("tax_id"),
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
            "tax": tax_name,
            "hs_code": row.hs_code,
            "track_inventory": row.track_inventory,
            "is_active": row.is_active,
        }

    async def _validate_refs(
        self,
        tenant_id: UUID,
        unit_id: UUID | None,
        category_id: UUID | None,
        tax_id: UUID | None,
    ) -> None:
        if unit_id is not None:
            await self.units.require_id(tenant_id, unit_id)
        if category_id is not None:
            await self.categories.require_id(tenant_id, category_id)
        if tax_id is not None:
            await self.taxes.get(tenant_id, tax_id)

    async def _require(self, tenant_id: UUID, product_id: UUID) -> Product:
        row = await self.repo.get(tenant_id, product_id)
        if row is None:
            raise ResourceNotFoundError("Product not found")
        return row
