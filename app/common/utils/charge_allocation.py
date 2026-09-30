"""Spread inventoriable charges across document lines by allocation basis."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.common.utils.currency import quantize_money, quantize_quantity
from app.core.enums import ChargeAllocationMethod
from app.core.exceptions import ChargeAllocationBasisMissingError

_ZERO = Decimal("0")


def spread_amount(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    total_weight = sum(weights, _ZERO)
    if total_weight <= _ZERO:
        return [_ZERO for _ in weights]
    raw = [quantize_money(total * (weight / total_weight)) for weight in weights]
    drift = quantize_money(total - sum(raw, _ZERO))
    if raw:
        raw[-1] = quantize_money(raw[-1] + drift)
    return raw


@dataclass(frozen=True, slots=True)
class ChargeLineContext:
    quantity: Decimal
    rate: Decimal
    net_weight: Decimal | None
    gross_weight: Decimal | None
    volume: Decimal | None


def line_allocation_base(
    line: ChargeLineContext,
    method: ChargeAllocationMethod,
    *,
    exchange_rate: Decimal,
) -> Decimal:
    if method == ChargeAllocationMethod.QUANTITY:
        return quantize_quantity(line.quantity)
    if method == ChargeAllocationMethod.WEIGHT:
        weight = (
            line.net_weight
            if line.net_weight is not None and line.net_weight > _ZERO
            else line.gross_weight
        )
        return quantize_quantity(weight or _ZERO)
    if method == ChargeAllocationMethod.VOLUME:
        return quantize_quantity(line.volume or _ZERO)
    return quantize_money(line.quantity * line.rate * exchange_rate)


def allocate_charge(
    amount: Decimal,
    lines: list[ChargeLineContext],
    method: ChargeAllocationMethod,
    *,
    exchange_rate: Decimal,
) -> list[Decimal]:
    value_bases = [
        line_allocation_base(line, ChargeAllocationMethod.VALUE, exchange_rate=exchange_rate)
        for line in lines
    ]
    bases = [
        line_allocation_base(line, method, exchange_rate=exchange_rate) for line in lines
    ]
    if sum(bases, _ZERO) <= _ZERO:
        if method in {ChargeAllocationMethod.WEIGHT, ChargeAllocationMethod.VOLUME}:
            raise ChargeAllocationBasisMissingError(
                details={"allocation_basis": method.value},
            )
        bases = value_bases
    if sum(bases, _ZERO) <= _ZERO:
        return [_ZERO for _ in lines]
    return spread_amount(amount, bases)
