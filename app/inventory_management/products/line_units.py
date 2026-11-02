"""Resolve document and stock line units to the product base unit (pieces)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.common.utils.currency import quantize_money, quantize_quantity
from app.core.exceptions import ValidationError


class ProductUnitFields(Protocol):
    unit_id: UUID | None
    secondary_unit_id: UUID | None
    secondary_unit_factor: Decimal | None
    pieces_per_unit: Decimal | None


@dataclass(frozen=True)
class ResolvedProductLineQuantity:
    unit_id: UUID | None
    quantity: Decimal
    rate: Decimal | None = None
    unit_cost: Decimal | None = None
    landed_unit_cost: Decimal | None = None
    quality_hold_delta: Decimal | None = None


def _secondary_factor(product: ProductUnitFields) -> Decimal:
    factor = product.secondary_unit_factor
    if factor is None or factor <= 0:
        raise ValidationError(
            "Product unit 2 is not configured with a valid pieces-per-package factor"
        )
    return factor


def _scale_money_per_piece(value: Decimal | None, factor: Decimal) -> Decimal | None:
    if value is None:
        return None
    return quantize_money(value / factor)


def _scale_money_by_factor(value: Decimal | None, factor: Decimal) -> Decimal | None:
    if value is None:
        return None
    return quantize_money(value * factor)


def _is_pcs(code: str | None) -> bool:
    return (code or "").strip().upper() == "PCS"


def _pieces_per_base_unit(product: ProductUnitFields) -> Decimal | None:
    if product.secondary_unit_factor is not None and product.secondary_unit_factor > 0:
        return product.secondary_unit_factor
    if product.pieces_per_unit is not None and product.pieces_per_unit > 0:
        return product.pieces_per_unit
    return None


def resolve_line_to_pieces(
    product: ProductUnitFields,
    *,
    unit_id: UUID | None,
    quantity: Decimal,
    rate: Decimal | None = None,
    unit_cost: Decimal | None = None,
    landed_unit_cost: Decimal | None = None,
    quality_hold_delta: Decimal | None = None,
    base_unit_code: str | None = None,
    secondary_unit_code: str | None = None,
    line_unit_code: str | None = None,
) -> ResolvedProductLineQuantity:
    """Convert line qty/rate into the product inventory unit (pieces when configured)."""

    qty = quantize_quantity(quantity)
    hold = (
        quantize_quantity(quality_hold_delta)
        if quality_hold_delta is not None
        else None
    )
    base_unit = product.unit_id
    secondary_unit = product.secondary_unit_id
    base_pcs = _is_pcs(base_unit_code)
    sec_pcs = _is_pcs(secondary_unit_code)
    line_pcs = _is_pcs(line_unit_code)

    def _resolved(
        resolved_unit: UUID | None,
        resolved_qty: Decimal,
        resolved_rate: Decimal | None = rate,
        resolved_cost: Decimal | None = unit_cost,
        resolved_landed: Decimal | None = landed_unit_cost,
        resolved_hold: Decimal | None = hold,
    ) -> ResolvedProductLineQuantity:
        return ResolvedProductLineQuantity(
            unit_id=resolved_unit,
            quantity=resolved_qty,
            rate=resolved_rate,
            unit_cost=resolved_cost,
            landed_unit_cost=resolved_landed,
            quality_hold_delta=resolved_hold,
        )

    if unit_id is None or unit_id == base_unit:
        return _resolved(base_unit, qty)

    if secondary_unit is not None and unit_id == secondary_unit:
        factor = _pieces_per_base_unit(product)
        if factor is None:
            raise ValidationError(
                "Product unit 2 is not configured with a valid pieces-per-package factor"
            )
        if sec_pcs and not base_pcs:
            # Unit 2 is pieces — document lines stay in unit 2.
            return _resolved(secondary_unit, qty)
        if not base_pcs and base_unit_code is not None:
            # Known package inventory unit; document lines stay in unit 2 (e.g. pieces).
            return _resolved(secondary_unit, qty)
        if base_unit_code is None and secondary_unit_code is None and line_unit_code is None:
            # Avoid guessing conversions without unit codes (prevents pieces → cartons).
            return _resolved(secondary_unit, qty)
        if base_pcs and not sec_pcs:
            return _resolved(
                base_unit,
                quantize_quantity(qty * factor),
                _scale_money_per_piece(rate, factor),
                _scale_money_per_piece(unit_cost, factor),
                _scale_money_per_piece(landed_unit_cost, factor),
                quantize_quantity(hold * factor) if hold is not None else None,
            )
        return _resolved(
            base_unit,
            quantize_quantity(qty * factor),
            _scale_money_per_piece(rate, factor),
            _scale_money_per_piece(unit_cost, factor),
            _scale_money_per_piece(landed_unit_cost, factor),
            quantize_quantity(hold * factor) if hold is not None else None,
        )

    if line_pcs and not base_pcs:
        doc_unit = (
            secondary_unit
            if secondary_unit is not None
            and (unit_id == secondary_unit or sec_pcs)
            else unit_id
        )
        return _resolved(doc_unit, qty)

    if base_pcs and line_pcs:
        return _resolved(base_unit, qty)

    if base_unit is not None:
        raise ValidationError("Unit must match the product unit or unit 2")

    return _resolved(unit_id, qty)


def normalize_product_line_for_storage(
    product: ProductUnitFields | None,
    *,
    unit_id: UUID | None,
    quantity: Decimal,
    rate: Decimal | None = None,
    unit_cost: Decimal | None = None,
    base_unit_code: str | None = None,
    secondary_unit_code: str | None = None,
    line_unit_code: str | None = None,
) -> tuple[UUID | None, Decimal, Decimal | None, Decimal | None]:
    """Return unit_id, quantity, rate, and unit_cost for document line storage."""

    if product is None:
        return unit_id, quantize_quantity(quantity), rate, unit_cost
    resolved = resolve_line_to_pieces(
        product,
        unit_id=unit_id,
        quantity=quantity,
        rate=rate,
        unit_cost=unit_cost,
        base_unit_code=base_unit_code,
        secondary_unit_code=secondary_unit_code,
        line_unit_code=line_unit_code,
    )
    return (
        resolved.unit_id,
        resolved.quantity,
        resolved.rate,
        resolved.unit_cost,
    )


def resolve_line_to_stock_quantity(
    product: ProductUnitFields,
    *,
    unit_id: UUID | None,
    quantity: Decimal,
    unit_cost: Decimal | None = None,
    landed_unit_cost: Decimal | None = None,
    quality_hold_delta: Decimal | None = None,
    base_unit_code: str | None = None,
    secondary_unit_code: str | None = None,
    line_unit_code: str | None = None,
) -> ResolvedProductLineQuantity:
    """Convert a line into product.unit_id quantities for stock movements."""

    doc = resolve_line_to_pieces(
        product,
        unit_id=unit_id,
        quantity=quantity,
        rate=None,
        unit_cost=unit_cost,
        landed_unit_cost=landed_unit_cost,
        quality_hold_delta=quality_hold_delta,
        base_unit_code=base_unit_code,
        secondary_unit_code=secondary_unit_code,
        line_unit_code=line_unit_code,
    )
    base_unit = product.unit_id
    if doc.unit_id == base_unit or base_unit is None:
        return doc
    base_pcs = _is_pcs(base_unit_code)
    sec_pcs = _is_pcs(secondary_unit_code)
    factor = _pieces_per_base_unit(product)
    if factor is None:
        raise ValidationError(
            "Product unit 2 is not configured with a valid pieces-per-package factor"
        )
    if sec_pcs and not base_pcs and doc.unit_id == product.secondary_unit_id:
        return ResolvedProductLineQuantity(
            unit_id=base_unit,
            quantity=quantize_quantity(doc.quantity / factor),
            unit_cost=_scale_money_by_factor(doc.unit_cost, factor),
            landed_unit_cost=_scale_money_by_factor(doc.landed_unit_cost, factor),
            quality_hold_delta=(
                quantize_quantity(doc.quality_hold_delta / factor)
                if doc.quality_hold_delta is not None
                else None
            ),
        )
    return doc


def quantity_in_pieces(
    product: ProductUnitFields,
    *,
    unit_id: UUID | None,
    quantity: Decimal,
    base_unit_code: str | None = None,
    secondary_unit_code: str | None = None,
    line_unit_code: str | None = None,
) -> Decimal:
    return resolve_line_to_stock_quantity(
        product,
        unit_id=unit_id,
        quantity=quantity,
        base_unit_code=base_unit_code,
        secondary_unit_code=secondary_unit_code,
        line_unit_code=line_unit_code,
    ).quantity


def resolve_movement_qty(
    product: ProductUnitFields,
    *,
    unit_id: UUID | None,
    qty: Decimal,
    quality_hold_delta: Decimal | None = None,
    base_unit_code: str | None = None,
    secondary_unit_code: str | None = None,
    line_unit_code: str | None = None,
) -> tuple[Decimal, Decimal, UUID | None]:
    """Return quantity and hold delta in product base unit for stock movements."""

    hold_in = quality_hold_delta if quality_hold_delta is not None else Decimal("0")
    resolved = resolve_line_to_stock_quantity(
        product,
        unit_id=unit_id,
        quantity=qty,
        quality_hold_delta=hold_in,
        base_unit_code=base_unit_code,
        secondary_unit_code=secondary_unit_code,
        line_unit_code=line_unit_code,
    )
    hold_out = (
        resolved.quality_hold_delta
        if resolved.quality_hold_delta is not None
        else quantize_quantity(hold_in)
    )
    return resolved.quantity, hold_out, resolved.unit_id
