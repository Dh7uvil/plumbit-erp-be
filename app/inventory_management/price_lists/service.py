"""Price-list use cases."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import INVENTORY_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money
from app.core.enums import AuditAction, PriceListType
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.db.session import transaction
from app.erp.exchange_rates.service import CurrencyService
from app.inventory_management.price_lists.models import PriceList, PriceListItem
from app.inventory_management.price_lists.repository import PriceListRepository
from app.inventory_management.price_lists.schemas import (
    PriceListCreate,
    PriceListItemResponse,
    PriceListItemUpsert,
    PriceListResponse,
    PriceListUpdate,
)
from app.inventory_management.products.service import ProductService


class PriceListService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PriceListRepository(session)
        self.currencies = CurrencyService(session)
        self.products = ProductService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        currency_id: UUID | None = None,
        list_type: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[PriceListResponse], int]:
        filters: dict[str, object] = {}
        if currency_id is not None:
            filters["currency_id"] = currency_id
        if list_type is not None:
            filters["list_type"] = list_type
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        responses = [await self._to_response(tenant_id, row) for row in rows]
        return responses, total

    async def get(self, tenant_id: UUID, price_list_id: UUID) -> PriceListResponse:
        row = await self._require(tenant_id, price_list_id)
        return await self._to_response(tenant_id, row)

    async def require_id(self, tenant_id: UUID, price_list_id: UUID) -> UUID:
        await self._require(tenant_id, price_list_id)
        return price_list_id

    async def create(
        self, tenant_id: UUID, payload: PriceListCreate, *, actor_user_id: UUID
    ) -> PriceListResponse:
        async with transaction(self.session):
            await self.currencies.require_id(tenant_id, payload.currency_id)
            try:
                row = await self.repo.create(
                    tenant_id,
                    {
                        "name": payload.name,
                        "currency_id": payload.currency_id,
                        "list_type": payload.list_type.value,
                        "percent": payload.percent,
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A price list with this name already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="price_list",
                entity_id=row.id,
                new_values=await self._price_list_snapshot(tenant_id, row),
            )
            return await self._to_response(tenant_id, row)

    async def update(
        self, tenant_id: UUID, price_list_id: UUID, payload: PriceListUpdate, *, actor_user_id: UUID
    ) -> PriceListResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, price_list_id)
            old_values = await self._price_list_snapshot(tenant_id, existing)
            try:
                row = await self.repo.update(tenant_id, price_list_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError("A price list with this name already exists") from exc
            if row is None:
                raise ResourceNotFoundError("Price list not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="price_list",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._price_list_snapshot(tenant_id, row),
            )
            return await self._to_response(tenant_id, row)

    async def delete(
        self, tenant_id: UUID, price_list_id: UUID, *, actor_user_id: UUID
    ) -> PriceListResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, price_list_id)
            response = await self._to_response(tenant_id, row)
            await self.repo.soft_delete(tenant_id, price_list_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="price_list",
                entity_id=price_list_id,
                old_values=await self._price_list_snapshot(tenant_id, row),
            )
            return response

    async def upsert_item(
        self,
        tenant_id: UUID,
        price_list_id: UUID,
        payload: PriceListItemUpsert,
        *,
        actor_user_id: UUID,
    ) -> PriceListItemResponse:
        async with transaction(self.session):
            await self._require(tenant_id, price_list_id)
            await self.products.get(tenant_id, payload.product_id)
            existing = await self.repo.get_item(tenant_id, price_list_id, payload.product_id)
            old_values = (
                await self._price_list_item_snapshot(tenant_id, existing)
                if existing is not None
                else None
            )
            item = await self.repo.upsert_item(
                tenant_id,
                price_list_id=price_list_id,
                product_id=payload.product_id,
                rate=payload.rate,
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="price_list",
                entity_id=price_list_id,
                old_values=old_values,
                new_values=await self._price_list_item_snapshot(tenant_id, item),
            )
            return PriceListItemResponse.model_validate(item)

    async def delete_item(
        self,
        tenant_id: UUID,
        price_list_id: UUID,
        product_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> PriceListItemResponse:
        async with transaction(self.session):
            await self._require(tenant_id, price_list_id)
            item = await self.repo.delete_item(tenant_id, price_list_id, product_id)
            if item is None:
                raise ResourceNotFoundError("Price list item not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="price_list",
                entity_id=price_list_id,
                old_values=await self._price_list_item_snapshot(tenant_id, item),
            )
            return PriceListItemResponse.model_validate(item)

    async def resolve_rate(
        self,
        tenant_id: UUID,
        *,
        product_id: UUID,
        selling_rate: Decimal,
        price_list_id: UUID | None,
        line_override: Decimal | None,
    ) -> Decimal:
        """line override → customer price list → product selling rate."""

        if line_override is not None:
            return quantize_money(line_override)
        if price_list_id is None:
            return quantize_money(selling_rate)
        price_list = await self._require(tenant_id, price_list_id)
        if price_list.list_type == PriceListType.CUSTOM_RATES.value:
            item = await self.repo.get_item(tenant_id, price_list_id, product_id)
            if item is not None:
                return quantize_money(item.rate)
            return quantize_money(selling_rate)
        percent = price_list.percent or Decimal("0")
        return quantize_money(selling_rate * (Decimal("1") + percent / Decimal("100")))

    async def _price_list_snapshot(self, tenant_id: UUID, row: PriceList) -> dict[str, object]:
        currency = await self.currencies.get(tenant_id, row.currency_id)
        return {
            "name": row.name,
            "currency": currency.code,
            "list_type": row.list_type,
            "percent": row.percent,
            "is_active": row.is_active,
        }

    async def _price_list_item_snapshot(
        self, tenant_id: UUID, item: PriceListItem
    ) -> dict[str, object]:
        product = await self.products.get(tenant_id, item.product_id)
        return {
            "product": product.sku,
            "rate": item.rate,
        }

    async def _to_response(self, tenant_id: UUID, row: PriceList) -> PriceListResponse:
        items = await self.repo.list_items(tenant_id, row.id)
        return PriceListResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            currency_id=row.currency_id,
            list_type=PriceListType(row.list_type),
            percent=row.percent,
            is_active=row.is_active,
            items=[PriceListItemResponse.model_validate(item) for item in items],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _require(self, tenant_id: UUID, price_list_id: UUID) -> PriceList:
        row = await self.repo.get(tenant_id, price_list_id)
        if row is None:
            raise ResourceNotFoundError("Price list not found")
        return row
