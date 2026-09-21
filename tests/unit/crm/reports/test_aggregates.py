"""Unit tests for CRM report helpers."""

from decimal import Decimal

from app.core.exceptions import ValidationError
from app.crm.reports.constants import PIPELINE_GROUPS, REPORT_ROW_LIMIT
from app.crm.reports.repository import bound_rows, percent_of
from app.crm.reports.service import CrmReportService


def test_percent_of_quantizes_to_money_scale() -> None:
    assert percent_of(1, 2) == Decimal("50.0000")
    assert percent_of(1, 3) == Decimal("33.3333")


def test_percent_of_is_none_without_whole() -> None:
    assert percent_of(1, 0) is None
    assert percent_of(0, 0) is None


def test_bound_rows_enforces_report_limit() -> None:
    rows = list(range(REPORT_ROW_LIMIT + 5))
    kept, truncated = bound_rows(rows)
    assert truncated is True
    assert kept == rows[:REPORT_ROW_LIMIT]
    kept, truncated = bound_rows(list(range(3)))
    assert truncated is False
    assert kept == [0, 1, 2]


def test_invalid_group_by_raises_validation_error() -> None:
    service = CrmReportService(session=None)  # type: ignore[arg-type]
    try:
        service._require_group("not-a-group", PIPELINE_GROUPS, field="group_by")
    except ValidationError as exc:
        assert exc.details == {"group_by": "not-a-group"}
    else:
        raise AssertionError("expected ValidationError")
