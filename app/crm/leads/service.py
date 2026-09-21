"""Lead use cases."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    CRM_MODULE,
    LEAD_ASSIGN,
    LEAD_CONVERT,
    LEAD_DELETE,
    LEAD_UPDATE,
)
from app.auth.models import User
from app.common.idempotency.service import IdempotencyService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction, LeadStatus
from app.core.exceptions import DocumentStaleError, ResourceNotFoundError, ValidationError
from app.core.permissions import has_permission
from app.crm.contacts.schemas import ContactCreate
from app.crm.contacts.service import ContactService
from app.crm.customers.schemas import CustomerCreate
from app.crm.customers.service import CustomerService
from app.crm.lead_sources.service import LeadSourceService
from app.crm.leads.codes import allocate_lead_number
from app.crm.leads.models import Lead
from app.crm.leads.repository import LeadRepository
from app.crm.leads.schemas import (
    LeadAssign,
    LeadConvert,
    LeadConvertResponse,
    LeadCreate,
    LeadResponse,
    LeadStatusChange,
    LeadUpdate,
)
from app.crm.leads.workflow import (
    allowed_status_targets,
    assert_editable,
    assert_status_transition,
)
from app.crm.opportunities.schemas import OpportunityCreate
from app.crm.opportunities.service import OpportunityService
from app.db.session import transaction
from app.erp.exchange_rates.service import CurrencyService


class LeadService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
        repo: LeadRepository | None = None,
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = repo or LeadRepository(session)
        self.lead_sources = LeadSourceService(session)
        self.customers = CustomerService(session)
        self.contacts = ContactService(session)
        self.opportunities = OpportunityService(session, actor_permissions=actor_permissions)
        self.currencies = CurrencyService(session)
        self.idempotency = IdempotencyService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        source_id: UUID | None = None,
        owner_id: UUID | None = None,
        rating: str | None = None,
    ) -> tuple[builtins.list[LeadResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if source_id is not None:
            filters["source_id"] = source_id
        if owner_id is not None:
            filters["owner_id"] = owner_id
        if rating is not None:
            filters["rating"] = rating
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, lead_id: UUID) -> LeadResponse:
        return self._to_response(await self._require(tenant_id, lead_id))

    async def create(
        self, tenant_id: UUID, payload: LeadCreate, *, actor_user_id: UUID
    ) -> LeadResponse:
        async with transaction(self.session):
            if payload.source_id is not None:
                await self.lead_sources.require_id(tenant_id, payload.source_id)
            if payload.owner_id is not None:
                await self._require_owner(tenant_id, payload.owner_id)
            if payload.currency_id is not None:
                await self.currencies.require_id(tenant_id, payload.currency_id)
            lead_number = await allocate_lead_number(self.session, tenant_id)
            row = await self.repo.create(
                tenant_id,
                {
                    **payload.model_dump(),
                    "lead_number": lead_number,
                    "status": LeadStatus.NEW.value,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=CRM_MODULE,
                entity_type="lead",
                entity_id=row.id,
                new_values=await self._snapshot(row),
            )
            return self._to_response(row)

    async def update(
        self,
        tenant_id: UUID,
        lead_id: UUID,
        payload: LeadUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> LeadResponse:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require(tenant_id, lead_id, for_update=True)
            assert_editable(LeadStatus(existing.status))
            self._assert_version(existing, expected_version)
            merged = self._merge_update(existing, payload)
            if merged.source_id is not None:
                await self.lead_sources.require_id(tenant_id, merged.source_id)
            if merged.owner_id is not None:
                await self._require_owner(tenant_id, merged.owner_id)
            if merged.currency_id is not None:
                await self.currencies.require_id(tenant_id, merged.currency_id)
            old_values = await self._snapshot(existing)
            values["version"] = existing.version + 1
            row = await self.repo.update(tenant_id, lead_id, values)
            if row is None:
                raise ResourceNotFoundError("Lead not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="lead",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(row),
            )
            return self._to_response(row)

    async def assign(
        self,
        tenant_id: UUID,
        lead_id: UUID,
        payload: LeadAssign,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> LeadResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, lead_id, for_update=True)
            assert_editable(LeadStatus(row.status))
            self._assert_version(row, expected_version)
            await self._require_owner(tenant_id, payload.owner_id)
            old_values = await self._snapshot(row)
            updated = await self.repo.update(
                tenant_id,
                lead_id,
                {
                    "owner_id": payload.owner_id,
                    "version": row.version + 1,
                    "updated_by": actor_user_id,
                },
            )
            if updated is None:
                raise ResourceNotFoundError("Lead not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="lead",
                entity_id=updated.id,
                old_values=old_values,
                new_values=await self._snapshot(updated),
            )
            return self._to_response(updated)

    async def change_status(
        self,
        tenant_id: UUID,
        lead_id: UUID,
        payload: LeadStatusChange,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> LeadResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, lead_id, for_update=True)
            current = LeadStatus(row.status)
            self._assert_version(row, expected_version)
            assert_status_transition(current, payload.status)
            old_values = await self._snapshot(row)
            updated = await self.repo.update(
                tenant_id,
                lead_id,
                {
                    "status": payload.status.value,
                    "version": row.version + 1,
                    "updated_by": actor_user_id,
                },
            )
            if updated is None:
                raise ResourceNotFoundError("Lead not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="lead",
                entity_id=updated.id,
                old_values=old_values,
                new_values=await self._snapshot(updated),
            )
            return self._to_response(updated)

    async def convert(
        self,
        tenant_id: UUID,
        lead_id: UUID,
        payload: LeadConvert,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> LeadConvertResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return LeadConvertResponse.model_validate(replay)

            row = await self._require(tenant_id, lead_id, for_update=True)
            if LeadStatus(row.status) == LeadStatus.CONVERTED:
                raise ValidationError("Lead has already been converted")
            if LeadStatus(row.status) == LeadStatus.LOST:
                raise ValidationError("Lead cannot be converted")
            self._assert_version(row, expected_version)

            if payload.customer_id is not None:
                await self.customers.require_party(tenant_id, payload.customer_id)
                customer_id = payload.customer_id
            else:
                assert payload.new_customer is not None
                created_customer = await self.customers.create_record(
                    tenant_id,
                    CustomerCreate(
                        name=payload.new_customer.name,
                        tax_treatment=payload.new_customer.tax_treatment,
                        currency_id=payload.new_customer.currency_id,
                        trn=payload.new_customer.trn,
                    ),
                    actor_user_id=actor_user_id,
                )
                customer_id = created_customer.id

            created_contact = await self.contacts.create_record(
                tenant_id,
                ContactCreate(
                    customer_id=customer_id,
                    name=payload.contact.name,
                    email=payload.contact.email,
                    phone=payload.contact.phone,
                    is_primary=payload.contact.is_primary,
                ),
                actor_user_id=actor_user_id,
            )

            opportunity_id: UUID | None = None
            opportunity_payload = payload.opportunity
            if opportunity_payload is not None and opportunity_payload.create:
                opportunity_name = opportunity_payload.name or self._default_opportunity_name(row)
                amount = opportunity_payload.amount
                currency_id = opportunity_payload.currency_id
                if amount is None and row.estimated_value is not None:
                    amount = row.estimated_value
                    currency_id = currency_id or row.currency_id
                created_opportunity = await self.opportunities.create_record(
                    tenant_id,
                    OpportunityCreate(
                        name=opportunity_name,
                        customer_id=customer_id,
                        contact_id=created_contact.id,
                        pipeline_id=opportunity_payload.pipeline_id,
                        stage_id=opportunity_payload.stage_id,
                        amount=amount,
                        currency_id=currency_id,
                        expected_close_date=opportunity_payload.expected_close_date,
                        owner_id=opportunity_payload.owner_id or row.owner_id,
                        source_id=row.source_id,
                        lead_id=lead_id,
                    ),
                    actor_user_id=actor_user_id,
                )
                opportunity_id = created_opportunity.id

            now = datetime.now(UTC)
            old_values = await self._snapshot(row)
            updated = await self.repo.update(
                tenant_id,
                lead_id,
                {
                    "status": LeadStatus.CONVERTED.value,
                    "converted_customer_id": customer_id,
                    "converted_contact_id": created_contact.id,
                    "converted_opportunity_id": opportunity_id,
                    "converted_at": now,
                    "version": row.version + 1,
                    "updated_by": actor_user_id,
                },
            )
            if updated is None:
                raise ResourceNotFoundError("Lead not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=CRM_MODULE,
                entity_type="lead",
                entity_id=updated.id,
                old_values=old_values,
                new_values=await self._snapshot(updated),
            )
            response = LeadConvertResponse(
                lead=self._to_response(updated),
                customer_id=customer_id,
                contact_id=created_contact.id,
                opportunity_id=opportunity_id,
            )
            await self.idempotency.store(
                tenant_id,
                idempotency_key,
                response.model_dump(mode="json"),
            )
            return response

    async def delete(
        self, tenant_id: UUID, lead_id: UUID, *, actor_user_id: UUID
    ) -> LeadResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, lead_id)
            assert_editable(LeadStatus(row.status))
            response = self._to_response(row)
            await self.repo.soft_delete(tenant_id, lead_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=CRM_MODULE,
                entity_type="lead",
                entity_id=lead_id,
                old_values=await self._snapshot(row),
            )
            return response

    def _available_actions(self, status: LeadStatus) -> builtins.list[str]:
        actions: builtins.list[str] = []
        if status in {LeadStatus.CONVERTED, LeadStatus.LOST}:
            return actions
        if has_permission(self.actor_permissions, LEAD_ASSIGN):
            actions.append("assign")
        for target in allowed_status_targets(status):
            actions.append(f"set_status:{target.value}")
        if has_permission(self.actor_permissions, LEAD_UPDATE):
            actions.append("update")
        if has_permission(self.actor_permissions, LEAD_DELETE):
            actions.append("delete")
        if has_permission(self.actor_permissions, LEAD_CONVERT):
            actions.append("convert")
        return actions

    def _to_response(self, row: Lead) -> LeadResponse:
        status = LeadStatus(row.status)
        base = LeadResponse.model_validate(row)
        return base.model_copy(
            update={
                "status": status,
                "available_actions": self._available_actions(status),
            }
        )

    def _assert_version(self, row: Lead, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _require(
        self, tenant_id: UUID, lead_id: UUID, *, for_update: bool = False
    ) -> Lead:
        row = await self.repo.get(tenant_id, lead_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Lead not found")
        return row

    async def _require_owner(self, tenant_id: UUID, owner_id: UUID) -> None:
        statement = select(User.id).where(User.tenant_id == tenant_id, User.id == owner_id)
        result = await self.session.execute(statement)
        if result.scalar_one_or_none() is None:
            raise ValidationError("Owner not found")

    async def _snapshot(self, row: Lead) -> dict[str, object]:
        return {
            "lead_number": row.lead_number,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "company_name": row.company_name,
            "email": row.email,
            "phone": row.phone,
            "title": row.title,
            "status": row.status,
            "rating": row.rating,
            "source_id": str(row.source_id) if row.source_id else None,
            "owner_id": str(row.owner_id) if row.owner_id else None,
            "estimated_value": (
                str(row.estimated_value) if row.estimated_value is not None else None
            ),
            "currency_id": str(row.currency_id) if row.currency_id else None,
            "notes": row.notes,
            "version": row.version,
        }

    def _default_opportunity_name(self, row: Lead) -> str:
        if row.company_name:
            return row.company_name.strip()
        parts = [part for part in (row.first_name, row.last_name) if part]
        if parts:
            return " ".join(parts)
        return row.lead_number

    def _merge_update(self, existing: Lead, payload: LeadUpdate) -> LeadCreate:
        data = {
            "first_name": existing.first_name,
            "last_name": existing.last_name,
            "company_name": existing.company_name,
            "email": existing.email,
            "phone": existing.phone,
            "title": existing.title,
            "rating": existing.rating,
            "source_id": existing.source_id,
            "owner_id": existing.owner_id,
            "estimated_value": existing.estimated_value,
            "currency_id": existing.currency_id,
            "notes": existing.notes,
        }
        data.update(payload.model_dump(exclude_unset=True, exclude={"version"}))
        return LeadCreate.model_validate(data)
