"""Fiscal year boundary helpers. 1 January defaults match calendar year."""

from datetime import date

from app.erp.accounting.fiscal import FiscalYearConfig


def test_january_default_matches_calendar_year() -> None:
    config = FiscalYearConfig()
    assert config.year_for(date(2026, 1, 1)) == 2026
    assert config.year_for(date(2026, 12, 31)) == 2026
    assert config.bounds(2026) == (date(2026, 1, 1), date(2026, 12, 31))


def test_april_start_splits_calendar_years() -> None:
    config = FiscalYearConfig(start_month=4, start_day=1)
    assert config.year_for(date(2026, 3, 31)) == 2025
    assert config.year_for(date(2026, 4, 1)) == 2026
    assert config.bounds(2026) == (date(2026, 4, 1), date(2027, 3, 31))


def test_february_29_clamps_on_non_leap_years() -> None:
    config = FiscalYearConfig(start_month=2, start_day=29)
    assert config.year_for(date(2025, 2, 28)) == 2025
    start, end = config.bounds(2025)
    assert start == date(2025, 2, 28)
    assert end == date(2026, 2, 27)
