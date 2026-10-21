"""Cost sheet charge allocation helpers."""

from decimal import Decimal

from app.erp.cost_sheets.service import _split_proportional


def test_split_proportional_puts_remainder_on_last_line() -> None:
    total = Decimal("10.00")
    weights = [Decimal("1"), Decimal("1"), Decimal("1")]
    shares = _split_proportional(total, weights)
    assert sum(shares, Decimal("0")) == total
    assert shares[-1] == Decimal("3.3334")
    assert shares[0] == Decimal("3.3333")
