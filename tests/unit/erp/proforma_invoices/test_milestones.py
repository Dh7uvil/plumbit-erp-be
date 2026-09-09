"""Unit tests for proforma invoice milestone amount resolution."""

from decimal import Decimal

import pytest

from app.core.enums import PaymentMilestoneTrigger
from app.core.exceptions import MilestoneModeMixedError, MilestoneTotalMismatchError
from app.erp.proforma_invoices.schemas import ProformaInvoiceMilestoneInput
from app.erp.proforma_invoices.service import compute_milestone_amounts


def _percent(sequence: int, percent: str) -> ProformaInvoiceMilestoneInput:
    return ProformaInvoiceMilestoneInput(
        sequence=sequence,
        label=f"Milestone {sequence}",
        trigger=PaymentMilestoneTrigger.ON_CONFIRMATION,
        percent=Decimal(percent),
    )


def _amount(sequence: int, amount: str) -> ProformaInvoiceMilestoneInput:
    return ProformaInvoiceMilestoneInput(
        sequence=sequence,
        label=f"Milestone {sequence}",
        trigger=PaymentMilestoneTrigger.BEFORE_SHIPMENT,
        amount=Decimal(amount),
    )


def test_percent_mode_sums_to_grand_total() -> None:
    rows = compute_milestone_amounts(
        [_percent(1, "30"), _percent(2, "70")],
        Decimal("210.0000"),
    )
    assert rows[0]["computed_amount"] == Decimal("63.0000")
    assert rows[1]["computed_amount"] == Decimal("147.0000")
    assert sum((row["computed_amount"] for row in rows), Decimal("0")) == Decimal("210.0000")


def test_last_milestone_absorbs_rounding() -> None:
    rows = compute_milestone_amounts(
        [_percent(1, "33.3300"), _percent(2, "66.6700")],
        Decimal("10.0000"),
    )
    assert rows[0]["computed_amount"] == Decimal("3.3330")
    assert rows[1]["computed_amount"] == Decimal("6.6670")
    assert sum((row["computed_amount"] for row in rows), Decimal("0")) == Decimal("10.0000")


def test_amount_mode_must_match_grand_total() -> None:
    rows = compute_milestone_amounts(
        [_amount(1, "30.0000"), _amount(2, "70.0000")],
        Decimal("100.0000"),
    )
    assert [row["computed_amount"] for row in rows] == [Decimal("30.0000"), Decimal("70.0000")]


def test_mixed_mode_is_rejected() -> None:
    with pytest.raises(MilestoneModeMixedError):
        compute_milestone_amounts(
            [_percent(1, "30"), _amount(2, "70.0000")],
            Decimal("100.0000"),
        )


def test_percent_sum_mismatch_is_rejected() -> None:
    with pytest.raises(MilestoneTotalMismatchError):
        compute_milestone_amounts(
            [_percent(1, "30"), _percent(2, "60")],
            Decimal("100.0000"),
        )


def test_amount_sum_mismatch_is_rejected() -> None:
    with pytest.raises(MilestoneTotalMismatchError):
        compute_milestone_amounts(
            [_amount(1, "30.0000"), _amount(2, "60.0000")],
            Decimal("100.0000"),
        )
