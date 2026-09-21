"""Unit tests for campaign ROI arithmetic."""

from decimal import Decimal

from app.crm.campaigns.workflow import compute_roi_percent


def test_roi_is_percent_of_actual_cost() -> None:
    assert compute_roi_percent(
        won_opportunity_value=Decimal("150.0000"),
        actual_cost=Decimal("50.0000"),
    ) == Decimal("200.0000")


def test_negative_roi_when_cost_exceeds_won_value() -> None:
    assert compute_roi_percent(
        won_opportunity_value=Decimal("40.0000"),
        actual_cost=Decimal("50.0000"),
    ) == Decimal("-20.0000")


def test_roi_is_none_without_positive_cost() -> None:
    assert compute_roi_percent(won_opportunity_value=Decimal("100"), actual_cost=None) is None
    assert (
        compute_roi_percent(won_opportunity_value=Decimal("100"), actual_cost=Decimal("0")) is None
    )
