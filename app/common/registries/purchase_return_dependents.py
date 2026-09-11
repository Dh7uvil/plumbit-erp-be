"""Registry of probes that block purchase-return cancel when a child document is live."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

PurchaseReturnDependentProbe = Callable[[AsyncSession, UUID, UUID], Awaitable[bool]]

_PROBES: dict[str, PurchaseReturnDependentProbe] = {}


def register(name: str, probe: PurchaseReturnDependentProbe) -> None:
    """Register or replace a named purchase-return-dependent probe."""

    _PROBES[name] = probe


def registered_probes() -> tuple[PurchaseReturnDependentProbe, ...]:
    """Return probes in registration-name order."""

    return tuple(_PROBES[name] for name in _PROBES)


def clear() -> None:
    """Remove every probe. Intended for tests."""

    _PROBES.clear()
