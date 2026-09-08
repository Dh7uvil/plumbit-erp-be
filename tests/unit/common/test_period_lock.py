"""Unit tests for the shared period-lock policy helper."""

from datetime import date

import pytest

from app.common.period_lock import PeriodLockPolicy
from app.core.exceptions import PeriodLockedError

_DOC = date(2024, 6, 15)
_LOCK = date(2024, 6, 30)
_HARD = date(2024, 5, 31)


def test_open_period_is_not_locked() -> None:
    policy = PeriodLockPolicy(lock_date=None, hard_lock_date=None)
    assert policy.is_locked(_DOC, can_override=False) is False
    policy.assert_open(_DOC, can_override=False)


def test_soft_lock_blocks_without_override() -> None:
    policy = PeriodLockPolicy(lock_date=_LOCK, hard_lock_date=None, lock_reason="Month-end close")
    assert policy.is_locked(_DOC, can_override=False) is True
    assert policy.is_locked(_DOC, can_override=True) is False
    assert policy.is_locked(date(2024, 7, 1), can_override=False) is False
    with pytest.raises(PeriodLockedError) as exc:
        policy.assert_open(_DOC, can_override=False)
    assert exc.value.details["tier"] == "soft"
    assert exc.value.details["reason"] == "Month-end close"
    assert exc.value.details["lock_date"] == "2024-06-30"
    assert exc.value.details["document_date"] == "2024-06-15"
    policy.assert_open(_DOC, can_override=True)


def test_hard_lock_blocks_every_actor() -> None:
    policy = PeriodLockPolicy(
        lock_date=_LOCK,
        hard_lock_date=_HARD,
        hard_lock_reason="VAT filed",
    )
    assert policy.is_locked(date(2024, 5, 1), can_override=True) is True
    with pytest.raises(PeriodLockedError) as exc:
        policy.assert_open(date(2024, 5, 1), can_override=True)
    assert exc.value.details["tier"] == "hard"
    assert exc.value.details["reason"] == "VAT filed"
    assert exc.value.details["hard_lock_date"] == "2024-05-31"


def test_inclusive_lock_date() -> None:
    policy = PeriodLockPolicy(lock_date=_LOCK, hard_lock_date=None)
    assert policy.is_locked(_LOCK, can_override=False) is True
    policy.assert_open(date(2024, 7, 1), can_override=False)
