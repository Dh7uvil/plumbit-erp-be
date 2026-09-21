"""Built-in transactional email templates."""

from __future__ import annotations

from decimal import Decimal
from html import escape

from app.core.enums import DunningTemplateKey


def render_password_reset(
    *, reset_url: str, expires_minutes: int, tenant_name: str
) -> tuple[str, str, str]:
    subject = f"Reset your {tenant_name} password"
    text = (
        f"Use the link below to reset your password for {tenant_name}. "
        f"The link expires in {expires_minutes} minutes.\n\n"
        f"{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    html = (
        f"<p>Use the link below to reset your password for {escape(tenant_name)}. "
        f"The link expires in {expires_minutes} minutes.</p>"
        f'<p><a href="{escape(reset_url)}">Reset password</a></p>'
        "<p>If you did not request this, you can ignore this email.</p>"
    )
    return subject, text, html


def render_payment_reminder(
    *,
    template_key: DunningTemplateKey,
    tenant_name: str,
    customer_name: str,
    invoice_number: str,
    due_date: str,
    balance_due: Decimal,
    currency_code: str,
) -> tuple[str, str, str]:
    amount = f"{currency_code} {balance_due:.2f}"
    if template_key == DunningTemplateKey.PAYMENT_DUE_SOON:
        subject = f"Payment reminder: {invoice_number} due {due_date}"
        lead = f"This is a friendly reminder that invoice {invoice_number} is due on {due_date}."
    elif template_key == DunningTemplateKey.PAYMENT_ESCALATION:
        subject = f"Urgent: overdue invoice {invoice_number}"
        lead = (
            f"Invoice {invoice_number} for {customer_name} remains overdue. "
            f"The outstanding balance is {amount}."
        )
    else:
        subject = f"Overdue invoice {invoice_number}"
        lead = (
            f"Invoice {invoice_number} was due on {due_date}. "
            f"The outstanding balance is {amount}."
        )
    text = (
        f"Dear {customer_name},\n\n"
        f"{lead}\n\n"
        f"Outstanding balance: {amount}\n\n"
        f"Regards,\n{tenant_name}"
    )
    html = (
        f"<p>Dear {escape(customer_name)},</p>"
        f"<p>{escape(lead)}</p>"
        f"<p><strong>Outstanding balance:</strong> {escape(amount)}</p>"
        f"<p>Regards,<br>{escape(tenant_name)}</p>"
    )
    return subject, text, html
