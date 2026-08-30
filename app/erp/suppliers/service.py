"""Supplier use cases on the shared party tables."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.crm.customers.schemas import CustomerResponse
from app.crm.customers.service import SUPPLIER_PARTY_ROLE, CustomerService
from app.erp.suppliers.schemas import (
    SupplierCreate,
    SupplierExtraAddressCreate,
    SupplierExtraAddressResponse,
    SupplierResponse,
    SupplierUpdate,
)


class SupplierService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._parties = CustomerService(session, role=SUPPLIER_PARTY_ROLE)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        tax_treatment: str | None = None,
        currency_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[SupplierResponse], int]:
        rows, total = await self._parties.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            tax_treatment=tax_treatment,
            currency_id=currency_id,
            is_active=is_active,
        )
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, supplier_id: UUID) -> SupplierResponse:
        return self._to_response(await self._parties.get(tenant_id, supplier_id))

    async def create(
        self, tenant_id: UUID, payload: SupplierCreate, *, actor_user_id: UUID
    ) -> SupplierResponse:
        return self._to_response(
            await self._parties.create(tenant_id, payload, actor_user_id=actor_user_id)
        )

    async def update(
        self, tenant_id: UUID, supplier_id: UUID, payload: SupplierUpdate, *, actor_user_id: UUID
    ) -> SupplierResponse:
        return self._to_response(
            await self._parties.update(tenant_id, supplier_id, payload, actor_user_id=actor_user_id)
        )

    async def delete(
        self, tenant_id: UUID, supplier_id: UUID, *, actor_user_id: UUID
    ) -> SupplierResponse:
        return self._to_response(
            await self._parties.delete(tenant_id, supplier_id, actor_user_id=actor_user_id)
        )

    async def add_extra_address(
        self,
        tenant_id: UUID,
        supplier_id: UUID,
        payload: SupplierExtraAddressCreate,
        *,
        actor_user_id: UUID,
    ) -> SupplierExtraAddressResponse:
        row = await self._parties.add_extra_address(
            tenant_id, supplier_id, payload, actor_user_id=actor_user_id
        )
        return SupplierExtraAddressResponse.model_validate(row.model_dump())

    async def delete_extra_address(
        self,
        tenant_id: UUID,
        supplier_id: UUID,
        extra_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> SupplierExtraAddressResponse:
        row = await self._parties.delete_extra_address(
            tenant_id, supplier_id, extra_id, actor_user_id=actor_user_id
        )
        return SupplierExtraAddressResponse.model_validate(row.model_dump())

    @staticmethod
    def _to_response(row: CustomerResponse) -> SupplierResponse:
        return SupplierResponse.model_validate(row.model_dump())
