"""Commercial document policy settings stored on the tenant row."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.auth.models import Tenant


class InvoicePolicy(StrEnum):
    """When sales invoices may be raised against an order."""

    BILL_AHEAD = "bill_ahead"
    DELIVERED_ONLY = "delivered_only"


class _CommercialTenant(Protocol):
    invoice_policy: str
    returns_reopen_delivery: bool


@dataclass(frozen=True, slots=True)
class TenantCommercialSettings:
    """Defaults preserve current production behavior."""

    invoice_policy: InvoicePolicy = InvoicePolicy.BILL_AHEAD
    returns_reopen_delivery: bool = False


def commercial_settings_from_tenant(tenant: Tenant | _CommercialTenant) -> TenantCommercialSettings:
    """Read commercial settings from a tenant ORM row or protocol-compatible object."""
    raw_policy = getattr(tenant, "invoice_policy", None) or InvoicePolicy.BILL_AHEAD.value
    try:
        policy = InvoicePolicy(raw_policy)
    except ValueError:
        policy = InvoicePolicy.BILL_AHEAD
    return TenantCommercialSettings(
        invoice_policy=policy,
        returns_reopen_delivery=bool(getattr(tenant, "returns_reopen_delivery", False)),
    )
