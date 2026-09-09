"""Supplier product catalog use cases."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from typing import NoReturn
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ERP_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.datetime import utcnow
from app.core.enums import AuditAction
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.exchange_rates.service import CurrencyService
from app.erp.supplier_products.models import SupplierProduct
from app.erp.supplier_products.repository import SupplierProductRepository
from app.erp.supplier_products.schemas import (
    SupplierProductCreate,
    SupplierProductResolveResponse,
    SupplierProductResponse,
    SupplierProductUpdate,
    SupplierSkuResolveStatus,
)
from app.erp.suppliers.service import SupplierService
from app.inventory_management.products.service import ProductService

_SKU_CONSTRAINT = "uq_supplier_products_tenant_supplier_sku_active"
_PREFERRED_CONSTRAINT = "uq_supplier_products_tenant_supplier_product_preferred"
_PREFERRED_SUPPLIER_CONSTRAINT = "uq_supplier_products_tenant_product_preferred_supplier"


def normalize_supplier_sku(value: str) -> str:
    """Trim and uppercase a supplier SKU for uniqueness and resolve lookups."""

    return value.strip().upper()


def _constraint_name(exc: IntegrityError) -> str:
    orig = exc.orig
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None) if diag is not None else None
    if name:
        return str(name)
    return str(orig or exc)


class SupplierProductService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = SupplierProductRepository(session)
        self.suppliers = SupplierService(session)
        self.products = ProductService(session)
        self.currencies = CurrencyService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        supplier_id: UUID | None = None,
        product_id: UUID | None = None,
        mapped: bool | None = None,
        is_active: bool | None = None,
        is_preferred: bool | None = None,
        is_preferred_supplier: bool | None = None,
    ) -> tuple[builtins.list[SupplierProductResponse], int]:
        filters: dict[str, object] = {}
        if supplier_id is not None:
            filters["supplier_id"] = supplier_id
        if product_id is not None:
            filters["product_id"] = product_id
        if is_active is not None:
            filters["is_active"] = is_active
        if is_preferred is not None:
            filters["is_preferred"] = is_preferred
        if is_preferred_supplier is not None:
            filters["is_preferred_supplier"] = is_preferred_supplier
        extra = []
        if mapped is True:
            extra.append(SupplierProduct.product_id.is_not(None))
        elif mapped is False:
            extra.append(SupplierProduct.product_id.is_(None))
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        return await self._to_responses(tenant_id, rows), total

    async def get(self, tenant_id: UUID, supplier_product_id: UUID) -> SupplierProductResponse:
        row = await self._require(tenant_id, supplier_product_id)
        return await self._to_response(tenant_id, row)

    async def create(
        self, tenant_id: UUID, payload: SupplierProductCreate, *, actor_user_id: UUID
    ) -> SupplierProductResponse:
        async with transaction(self.session):
            supplier = await self.suppliers.get(tenant_id, payload.supplier_id)
            if payload.product_id is not None:
                await self.products.get(tenant_id, payload.product_id)
            currency_id = payload.currency_id or supplier.currency_id
            await self.currencies.require_id(tenant_id, currency_id)
            self._assert_preferred_requires_product(
                payload.product_id, payload.is_preferred, payload.is_preferred_supplier
            )
            await self._demote_for_flags(
                tenant_id,
                supplier_id=payload.supplier_id,
                product_id=payload.product_id,
                is_preferred=payload.is_preferred,
                is_preferred_supplier=payload.is_preferred_supplier,
            )
            normalized = normalize_supplier_sku(payload.supplier_sku)
            values: dict[str, object] = {
                "supplier_id": payload.supplier_id,
                "product_id": payload.product_id,
                "supplier_sku": payload.supplier_sku,
                "supplier_sku_normalized": normalized,
                "supplier_item_name": payload.supplier_item_name,
                "supplier_description": payload.supplier_description,
                "price": payload.price,
                "currency_id": currency_id,
                "price_updated_at": utcnow() if payload.price is not None else None,
                "is_preferred": payload.is_preferred,
                "is_preferred_supplier": payload.is_preferred_supplier,
                "notes": payload.notes,
                "is_active": payload.is_active,
                "created_by": actor_user_id,
                "updated_by": actor_user_id,
            }
            try:
                row = await self.repo.create(tenant_id, values)
            except IntegrityError as exc:
                self._raise_integrity(exc, sku=payload.supplier_sku)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ERP_MODULE,
                entity_type="supplier_product",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, row),
            )
            return await self._to_response(tenant_id, row)

    async def update(
        self,
        tenant_id: UUID,
        supplier_product_id: UUID,
        payload: SupplierProductUpdate,
        *,
        actor_user_id: UUID,
    ) -> SupplierProductResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            existing = await self._require(tenant_id, supplier_product_id)
            old_values = await self._snapshot(tenant_id, existing)
            if "currency_id" in values and values["currency_id"] is not None:
                await self.currencies.require_id(tenant_id, values["currency_id"])
            if "supplier_sku" in values and values["supplier_sku"] is not None:
                values["supplier_sku_normalized"] = normalize_supplier_sku(
                    str(values["supplier_sku"])
                )
            if "price" in values:
                new_price = values["price"]
                if new_price != existing.price:
                    values["price_updated_at"] = utcnow()
            is_preferred = (
                payload.is_preferred if payload.is_preferred is not None else existing.is_preferred
            )
            is_preferred_supplier = (
                payload.is_preferred_supplier
                if payload.is_preferred_supplier is not None
                else existing.is_preferred_supplier
            )
            self._assert_preferred_requires_product(
                existing.product_id, is_preferred, is_preferred_supplier
            )
            await self._demote_for_flags(
                tenant_id,
                supplier_id=existing.supplier_id,
                product_id=existing.product_id,
                is_preferred=is_preferred,
                is_preferred_supplier=is_preferred_supplier,
                except_id=existing.id,
            )
            values["updated_by"] = actor_user_id
            try:
                row = await self.repo.update(tenant_id, supplier_product_id, values)
            except IntegrityError as exc:
                sku = str(values.get("supplier_sku") or existing.supplier_sku)
                self._raise_integrity(exc, sku=sku)
            if row is None:
                raise ResourceNotFoundError("Supplier product not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ERP_MODULE,
                entity_type="supplier_product",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            return await self._to_response(tenant_id, row)

    async def delete(
        self, tenant_id: UUID, supplier_product_id: UUID, *, actor_user_id: UUID
    ) -> SupplierProductResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, supplier_product_id)
            response = await self._to_response(tenant_id, row)
            old_values = await self._snapshot(tenant_id, row)
            await self.repo.soft_delete(tenant_id, supplier_product_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="supplier_product",
                entity_id=supplier_product_id,
                old_values=old_values,
            )
            return response

    async def link(
        self,
        tenant_id: UUID,
        supplier_product_id: UUID,
        product_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> SupplierProductResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, supplier_product_id)
            await self.products.get(tenant_id, product_id)
            old_values = await self._snapshot(tenant_id, row)
            await self._assert_link_preferred_ok(tenant_id, row, product_id=product_id)
            try:
                updated = await self.repo.update(
                    tenant_id,
                    supplier_product_id,
                    {"product_id": product_id, "updated_by": actor_user_id},
                )
            except IntegrityError as exc:
                self._raise_integrity(exc, sku=row.supplier_sku)
            if updated is None:
                raise ResourceNotFoundError("Supplier product not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.LINK,
                module=ERP_MODULE,
                entity_type="supplier_product",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, updated),
            )
            return await self._to_response(tenant_id, updated)

    async def unlink(
        self, tenant_id: UUID, supplier_product_id: UUID, *, actor_user_id: UUID
    ) -> SupplierProductResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, supplier_product_id)
            old_values = await self._snapshot(tenant_id, row)
            updated = await self.repo.update(
                tenant_id,
                supplier_product_id,
                {
                    "product_id": None,
                    "is_preferred": False,
                    "is_preferred_supplier": False,
                    "updated_by": actor_user_id,
                },
            )
            if updated is None:
                raise ResourceNotFoundError("Supplier product not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UNLINK,
                module=ERP_MODULE,
                entity_type="supplier_product",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, updated),
            )
            return await self._to_response(tenant_id, updated)

    async def resolve(
        self, tenant_id: UUID, *, supplier_id: UUID, supplier_sku: str
    ) -> SupplierProductResolveResponse:
        await self.suppliers.get(tenant_id, supplier_id)
        printed = supplier_sku.strip()
        if not printed:
            return SupplierProductResolveResponse(
                supplier_sku=supplier_sku,
                status=SupplierSkuResolveStatus.UNKNOWN_SKU,
            )
        row = await self.repo.find_by_normalized_sku(
            tenant_id, supplier_id, normalize_supplier_sku(printed)
        )
        return await self._resolve_row(tenant_id, printed, row)

    async def resolve_batch(
        self, tenant_id: UUID, *, supplier_id: UUID, supplier_skus: Sequence[str]
    ) -> builtins.list[SupplierProductResolveResponse]:
        await self.suppliers.get(tenant_id, supplier_id)
        normalized_to_row: dict[str, SupplierProduct] = {}
        lookups = [normalize_supplier_sku(sku) for sku in supplier_skus if sku.strip()]
        if lookups:
            rows = await self.repo.find_by_normalized_skus(tenant_id, supplier_id, lookups)
            normalized_to_row = {row.supplier_sku_normalized: row for row in rows}
        results: builtins.list[SupplierProductResolveResponse] = []
        for sku in supplier_skus:
            printed = sku.strip()
            if not printed:
                results.append(
                    SupplierProductResolveResponse(
                        supplier_sku=sku,
                        status=SupplierSkuResolveStatus.UNKNOWN_SKU,
                    )
                )
                continue
            row = normalized_to_row.get(normalize_supplier_sku(printed))
            results.append(await self._resolve_row(tenant_id, printed, row))
        return results

    async def _resolve_row(
        self, tenant_id: UUID, supplier_sku: str, row: SupplierProduct | None
    ) -> SupplierProductResolveResponse:
        if row is None:
            return SupplierProductResolveResponse(
                supplier_sku=supplier_sku,
                status=SupplierSkuResolveStatus.UNKNOWN_SKU,
            )
        product_sku: str | None = None
        product_name: str | None = None
        if row.product_id is not None:
            try:
                product = await self.products.get(tenant_id, row.product_id)
                product_sku = product.sku
                product_name = product.name
            except ResourceNotFoundError:
                product_sku = None
                product_name = None
        status = (
            SupplierSkuResolveStatus.MAPPED
            if row.product_id is not None
            else SupplierSkuResolveStatus.UNMAPPED
        )
        return SupplierProductResolveResponse(
            supplier_sku=supplier_sku,
            status=status,
            supplier_product_id=row.id,
            product_id=row.product_id,
            product_sku=product_sku,
            product_name=product_name,
        )

    async def _assert_link_preferred_ok(
        self, tenant_id: UUID, row: SupplierProduct, *, product_id: UUID
    ) -> None:
        if row.is_preferred:
            incumbent = await self.repo.find_preferred(
                tenant_id, supplier_id=row.supplier_id, product_id=product_id
            )
            if incumbent is not None and incumbent.id != row.id:
                raise ValidationError(
                    "This supplier already has a preferred SKU for this product",
                    details={"field": "product_id"},
                )
        if row.is_preferred_supplier:
            incumbent = await self.repo.find_preferred_supplier(tenant_id, product_id)
            if incumbent is not None and incumbent.id != row.id:
                raise ValidationError(
                    "This product already has a preferred supplier",
                    details={"field": "product_id"},
                )

    async def _demote_for_flags(
        self,
        tenant_id: UUID,
        *,
        supplier_id: UUID,
        product_id: UUID | None,
        is_preferred: bool,
        is_preferred_supplier: bool,
        except_id: UUID | None = None,
    ) -> None:
        if product_id is None:
            return
        if is_preferred:
            await self.repo.demote_preferred(
                tenant_id,
                supplier_id=supplier_id,
                product_id=product_id,
                except_id=except_id,
            )
        if is_preferred_supplier:
            await self.repo.demote_preferred_supplier(
                tenant_id, product_id=product_id, except_id=except_id
            )

    @staticmethod
    def _assert_preferred_requires_product(
        product_id: UUID | None, is_preferred: bool, is_preferred_supplier: bool
    ) -> None:
        if (is_preferred or is_preferred_supplier) and product_id is None:
            raise ValidationError("Preferred flags require a mapped product")

    def _raise_integrity(self, exc: IntegrityError, *, sku: str) -> NoReturn:
        name = _constraint_name(exc)
        if _SKU_CONSTRAINT in name:
            raise ValidationError(
                f"Supplier SKU '{sku}' already exists for this supplier",
                details={"field": "supplier_sku"},
            ) from exc
        if _PREFERRED_CONSTRAINT in name:
            raise ValidationError(
                "This supplier already has a preferred SKU for this product",
                details={"field": "is_preferred"},
            ) from exc
        if _PREFERRED_SUPPLIER_CONSTRAINT in name:
            raise ValidationError(
                "This product already has a preferred supplier",
                details={"field": "is_preferred_supplier"},
            ) from exc
        raise ValidationError("Supplier product already exists") from exc

    async def _snapshot(self, tenant_id: UUID, row: SupplierProduct) -> dict[str, object]:
        supplier_name: str | None = None
        try:
            supplier_name = (await self.suppliers.get(tenant_id, row.supplier_id)).name
        except ResourceNotFoundError:
            supplier_name = None
        product_sku: str | None = None
        if row.product_id is not None:
            try:
                product_sku = (await self.products.get(tenant_id, row.product_id)).sku
            except ResourceNotFoundError:
                product_sku = None
        currency = await self.currencies.get(tenant_id, row.currency_id)
        return {
            "supplier": supplier_name,
            "product": product_sku,
            "supplier_sku": row.supplier_sku,
            "supplier_item_name": row.supplier_item_name,
            "price": row.price,
            "currency": currency.code,
            "is_preferred": row.is_preferred,
            "is_preferred_supplier": row.is_preferred_supplier,
            "is_active": row.is_active,
        }

    async def _to_responses(
        self, tenant_id: UUID, rows: Sequence[SupplierProduct]
    ) -> builtins.list[SupplierProductResponse]:
        return [await self._to_response(tenant_id, row) for row in rows]

    async def _to_response(self, tenant_id: UUID, row: SupplierProduct) -> SupplierProductResponse:
        supplier_name: str | None = None
        try:
            supplier_name = (await self.suppliers.get(tenant_id, row.supplier_id)).name
        except ResourceNotFoundError:
            supplier_name = None
        product_sku: str | None = None
        product_name: str | None = None
        if row.product_id is not None:
            try:
                product = await self.products.get(tenant_id, row.product_id)
                product_sku = product.sku
                product_name = product.name
            except ResourceNotFoundError:
                product_sku = None
                product_name = None
        currency_code: str | None = None
        try:
            currency_code = (await self.currencies.get(tenant_id, row.currency_id)).code
        except ResourceNotFoundError:
            currency_code = None
        return SupplierProductResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            supplier_id=row.supplier_id,
            supplier_name=supplier_name,
            product_id=row.product_id,
            product_sku=product_sku,
            product_name=product_name,
            is_mapped=row.product_id is not None,
            supplier_sku=row.supplier_sku,
            supplier_item_name=row.supplier_item_name,
            supplier_description=row.supplier_description,
            price=row.price,
            currency_id=row.currency_id,
            currency_code=currency_code,
            price_updated_at=row.price_updated_at,
            is_preferred=row.is_preferred,
            is_preferred_supplier=row.is_preferred_supplier,
            notes=row.notes,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _require(self, tenant_id: UUID, supplier_product_id: UUID) -> SupplierProduct:
        row = await self.repo.get(tenant_id, supplier_product_id)
        if row is None:
            raise ResourceNotFoundError("Supplier product not found")
        return row
