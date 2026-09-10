"""Registry of probes that block sales-invoice void when a child document is live."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

SalesInvoiceDependentProbe = Callable[[AsyncSession, UUID, UUID], Awaitable[bool]]

_PROBES: dict[str, SalesInvoiceDependentProbe] = {}


def register(name: str, probe: SalesInvoiceDependentProbe) -> None:
    """Register or replace a named sales-invoice-dependent probe."""

    _PROBES[name] = probe


def registered_probes() -> tuple[SalesInvoiceDependentProbe, ...]:
    """Return probes in registration-name order."""

    return tuple(_PROBES[name] for name in _PROBES)


def clear() -> None:
    """Remove every probe. Intended for tests."""

    _PROBES.clear()
