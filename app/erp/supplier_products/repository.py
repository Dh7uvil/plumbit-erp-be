"""Supplier product catalog queries."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.erp.supplier_products.models import SupplierProduct

_SORT_FIELDS = frozenset({"supplier_sku", "supplier_item_name", "created_at", "updated_at"})
_FILTER_FIELDS = frozenset(
    {
        "supplier_id",
        "product_id",
        "is_active",
        "is_preferred",
        "is_preferred_supplier",
    }
)
_SEARCH_FIELDS = frozenset({"supplier_sku", "supplier_item_name", "supplier_description"})


class SupplierProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            SupplierProduct,
            allowed_sort_fields=_SORT_FIELDS,
            allowed_filter_fields=_FILTER_FIELDS,
            search_fields=_SEARCH_FIELDS,
        )

    async def get(self, tenant_id: UUID, supplier_product_id: UUID) -> SupplierProduct | None:
        return await self._repo.get(tenant_id, supplier_product_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        extra_criteria: Sequence[ColumnElement[bool]] | None = None,
    ) -> tuple[Sequence[SupplierProduct], int]:
        return await self._repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
            extra_criteria=extra_criteria,
        )

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> SupplierProduct:
        return await self._repo.create(tenant_id, values)

    async def update(
        self,
        tenant_id: UUID,
        supplier_product_id: UUID,
        values: Mapping[str, object],
    ) -> SupplierProduct | None:
        return await self._repo.update(tenant_id, supplier_product_id, values)

    async def soft_delete(
        self, tenant_id: UUID, supplier_product_id: UUID
    ) -> SupplierProduct | None:
        return await self._repo.soft_delete(tenant_id, supplier_product_id)

    async def find_by_normalized_sku(
        self, tenant_id: UUID, supplier_id: UUID, sku: str
    ) -> SupplierProduct | None:
        statement = self._repo.base_query(tenant_id).where(
            SupplierProduct.supplier_id == supplier_id,
            SupplierProduct.supplier_sku_normalized == sku,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def find_by_normalized_skus(
        self, tenant_id: UUID, supplier_id: UUID, skus: Sequence[str]
    ) -> Sequence[SupplierProduct]:
        if not skus:
            return []
        statement = self._repo.base_query(tenant_id).where(
            SupplierProduct.supplier_id == supplier_id,
            SupplierProduct.supplier_sku_normalized.in_(list(skus)),
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def find_preferred(
        self, tenant_id: UUID, *, supplier_id: UUID, product_id: UUID
    ) -> SupplierProduct | None:
        statement = self._repo.base_query(tenant_id).where(
            SupplierProduct.supplier_id == supplier_id,
            SupplierProduct.product_id == product_id,
            SupplierProduct.is_preferred.is_(True),
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def find_preferred_supplier(
        self, tenant_id: UUID, product_id: UUID
    ) -> SupplierProduct | None:
        statement = self._repo.base_query(tenant_id).where(
            SupplierProduct.product_id == product_id,
            SupplierProduct.is_preferred_supplier.is_(True),
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def demote_preferred(
        self,
        tenant_id: UUID,
        *,
        supplier_id: UUID,
        product_id: UUID,
        except_id: UUID | None = None,
    ) -> None:
        criteria: list[ColumnElement[bool]] = [
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.supplier_id == supplier_id,
            SupplierProduct.product_id == product_id,
            SupplierProduct.is_preferred.is_(True),
            SupplierProduct.deleted_at.is_(None),
        ]
        if except_id is not None:
            criteria.append(SupplierProduct.id != except_id)
        await self.session.execute(
            update(SupplierProduct).where(*criteria).values(is_preferred=False)
        )
        self.session.expire_all()

    async def demote_preferred_supplier(
        self,
        tenant_id: UUID,
        *,
        product_id: UUID,
        except_id: UUID | None = None,
    ) -> None:
        criteria: list[ColumnElement[bool]] = [
            SupplierProduct.tenant_id == tenant_id,
            SupplierProduct.product_id == product_id,
            SupplierProduct.is_preferred_supplier.is_(True),
            SupplierProduct.deleted_at.is_(None),
        ]
        if except_id is not None:
            criteria.append(SupplierProduct.id != except_id)
        await self.session.execute(
            update(SupplierProduct).where(*criteria).values(is_preferred_supplier=False)
        )
        self.session.expire_all()
