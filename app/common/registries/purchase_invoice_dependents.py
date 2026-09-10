"""Registry of probes that block purchase-invoice void when a child document is live."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

PurchaseInvoiceDependentProbe = Callable[[AsyncSession, UUID, UUID], Awaitable[bool]]

_PROBES: dict[str, PurchaseInvoiceDependentProbe] = {}


def register(name: str, probe: PurchaseInvoiceDependentProbe) -> None:
    """Register or replace a named purchase-invoice-dependent probe."""

    _PROBES[name] = probe


def registered_probes() -> tuple[PurchaseInvoiceDependentProbe, ...]:
    """Return probes in registration-name order."""

    return tuple(_PROBES[name] for name in _PROBES)


def clear() -> None:
    """Remove every probe. Intended for tests."""

    _PROBES.clear()
