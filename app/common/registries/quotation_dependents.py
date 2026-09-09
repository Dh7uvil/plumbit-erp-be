"""Registry of probes that block quotation revise/convert when a child document is live."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

QuotationDependentProbe = Callable[[AsyncSession, UUID, UUID], Awaitable[bool]]

_PROBES: dict[str, QuotationDependentProbe] = {}


def register(name: str, probe: QuotationDependentProbe) -> None:
    """Register or replace a named quotation-dependent probe."""

    _PROBES[name] = probe


def registered_probes() -> tuple[QuotationDependentProbe, ...]:
    """Return probes in registration-name order."""

    return tuple(_PROBES[name] for name in _PROBES)


def clear() -> None:
    """Remove every probe. Intended for tests."""

    _PROBES.clear()
