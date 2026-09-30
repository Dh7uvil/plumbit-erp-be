"""Parity tests for document total helpers."""

from decimal import Decimal

from app.common.utils.document_totals import (
    compute_line_amounts,
    header_discount_share,
)


def test_compute_line_amounts_inclusive_back_calculates_tax() -> None:
    qty, discount, tax, net = compute_line_amounts(
        quantity=Decimal("1"),
        rate=Decimal("105"),
        discount_type=None,
        discount_value=None,
        tax_rate=Decimal("5"),
        prices_include_tax=True,
    )
    assert qty == Decimal("1.000000")
    assert discount == Decimal("0.0000")
    assert net == Decimal("100.0000")
    assert tax == Decimal("5.0000")
    assert net + tax == Decimal("105.0000")


def test_header_discount_share_sums_to_total() -> None:
    doc_discount = Decimal("10.0000")
    line_nets = [Decimal("33.3300"), Decimal("33.3300"), Decimal("33.3400")]
    subtotal = Decimal("100.0000")
    shares = [header_discount_share(doc_discount, subtotal, net) for net in line_nets]
    assert sum(shares, start=Decimal("0")) == doc_discount
