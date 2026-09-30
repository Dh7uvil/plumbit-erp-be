"""Unit tests for Phase 2 commercial money integrity helpers."""

from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.common.schemas.discount_fields import DiscountFieldsMixin, assert_discount_bounds
from app.common.utils.document_totals import compute_header_totals, discount_amount
from app.common.utils.settlement import assert_invoice_not_over_settled
from app.core.enums import DiscountType
from app.core.exceptions import PaymentOverAllocatedError, ValidationError


class _DiscountPayload(DiscountFieldsMixin):
    pass


def test_percentage_discount_schema_rejects_over_100() -> None:
    with pytest.raises(PydanticValidationError, match="100"):
        _DiscountPayload(
            discount_type=DiscountType.PERCENTAGE,
            discount_value=Decimal("100.01"),
        )


def test_discount_amount_rejects_over_100_percent() -> None:
    with pytest.raises(ValidationError, match="100"):
        discount_amount(
            Decimal("100"),
            DiscountType.PERCENTAGE,
            Decimal("150"),
        )


def test_assert_discount_bounds_service_guard() -> None:
    with pytest.raises(ValidationError, match="100"):
        assert_discount_bounds(DiscountType.PERCENTAGE, Decimal("101"))


def test_compute_header_totals_caps_negative_adjustment() -> None:
    _, _, _, grand, _, adjustment = compute_header_totals(
        line_nets=[Decimal("100.0000")],
        line_taxes=[Decimal("5.0000")],
        discount_type=None,
        discount_value=None,
        shipping_amount=Decimal("0"),
        adjustment_amount=Decimal("-200"),
    )
    assert grand == Decimal("0.0000")
    assert adjustment == Decimal("-105.0000")


def test_apply_credit_cap_raises_when_over_settled() -> None:
    with pytest.raises(PaymentOverAllocatedError):
        assert_invoice_not_over_settled(
            grand_total=Decimal("100.0000"),
            amount_paid=Decimal("60.0000"),
            amount_credited=Decimal("50.0000"),
            amount_written_off=Decimal("0"),
        )


def test_apply_credit_cap_allows_exact_settlement() -> None:
    assert_invoice_not_over_settled(
        grand_total=Decimal("100.0000"),
        amount_paid=Decimal("60.0000"),
        amount_credited=Decimal("40.0000"),
        amount_written_off=Decimal("0"),
    )
