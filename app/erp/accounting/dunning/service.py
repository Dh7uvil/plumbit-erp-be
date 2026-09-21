"""Payment reminder rules and delivery."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ACCOUNTING_MODULE
from app.auth.models import Tenant
from app.common.outbox.service import OutboxService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AuditAction, DunningTemplateKey, InvoiceDocumentStatus
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.crm.contacts.models import Contact
from app.crm.contacts.repository import ContactRepository
from app.crm.customers.models import Customer
from app.db.session import transaction
from app.erp.accounting.dunning.models import DunningRule
from app.erp.accounting.dunning.repository import DunningLogRepository, DunningRuleRepository
from app.erp.accounting.dunning.schemas import (
    DunningLogResponse,
    DunningRuleCreate,
    DunningRuleResponse,
    DunningRuleUpdate,
    SendPaymentReminderResponse,
)
from app.erp.exchange_rates.models import Currency
from app.erp.sales_invoices.models import SalesInvoice
from app.erp.sales_invoices.repository import SalesInvoiceRepository
from app.integrations.email.templates import render_payment_reminder

logger = logging.getLogger(__name__)
_ZERO = Decimal("0")


def _rule_snapshot(row: DunningRule) -> dict[str, object]:
    return {
        "name": row.name,
        "days_offset": row.days_offset,
        "template_key": row.template_key,
        "escalate": row.escalate,
        "description": row.description,
        "is_active": row.is_active,
    }


class DunningRuleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DunningRuleRepository(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[DunningRuleResponse], int]:
        filters = {"is_active": is_active} if is_active is not None else None
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )
        return [DunningRuleResponse.model_validate(row) for row in rows], total

    async def get(self, tenant_id: UUID, rule_id: UUID) -> DunningRuleResponse:
        return DunningRuleResponse.model_validate(await self._require_rule(tenant_id, rule_id))

    async def create(
        self, tenant_id: UUID, payload: DunningRuleCreate, *, actor_user_id: UUID
    ) -> DunningRuleResponse:
        async with transaction(self.session):
            try:
                values = payload.model_dump()
                values["template_key"] = payload.template_key.value
                row = await self.repo.create(
                    tenant_id,
                    {
                        **values,
                        "created_by": actor_user_id,
                        "updated_by": actor_user_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A dunning rule with this name already exists"
                ) from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ACCOUNTING_MODULE,
                entity_type="dunning_rule",
                entity_id=row.id,
                new_values=_rule_snapshot(row),
            )
            return DunningRuleResponse.model_validate(row)

    async def update(
        self,
        tenant_id: UUID,
        rule_id: UUID,
        payload: DunningRuleUpdate,
        *,
        actor_user_id: UUID,
    ) -> DunningRuleResponse:
        values = payload.model_dump(exclude_unset=True)
        if "template_key" in values and values["template_key"] is not None:
            template_key = values["template_key"]
            values["template_key"] = (
                template_key.value if hasattr(template_key, "value") else template_key
            )
        values["updated_by"] = actor_user_id
        async with transaction(self.session):
            existing = await self._require_rule(tenant_id, rule_id)
            old_values = _rule_snapshot(existing)
            try:
                row = await self.repo.update(tenant_id, rule_id, values)
            except IntegrityError as exc:
                raise DuplicateResourceError(
                    "A dunning rule with this name already exists"
                ) from exc
            if row is None:
                raise ResourceNotFoundError("Dunning rule not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="dunning_rule",
                entity_id=row.id,
                old_values=old_values,
                new_values=_rule_snapshot(row),
            )
            return DunningRuleResponse.model_validate(row)

    async def delete(
        self, tenant_id: UUID, rule_id: UUID, *, actor_user_id: UUID
    ) -> DunningRuleResponse:
        async with transaction(self.session):
            row = await self._require_rule(tenant_id, rule_id)
            response = DunningRuleResponse.model_validate(row)
            await self.repo.soft_delete(tenant_id, rule_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="dunning_rule",
                entity_id=rule_id,
                old_values=_rule_snapshot(row),
            )
            return response

    async def _require_rule(self, tenant_id: UUID, rule_id: UUID) -> DunningRule:
        row = await self.repo.get(tenant_id, rule_id)
        if row is None:
            raise ResourceNotFoundError("Dunning rule not found")
        return row


class DunningService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.rule_repo = DunningRuleRepository(session)
        self.log_repo = DunningLogRepository(session)
        self.invoice_repo = SalesInvoiceRepository(session)
        self.contact_repo = ContactRepository(session)
        self.outbox = OutboxService(session)

    async def list_logs(
        self, tenant_id: UUID, sales_invoice_id: UUID
    ) -> list[DunningLogResponse]:
        await self._require_invoice(tenant_id, sales_invoice_id)
        rows = await self.log_repo.list_for_invoice(tenant_id, sales_invoice_id)
        return [
            DunningLogResponse(
                id=log.id,
                tenant_id=log.tenant_id,
                sales_invoice_id=log.sales_invoice_id,
                dunning_rule_id=log.dunning_rule_id,
                dunning_rule_name=rule.name if rule is not None else None,
                channel=log.channel,
                recipient_email=log.recipient_email,
                sent_at=log.sent_at,
                created_by=log.created_by,
            )
            for log, rule in rows
        ]

    async def send_manual_reminder(
        self,
        tenant_id: UUID,
        sales_invoice_id: UUID,
        *,
        dunning_rule_id: UUID | None,
        actor_user_id: UUID,
    ) -> SendPaymentReminderResponse:
        async with transaction(self.session):
            invoice = await self._require_open_invoice(tenant_id, sales_invoice_id)
            rule = await self._resolve_rule(tenant_id, invoice, dunning_rule_id)
            return await self._send_for_invoice(
                tenant_id,
                invoice,
                rule,
                actor_user_id=actor_user_id,
                manual=True,
            )

    async def scan_tenant(self, tenant_id: UUID, *, as_of: date) -> int:
        sent = 0
        rules = await self.rule_repo.list_active(tenant_id)
        async with transaction(self.session):
            for rule in rules:
                target_due_date = as_of - timedelta(days=rule.days_offset)
                invoices = await self.log_repo.invoices_due_for_rule(
                    tenant_id, target_due_date=target_due_date
                )
                for invoice in invoices:
                    if invoice.due_date is None:
                        continue
                    existing = await self.log_repo.get_for_invoice_rule(
                        tenant_id,
                        sales_invoice_id=invoice.id,
                        dunning_rule_id=rule.id,
                    )
                    if existing is not None:
                        continue
                    try:
                        await self._send_for_invoice(
                            tenant_id,
                            invoice,
                            rule,
                            actor_user_id=None,
                            manual=False,
                        )
                        sent += 1
                    except ValidationError as exc:
                        logger.info(
                            "dunning_skipped",
                            extra={
                                "tenant_id": str(tenant_id),
                                "invoice_id": str(invoice.id),
                                "reason": str(exc),
                            },
                        )
        return sent

    async def _resolve_rule(
        self,
        tenant_id: UUID,
        invoice: SalesInvoice,
        dunning_rule_id: UUID | None,
    ) -> DunningRule:
        if dunning_rule_id is not None:
            row = await self.rule_repo.get(tenant_id, dunning_rule_id)
            if row is None or not row.is_active:
                raise ResourceNotFoundError("Dunning rule not found")
            return row
        if invoice.due_date is None:
            raise ValidationError("Invoice has no due date")
        today = datetime.now(UTC).date()
        days_from_due = (today - invoice.due_date).days
        rules = await self.rule_repo.list_active(tenant_id)
        matching = [rule for rule in rules if rule.days_offset == days_from_due]
        if not matching:
            fallback_key = (
                DunningTemplateKey.PAYMENT_OVERDUE
                if days_from_due > 0
                else DunningTemplateKey.PAYMENT_DUE_SOON
            )
            matching = [rule for rule in rules if rule.template_key == fallback_key.value]
        if not matching:
            raise ValidationError("No active dunning rule applies to this invoice")
        return matching[0]

    async def _send_for_invoice(
        self,
        tenant_id: UUID,
        invoice: SalesInvoice,
        rule: DunningRule,
        *,
        actor_user_id: UUID | None,
        manual: bool,
    ) -> SendPaymentReminderResponse:
        existing = await self.log_repo.get_for_invoice_rule(
            tenant_id,
            sales_invoice_id=invoice.id,
            dunning_rule_id=rule.id,
        )
        if existing is not None:
            raise DuplicateResourceError("This reminder was already sent for this rule")

        recipient = await self._recipient_email(tenant_id, invoice)
        if recipient is None:
            raise ValidationError("No billing email is available for this customer")

        tenant = await self.session.scalar(select(Tenant).where(Tenant.id == tenant_id))
        customer = await self.session.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.id == invoice.customer_id,
                Customer.deleted_at.is_(None),
            )
        )
        currency = await self.session.scalar(
            select(Currency).where(
                Currency.tenant_id == tenant_id,
                Currency.id == invoice.currency_id,
            )
        )
        tenant_name = tenant.name if tenant is not None else "Plumbit ERP"
        customer_name = customer.name if customer is not None else "Customer"
        currency_code = currency.code if currency is not None else ""
        due_label = invoice.due_date.isoformat() if invoice.due_date else "—"
        template_key = DunningTemplateKey(rule.template_key)
        subject, text_body, html_body = render_payment_reminder(
            template_key=template_key,
            tenant_name=tenant_name,
            customer_name=customer_name,
            invoice_number=invoice.document_number,
            due_date=due_label,
            balance_due=invoice.balance_due,
            currency_code=currency_code,
        )
        sent_at = datetime.now(UTC)
        try:
            log = await self.log_repo.create(
                tenant_id,
                {
                    "sales_invoice_id": invoice.id,
                    "dunning_rule_id": rule.id,
                    "channel": "EMAIL",
                    "recipient_email": recipient,
                    "sent_at": sent_at,
                    "created_by": actor_user_id,
                },
            )
        except IntegrityError as exc:
            raise DuplicateResourceError("This reminder was already sent for this rule") from exc

        dedupe = f"dunning:{invoice.id}:{rule.id}"
        await self.outbox.enqueue(
            tenant_id,
            event_type="sales.payment_reminder.requested",
            aggregate_type="sales_invoice",
            aggregate_id=invoice.id,
            payload={
                "to": recipient,
                "subject": subject,
                "text_body": text_body,
                "html_body": html_body,
                "dunning_log_id": str(log.id),
                "manual": manual,
            },
            dedupe_key=dedupe,
        )
        return SendPaymentReminderResponse(dunning_log_id=log.id, recipient_email=recipient)

    async def _recipient_email(self, tenant_id: UUID, invoice: SalesInvoice) -> str | None:
        contact: Contact | None = None
        if invoice.contact_id is not None:
            contact = await self.contact_repo.get(tenant_id, invoice.contact_id)
        if contact is None or not contact.email:
            contact = await self.contact_repo.get_primary(tenant_id, invoice.customer_id)
        if contact is None or not contact.email:
            return None
        return contact.email.strip()

    async def _require_invoice(self, tenant_id: UUID, invoice_id: UUID) -> SalesInvoice:
        row = await self.invoice_repo.get(tenant_id, invoice_id)
        if row is None:
            raise ResourceNotFoundError("Sales invoice not found")
        return row

    async def _require_open_invoice(self, tenant_id: UUID, invoice_id: UUID) -> SalesInvoice:
        row = await self._require_invoice(tenant_id, invoice_id)
        if row.status != InvoiceDocumentStatus.POSTED.value:
            raise ValidationError("Only posted invoices can receive payment reminders")
        if row.balance_due <= _ZERO:
            raise ValidationError("Invoice has no balance due")
        if row.due_date is None:
            raise ValidationError("Invoice has no due date")
        return row
