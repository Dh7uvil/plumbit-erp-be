"""Contact use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import CRM_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction
from app.core.exceptions import ResourceNotFoundError
from app.crm.contacts.models import Contact
from app.crm.contacts.repository import ContactRepository
from app.crm.contacts.schemas import ContactCreate, ContactResponse, ContactUpdate
from app.crm.customers.service import CustomerService
from app.db.session import transaction


class ContactService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ContactRepository(session)
        self.customers = CustomerService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        customer_id: UUID | None = None,
        is_primary: bool | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[ContactResponse], int]:
        filters: dict[str, object] = {}
        if customer_id is not None:
            filters["customer_id"] = customer_id
        if is_primary is not None:
            filters["is_primary"] = is_primary
        if is_active is not None:
            filters["is_active"] = is_active
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [ContactResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, contact_id: UUID) -> ContactResponse:
        return ContactResponse.model_validate(await self._require(tenant_id, contact_id))

    async def get_primary(self, tenant_id: UUID, customer_id: UUID) -> ContactResponse | None:
        row = await self.repo.get_primary(tenant_id, customer_id)
        if row is None:
            return None
        return ContactResponse.model_validate(row)

    async def create(
        self, tenant_id: UUID, payload: ContactCreate, *, actor_user_id: UUID
    ) -> ContactResponse:
        async with transaction(self.session):
            await self.customers.require_party(tenant_id, payload.customer_id)
            if payload.is_primary:
                await self.repo.clear_other_primaries(tenant_id, payload.customer_id)
            row = await self.repo.create(
                tenant_id,
                {
                    **payload.model_dump(),
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=CRM_MODULE,
                entity_type="contact",
                entity_id=row.id,
                new_values=await self._contact_snapshot(tenant_id, row),
            )
            return ContactResponse.model_validate(row)

    async def update(
        self, tenant_id: UUID, contact_id: UUID, payload: ContactUpdate, *, actor_user_id: UUID
    ) -> ContactResponse:
        values = payload.model_dump(exclude_unset=True)
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, contact_id)
            old_values = await self._contact_snapshot(tenant_id, existing)
            if values.get("is_primary") is True:
                await self.repo.clear_other_primaries(
                    tenant_id, existing.customer_id, keep_id=contact_id
                )
            row = await self.repo.update(tenant_id, contact_id, values)
            if row is None:
                raise ResourceNotFoundError("Contact not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="contact",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._contact_snapshot(tenant_id, row),
            )
            return ContactResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, contact_id: UUID, *, actor_user_id: UUID
    ) -> ContactResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, contact_id)
            response = ContactResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, contact_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=CRM_MODULE,
                entity_type="contact",
                entity_id=contact_id,
                old_values=await self._contact_snapshot(tenant_id, row),
            )
            return response

    async def _contact_snapshot(self, tenant_id: UUID, row: Contact) -> dict[str, object]:
        customer = await self.customers.require_party(tenant_id, row.customer_id)
        return {
            "customer": customer.name,
            "name": row.name,
            "email": row.email,
            "phone": row.phone,
            "is_primary": row.is_primary,
            "is_active": row.is_active,
        }

    async def _require(self, tenant_id: UUID, contact_id: UUID) -> Contact:
        row = await self.repo.get(tenant_id, contact_id)
        if row is None:
            raise ResourceNotFoundError("Contact not found")
        return row
