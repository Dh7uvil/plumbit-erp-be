"""Unit tests for recurring schedule anchor day."""

from datetime import date

from app.erp.accounting.recurring.service import advance_date


def test_monthly_jan_31_stays_on_month_end() -> None:
    current = date(2024, 1, 31)
    next_run = advance_date(current, "MONTHLY", 1, schedule_day=31)
    assert next_run == date(2024, 2, 29)


def test_monthly_jan_31_march_returns_mar_31() -> None:
    current = date(2024, 2, 29)
    next_run = advance_date(current, "MONTHLY", 1, schedule_day=31)
    assert next_run == date(2024, 3, 31)


def test_quarterly_from_jan_31() -> None:
    current = date(2024, 1, 31)
    next_run = advance_date(current, "QUARTERLY", 1, schedule_day=31)
    assert next_run == date(2024, 4, 30)


def test_yearly_from_jan_31_leap_year() -> None:
    current = date(2024, 1, 31)
    next_run = advance_date(current, "YEARLY", 1, schedule_day=31)
    assert next_run == date(2025, 1, 31)
