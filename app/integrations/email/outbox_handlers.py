"""Outbox handlers that deliver email and in-app notifications."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import select

from app.auth.models import Employee, Tenant, User
from app.common.notification_preferences.service import NotificationPreferenceService
from app.common.notifications.service import NotificationService
from app.common.outbox.models import OutboxEvent
from app.core.config import get_settings
from app.core.exceptions import IntegrationError
from app.db.session import async_session_factory, transaction
from app.erp.accounting.cheques.models import Cheque
from app.erp.quotation.models import Quotation
from app.erp.sales_invoices.models import SalesInvoice
from app.integrations.email.client import get_optional_email_transport
from app.integrations.email.schemas import EmailMessage
from app.integrations.email.templates import render_password_reset

logger = logging.getLogger(__name__)

EMAIL_EVENT_TYPES = frozenset(
    {
        "identity.password_reset.requested",
        "sales.payment_reminder.requested",
    }
)

NOTIFICATION_EVENT_TYPES = frozenset(
    {
        "tasks.assigned",
        "sales.quotation.revised",
        "sales.sales_invoice.posted",
        "cheque.due",
    }
)


async def handle_password_reset_requested(event: OutboxEvent) -> None:
    settings = get_settings()
    if not settings.feature_email_enabled:
        logger.info(
            "email_skipped_feature_disabled",
            extra={"event_type": event.event_type, "aggregate_id": str(event.aggregate_id)},
        )
        return
    transport = get_optional_email_transport()
    if transport is None:
        raise IntegrationError("Email delivery is enabled but SES is not configured")
    payload = event.payload or {}
    email = payload.get("email")
    reset_token = payload.get("reset_token")
    if not isinstance(email, str) or not isinstance(reset_token, str):
        raise IntegrationError("Invalid password reset outbox payload")
    if settings.public_app_url is None:
        raise IntegrationError("PUBLIC_APP_URL is required to send password reset emails")
    base = str(settings.public_app_url).rstrip("/")
    reset_url = f"{base}/reset-password?{urlencode({'token': reset_token})}"
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.id == event.tenant_id))
    tenant_name = tenant.name if tenant is not None else "Plumbit ERP"
    subject, text_body, html_body = render_password_reset(
        reset_url=reset_url,
        expires_minutes=settings.password_reset_ttl_minutes,
        tenant_name=tenant_name,
    )
    await transport.send(
        EmailMessage(to=email, subject=subject, text_body=text_body, html_body=html_body)
    )


async def handle_email_outbox_event(event: OutboxEvent) -> None:
    """Send a pre-rendered email from the outbox payload."""

    settings = get_settings()
    if not settings.feature_email_enabled:
        logger.info(
            "email_skipped_feature_disabled",
            extra={"event_type": event.event_type, "aggregate_id": str(event.aggregate_id)},
        )
        return
    transport = get_optional_email_transport()
    if transport is None:
        raise IntegrationError("Email delivery is enabled but SES is not configured")
    payload = event.payload or {}
    message = _message_from_payload(payload)
    await transport.send(message)


async def handle_task_assigned(event: OutboxEvent) -> None:
    payload = event.payload or {}
    assignee_id = _uuid_from_payload(payload, "assignee_id")
    if assignee_id is None:
        return
    task_number = payload.get("task_number", "")
    title = payload.get("title", "Task")
    body = f"You were assigned task {task_number}: {title}."
    await _deliver_notification(
        tenant_id=event.tenant_id,
        user_id=assignee_id,
        event=event.event_type,
        entity_type="task",
        entity_id=event.aggregate_id,
        title=f"Task assigned: {task_number}",
        body=body,
        email_subject=f"Task assigned: {task_number}",
        email_body=body,
    )


async def handle_quotation_revised(event: OutboxEvent) -> None:
    payload = event.payload or {}
    quote_number = payload.get("quote_number", "")
    revision_number = payload.get("revision_number", "")
    async with async_session_factory() as session:
        quotation = await session.scalar(
            select(Quotation).where(
                Quotation.tenant_id == event.tenant_id,
                Quotation.id == event.aggregate_id,
                Quotation.deleted_at.is_(None),
            )
        )
        user_id = await _quotation_recipient_user_id(session, event.tenant_id, quotation)
    if user_id is None:
        logger.info(
            "notification_skipped_no_recipient",
            extra={"event_type": event.event_type, "aggregate_id": str(event.aggregate_id)},
        )
        return
    body = f"Quotation {quote_number} was revised (revision {revision_number})."
    await _deliver_notification(
        tenant_id=event.tenant_id,
        user_id=user_id,
        event=event.event_type,
        entity_type="quotation",
        entity_id=event.aggregate_id,
        title=f"Quotation revised: {quote_number}",
        body=body,
        email_subject=f"Quotation revised: {quote_number}",
        email_body=body,
    )


async def handle_sales_invoice_posted(event: OutboxEvent) -> None:
    async with async_session_factory() as session:
        invoice = await session.scalar(
            select(SalesInvoice).where(
                SalesInvoice.tenant_id == event.tenant_id,
                SalesInvoice.id == event.aggregate_id,
                SalesInvoice.deleted_at.is_(None),
            )
        )
        if invoice is None:
            return
        user_id = invoice.created_by
        document_number = invoice.document_number
    if user_id is None:
        logger.info(
            "notification_skipped_no_recipient",
            extra={"event_type": event.event_type, "aggregate_id": str(event.aggregate_id)},
        )
        return
    body = f"Sales invoice {document_number} was posted."
    await _deliver_notification(
        tenant_id=event.tenant_id,
        user_id=user_id,
        event=event.event_type,
        entity_type="sales_invoice",
        entity_id=event.aggregate_id,
        title=f"Invoice posted: {document_number}",
        body=body,
        email_subject=f"Invoice posted: {document_number}",
        email_body=body,
    )


async def handle_cheque_due(event: OutboxEvent) -> None:
    payload = event.payload or {}
    user_id = _uuid_from_payload(payload, "user_id")
    if user_id is None:
        async with async_session_factory() as session:
            cheque = await session.scalar(
                select(Cheque).where(
                    Cheque.tenant_id == event.tenant_id,
                    Cheque.id == event.aggregate_id,
                    Cheque.deleted_at.is_(None),
                )
            )
            user_id = cheque.created_by if cheque is not None else None
    if user_id is None:
        logger.info(
            "notification_skipped_no_recipient",
            extra={"event_type": event.event_type, "aggregate_id": str(event.aggregate_id)},
        )
        return
    cheque_number = payload.get("cheque_number", "")
    due_date = payload.get("due_date", "")
    direction = payload.get("direction", "")
    amount = payload.get("amount", "")
    body = f"Cheque {cheque_number} ({direction}) for {amount} is due on {due_date}."
    await _deliver_notification(
        tenant_id=event.tenant_id,
        user_id=user_id,
        event=event.event_type,
        entity_type="cheque",
        entity_id=event.aggregate_id,
        title=f"Cheque due: {cheque_number}",
        body=body,
        email_subject=f"Cheque due: {cheque_number}",
        email_body=body,
    )


async def _deliver_notification(
    *,
    tenant_id: UUID,
    user_id: UUID,
    event: str,
    entity_type: str,
    entity_id: UUID | None,
    title: str,
    body: str,
    email_subject: str,
    email_body: str,
) -> None:
    async with async_session_factory() as session:
        prefs = await NotificationPreferenceService(session).get(tenant_id, user_id)

    if not prefs.in_app_enabled and not prefs.email_enabled:
        logger.info(
            "notification_skipped_preferences_disabled",
            extra={"event": event, "user_id": str(user_id), "tenant_id": str(tenant_id)},
        )
        return

    if prefs.in_app_enabled:
        async with async_session_factory() as session, transaction(session):
            await NotificationService(session).create(
                tenant_id,
                user_id,
                event=event,
                entity_type=entity_type,
                entity_id=entity_id,
                title=title,
                body=body,
            )

    if prefs.email_enabled:
        settings = get_settings()
        if not settings.feature_email_enabled:
            logger.info(
                "email_skipped_feature_disabled",
                extra={"event": event, "user_id": str(user_id)},
            )
            return
        transport = get_optional_email_transport()
        if transport is None:
            raise IntegrationError("Email delivery is enabled but SES is not configured")
        async with async_session_factory() as session:
            user = await session.scalar(
                select(User).where(User.tenant_id == tenant_id, User.id == user_id)
            )
        if user is None or not user.email:
            return
        await transport.send(
            EmailMessage(to=user.email, subject=email_subject, text_body=email_body)
        )


async def _quotation_recipient_user_id(
    session: Any, tenant_id: UUID, quotation: Quotation | None
) -> UUID | None:
    if quotation is None:
        return None
    if quotation.salesperson_id is not None:
        employee = await session.scalar(
            select(Employee).where(
                Employee.tenant_id == tenant_id,
                Employee.id == quotation.salesperson_id,
                Employee.deleted_at.is_(None),
            )
        )
        if employee is not None and employee.user_id is not None:
            return employee.user_id
    return quotation.created_by


def _uuid_from_payload(payload: dict[str, Any], key: str) -> UUID | None:
    raw = payload.get(key)
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def _message_from_payload(payload: dict[str, Any]) -> EmailMessage:
    try:
        return EmailMessage(
            to=payload["to"],
            subject=payload["subject"],
            text_body=payload["text_body"],
            html_body=payload.get("html_body"),
            reply_to=payload.get("reply_to"),
        )
    except KeyError as exc:
        raise IntegrationError(f"Invalid email outbox payload: missing {exc}") from exc
