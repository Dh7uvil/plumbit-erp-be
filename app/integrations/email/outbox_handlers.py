"""Outbox handlers that deliver email through SES."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select

from app.auth.models import Tenant
from app.common.outbox.models import OutboxEvent
from app.core.config import get_settings
from app.core.exceptions import IntegrationError
from app.db.session import async_session_factory
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
