"""Product line unit resolution (base unit and unit 2)."""

from decimal import Decimal
from uuid import UUID

import pytest

from app.core.exceptions import ValidationError
from app.inventory_management.products.line_units import (
    normalize_product_line_for_storage,
    resolve_line_to_pieces,
    resolve_line_to_stock_quantity,
)


class _Product:
    unit_id = UUID("11111111-1111-4111-8111-111111111111")
    secondary_unit_id = UUID("22222222-2222-4222-8222-222222222222")
    secondary_unit_factor = Decimal("10")
    pieces_per_unit = None


def test_base_unit_unchanged() -> None:
    resolved = resolve_line_to_pieces(
        _Product(),
        unit_id=_Product.unit_id,
        quantity=Decimal("5"),
        rate=Decimal("100"),
        base_unit_code="PCS",
        line_unit_code="PCS",
    )
    assert resolved.unit_id == _Product.unit_id
    assert resolved.quantity == Decimal("5.000000")
    assert resolved.rate == Decimal("100")


def test_unit2_package_converts_qty_and_rate() -> None:
    resolved = resolve_line_to_pieces(
        _Product(),
        unit_id=_Product.secondary_unit_id,
        quantity=Decimal("2"),
        rate=Decimal("100"),
        base_unit_code="PCS",
        secondary_unit_code="CTN",
        line_unit_code="CTN",
    )
    assert resolved.unit_id == _Product.unit_id
    assert resolved.quantity == Decimal("20.000000")
    assert resolved.rate == Decimal("10.0000")


def test_unit2_pieces_keeps_unit2_on_document_without_unit_codes() -> None:
    resolved = resolve_line_to_pieces(
        _Product(),
        unit_id=_Product.secondary_unit_id,
        quantity=Decimal("100"),
        rate=Decimal("5"),
    )
    assert resolved.unit_id == _Product.secondary_unit_id
    assert resolved.quantity == Decimal("100.000000")
    assert resolved.rate == Decimal("5")


def test_unit2_pieces_keeps_unit2_on_document() -> None:
    resolved = resolve_line_to_pieces(
        _Product(),
        unit_id=_Product.secondary_unit_id,
        quantity=Decimal("100"),
        rate=Decimal("5"),
        base_unit_code="CTN",
        secondary_unit_code="PCS",
        line_unit_code="PCS",
    )
    assert resolved.unit_id == _Product.secondary_unit_id
    assert resolved.quantity == Decimal("100.000000")
    assert resolved.rate == Decimal("5")


def test_stock_converts_pieces_unit2_to_base() -> None:
    resolved = resolve_line_to_stock_quantity(
        _Product(),
        unit_id=_Product.secondary_unit_id,
        quantity=Decimal("100"),
        base_unit_code="CTN",
        secondary_unit_code="PCS",
        line_unit_code="PCS",
    )
    assert resolved.unit_id == _Product.unit_id
    assert resolved.quantity == Decimal("10.000000")


def test_stock_uses_pieces_per_unit_when_unit2_is_pieces() -> None:
    class CartonProduct(_Product):
        secondary_unit_factor = Decimal("1")
        pieces_per_unit = Decimal("100")

    resolved = resolve_line_to_stock_quantity(
        CartonProduct(),
        unit_id=_Product.secondary_unit_id,
        quantity=Decimal("5000"),
        base_unit_code="CTN",
        secondary_unit_code="PCS",
        line_unit_code="PCS",
    )
    assert resolved.unit_id == CartonProduct.unit_id
    assert resolved.quantity == Decimal("50.000000")


def test_foreign_unit_rejected() -> None:
    foreign = UUID("33333333-3333-4333-8333-333333333333")
    with pytest.raises(ValidationError, match="Unit must match the product unit or unit 2"):
        resolve_line_to_pieces(
            _Product(),
            unit_id=foreign,
            quantity=Decimal("1"),
            base_unit_code="PCS",
            secondary_unit_code="CTN",
            line_unit_code="BOX",
        )


def test_unit2_without_factor_rejected() -> None:
    class NoFactor(_Product):
        secondary_unit_factor = None
        pieces_per_unit = None

    with pytest.raises(ValidationError, match="pieces-per-package"):
        resolve_line_to_pieces(
            NoFactor(),
            unit_id=_Product.secondary_unit_id,
            quantity=Decimal("1"),
            base_unit_code="PCS",
            secondary_unit_code="CTN",
            line_unit_code="CTN",
        )


def test_normalize_without_product_passthrough() -> None:
    uid, qty, rate, cost = normalize_product_line_for_storage(
        None,
        unit_id=None,
        quantity=Decimal("3"),
        rate=Decimal("9"),
        unit_cost=Decimal("2"),
    )
    assert uid is None
    assert qty == Decimal("3.000000")
    assert rate == Decimal("9")
    assert cost == Decimal("2")
