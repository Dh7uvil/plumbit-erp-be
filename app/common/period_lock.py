"""Shared period-lock invariant. No database and no feature-module imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.core.exceptions import PeriodLockedError


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class PeriodLockPolicy:
    lock_date: date | None
    hard_lock_date: date | None
    lock_reason: str | None = None
    hard_lock_reason: str | None = None

    def is_locked(self, document_date: date, *, can_override: bool) -> bool:
        if self.hard_lock_date is not None and document_date <= self.hard_lock_date:
            return True
        if self.lock_date is not None and document_date <= self.lock_date:
            return not can_override
        return False

    def assert_open(self, document_date: date, *, can_override: bool) -> None:
        if self.hard_lock_date is not None and document_date <= self.hard_lock_date:
            raise PeriodLockedError(
                details={
                    "lock_date": _iso(self.lock_date),
                    "hard_lock_date": _iso(self.hard_lock_date),
                    "document_date": document_date.isoformat(),
                    "tier": "hard",
                    "reason": self.hard_lock_reason,
                }
            )
        if self.lock_date is not None and document_date <= self.lock_date and not can_override:
            raise PeriodLockedError(
                details={
                    "lock_date": _iso(self.lock_date),
                    "hard_lock_date": _iso(self.hard_lock_date),
                    "document_date": document_date.isoformat(),
                    "tier": "soft",
                    "reason": self.lock_reason,
                }
            )
