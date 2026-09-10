"""Registry of probes that block delivery-note cancel when a child document is live."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

DeliveryNoteDependentProbe = Callable[[AsyncSession, UUID, UUID], Awaitable[bool]]

_PROBES: dict[str, DeliveryNoteDependentProbe] = {}


def register(name: str, probe: DeliveryNoteDependentProbe) -> None:
    """Register or replace a named delivery-note-dependent probe."""

    _PROBES[name] = probe


def registered_probes() -> tuple[DeliveryNoteDependentProbe, ...]:
    """Return probes in registration-name order."""

    return tuple(_PROBES[name] for name in _PROBES)


def clear() -> None:
    """Remove every probe. Intended for tests."""

    _PROBES.clear()
