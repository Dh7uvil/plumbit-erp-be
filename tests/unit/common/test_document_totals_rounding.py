"""Rounding remainder tests for header-discount VAT distribution."""

from decimal import Decimal

from app.common.utils.document_totals import (
    adjusted_line_taxes_after_header_discount,
    compute_header_totals,
    compute_line_amounts,
)
from app.core.enums import DiscountType


def test_header_discount_vat_sums_to_expected_total_three_lines() -> None:
    line_nets = [Decimal("33.3300"), Decimal("33.3300"), Decimal("33.3400")]
    line_taxes = [Decimal("1.6665"), Decimal("1.6665"), Decimal("1.6670")]
    adjusted = adjusted_line_taxes_after_header_discount(
        line_nets, line_taxes, Decimal("10.0000")
    )
    expected = quantize_expected(line_taxes, line_nets, Decimal("10.0000"))
    assert sum(adjusted, start=Decimal("0")) == expected


def test_header_discount_vat_sums_to_expected_total_seven_lines() -> None:
    line_nets = [Decimal(f"{14 + index}.0000") for index in range(7)]
    line_taxes = [quantize_money(net * Decimal("0.05")) for net in line_nets]
    doc_discount = Decimal("17.5000")
    adjusted = adjusted_line_taxes_after_header_discount(line_nets, line_taxes, doc_discount)
    expected = quantize_expected(line_taxes, line_nets, doc_discount)
    assert sum(adjusted, start=Decimal("0")) == expected


def test_compute_header_totals_zero_rated_and_shipping() -> None:
    subtotal, discount, tax_total, grand, adjusted = compute_header_totals(
        line_nets=[Decimal("100.0000"), Decimal("50.0000")],
        line_taxes=[Decimal("0.0000"), Decimal("0.0000")],
        discount_type=DiscountType.PERCENTAGE,
        discount_value=Decimal("5"),
        shipping_amount=Decimal("12.5000"),
        adjustment_amount=Decimal("-2.0000"),
    )
    assert subtotal == Decimal("150.0000")
    assert discount == Decimal("7.5000")
    assert tax_total == Decimal("0.0000")
    assert adjusted == [Decimal("0.0000"), Decimal("0.0000")]
    assert grand == Decimal("153.0000")


def quantize_money(value: Decimal) -> Decimal:
    from app.common.utils.currency import quantize_money as qm

    return qm(value)


def quantize_expected(
    line_taxes: list[Decimal], line_nets: list[Decimal], doc_discount: Decimal
) -> Decimal:
    subtotal = quantize_money(sum(line_nets, start=Decimal("0")))
    taxable_ratio = (subtotal - doc_discount) / subtotal
    return quantize_money(sum(line_taxes, start=Decimal("0")) * taxable_ratio)
