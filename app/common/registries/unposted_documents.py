"""Registry of probes that list unposted documents for period-lock preview."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas.pagination import PageParams


@dataclass(frozen=True, slots=True)
class UnpostedDocument:
    """One unposted document returned by a registered probe."""

    id: UUID
    document_type: str
    document_number: str
    document_date: date
    status: str


UnpostedProbe = Callable[
    [AsyncSession, UUID, date, PageParams],
    Awaitable[tuple[list[UnpostedDocument], int]],
]

_PROBES: dict[str, UnpostedProbe] = {}


def register(name: str, probe: UnpostedProbe) -> None:
    """Register or replace a named unposted-document probe."""

    _PROBES[name] = probe


def registered_probes() -> tuple[UnpostedProbe, ...]:
    """Return probes in registration-name order."""

    return tuple(_PROBES[name] for name in _PROBES)


def clear() -> None:
    """Remove every probe. Intended for tests."""

    _PROBES.clear()
