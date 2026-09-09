"""Unit tests for quality inspection qty rules."""

from decimal import Decimal

import pytest

from app.core.enums import QcDisposition, QualityInspectionStatus
from app.core.exceptions import QualityQtyMismatchError, ValidationError
from app.inventory_management.quality_inspections.workflow import (
    assert_line_quantities,
    next_status,
    transition_actions,
)


def test_draft_can_approve_or_cancel() -> None:
    assert transition_actions(QualityInspectionStatus.DRAFT) == ["approve", "cancel"]
    assert next_status(QualityInspectionStatus.DRAFT, "approve") == QualityInspectionStatus.APPROVED


def test_accepted_rejected_rework_must_sum_to_inspected() -> None:
    with pytest.raises(QualityQtyMismatchError):
        assert_line_quantities(
            qty_inspected=Decimal("10"),
            qty_accepted=Decimal("6"),
            qty_rejected=Decimal("3"),
            qty_rework=Decimal("0"),
            remaining_hold=Decimal("10"),
            disposition=None,
        )


def test_inspected_cannot_exceed_remaining_hold() -> None:
    with pytest.raises(QualityQtyMismatchError):
        assert_line_quantities(
            qty_inspected=Decimal("5"),
            qty_accepted=Decimal("5"),
            qty_rejected=Decimal("0"),
            qty_rework=Decimal("0"),
            remaining_hold=Decimal("4"),
            disposition=None,
        )


def test_rejected_requires_disposition() -> None:
    with pytest.raises(ValidationError):
        assert_line_quantities(
            qty_inspected=Decimal("2"),
            qty_accepted=Decimal("0"),
            qty_rejected=Decimal("2"),
            qty_rework=Decimal("0"),
            remaining_hold=Decimal("2"),
            disposition=None,
        )


def test_valid_partial_line_with_scrap() -> None:
    assert_line_quantities(
        qty_inspected=Decimal("10"),
        qty_accepted=Decimal("7"),
        qty_rejected=Decimal("2"),
        qty_rework=Decimal("1"),
        remaining_hold=Decimal("10"),
        disposition=QcDisposition.SCRAP,
    )
