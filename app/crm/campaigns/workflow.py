"""Campaign ROI helpers. Money arithmetic stays in Decimal."""

from decimal import ROUND_HALF_UP, Decimal

from app.core.constants import MONEY_SCALE

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_MONEY_QUANTUM = Decimal("1").scaleb(-MONEY_SCALE)


def compute_roi_percent(
    *, won_opportunity_value: Decimal, actual_cost: Decimal | None
) -> Decimal | None:
    """Return ROI as a percent of actual cost, or None when cost is missing or zero."""

    if actual_cost is None or actual_cost <= _ZERO:
        return None
    roi = ((won_opportunity_value - actual_cost) / actual_cost) * _HUNDRED
    return roi.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
