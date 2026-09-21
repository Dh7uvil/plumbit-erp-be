"""Email template rendering tests."""

from decimal import Decimal

from app.core.enums import DunningTemplateKey
from app.integrations.email.templates import render_password_reset, render_payment_reminder


def test_render_password_reset_includes_link() -> None:
    subject, text, html = render_password_reset(
        reset_url="https://app.test/reset-password?token=abc",
        expires_minutes=60,
        tenant_name="Acme",
    )
    assert "Acme" in subject
    assert "https://app.test/reset-password?token=abc" in text
    assert "reset-password" in html


def test_render_payment_reminder_overdue() -> None:
    subject, text, _html = render_payment_reminder(
        template_key=DunningTemplateKey.PAYMENT_OVERDUE,
        tenant_name="Acme",
        customer_name="Beta LLC",
        invoice_number="INV-001",
        due_date="2026-01-01",
        balance_due=Decimal("150.50"),
        currency_code="AED",
    )
    assert "INV-001" in subject
    assert "AED 150.50" in text
    assert "Beta LLC" in text
