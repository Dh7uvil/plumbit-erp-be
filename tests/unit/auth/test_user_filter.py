from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.auth.schemas import UserFilter
from app.core.enums import EmployeeStatus, UserStatus


def test_user_filter_collects_role_ids() -> None:
    first = uuid4()
    second = uuid4()
    filters = UserFilter(role_id=first, role_ids=[second, first])
    assert filters.collected_role_ids() == [second, first]


def test_user_filter_parses_comma_separated_role_ids() -> None:
    first = uuid4()
    second = uuid4()
    filters = UserFilter.model_validate({"role_ids": f"{first},{second}"})
    assert filters.role_ids == [first, second]


def test_user_filter_rejects_inverted_joining_date_range() -> None:
    with pytest.raises(ValidationError):
        UserFilter(joining_date_from=date(2026, 2, 1), joining_date_to=date(2026, 1, 1))


def test_user_filter_rejects_inverted_last_login_range() -> None:
    with pytest.raises(ValidationError):
        UserFilter(
            last_login_from=datetime(2026, 2, 1, tzinfo=UTC),
            last_login_to=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_user_filter_accepts_employee_status() -> None:
    filters = UserFilter(status=UserStatus.ACTIVE, employee_status=EmployeeStatus.INACTIVE)
    assert filters.status is UserStatus.ACTIVE
    assert filters.employee_status is EmployeeStatus.INACTIVE
