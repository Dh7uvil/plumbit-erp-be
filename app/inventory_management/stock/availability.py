"""Single available-quantity formula for stock balances."""

from decimal import Decimal

from app.common.utils.currency import quantize_quantity

_ZERO = Decimal("0")


def available_qty(
    qty_on_hand: Decimal,
    qty_reserved: Decimal = _ZERO,
    qty_quality_hold: Decimal = _ZERO,
) -> Decimal:
    """Return quantity that can be transferred or sold.

    QC-held stock is not available. Reserved quantity is subtracted the same way.
    """

    return quantize_quantity(qty_on_hand - qty_reserved - qty_quality_hold)
