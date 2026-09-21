"""Shared CRM polymorphic related-record validation."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CrmRelatedEntityType
from app.core.exceptions import ResourceNotFoundError, ValidationError


async def assert_related_entity_exists(
    session: AsyncSession,
    tenant_id: UUID,
    related_entity_type: CrmRelatedEntityType,
    related_entity_id: UUID,
) -> None:
    """Confirm the related CRM record exists in this tenant."""

    try:
        if related_entity_type is CrmRelatedEntityType.LEAD:
            from app.crm.leads.service import LeadService

            await LeadService(session).get(tenant_id, related_entity_id)
            return
        if related_entity_type is CrmRelatedEntityType.OPPORTUNITY:
            from app.crm.opportunities.service import OpportunityService

            await OpportunityService(session).get(tenant_id, related_entity_id)
            return
        if related_entity_type is CrmRelatedEntityType.CUSTOMER:
            from app.crm.customers.service import CustomerService

            await CustomerService(session).get(tenant_id, related_entity_id)
            return
        if related_entity_type is CrmRelatedEntityType.CONTACT:
            from app.crm.contacts.service import ContactService

            await ContactService(session).get(tenant_id, related_entity_id)
            return
    except ResourceNotFoundError as exc:
        raise ValidationError(f"Related {related_entity_type.value} was not found") from exc
    raise ValidationError("related_entity_type is not allowed")
