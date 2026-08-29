"""Unit tests for quotation totals and UAE VAT category resolution."""

from decimal import Decimal
from uuid import uuid4

from app.auth.schemas import AddressResponse
from app.core.enums import DiscountType, PlaceOfSupply, TaxCategory, TaxTreatment
from app.erp.quotation.totals import (
    compute_header_totals,
    compute_line_amounts,
    place_of_supply_from_address,
    resolve_line_tax_category,
)


def test_line_amounts_apply_percent_discount_then_vat() -> None:
    qty, discount, tax, net = compute_line_amounts(
        quantity=Decimal("2"),
        rate=Decimal("100"),
        discount_type=DiscountType.PERCENTAGE,
        discount_value=Decimal("10"),
        tax_rate=Decimal("5"),
    )
    assert qty == Decimal("2.000000")
    assert discount == Decimal("20.0000")
    assert net == Decimal("180.0000")
    assert tax == Decimal("9.0000")


def test_header_totals_ignore_client_intent_and_add_shipping() -> None:
    subtotal, discount, tax_total, grand = compute_header_totals(
        line_nets=[Decimal("180.0000")],
        line_taxes=[Decimal("9.0000")],
        discount_type=DiscountType.AMOUNT,
        discount_value=Decimal("20"),
        shipping_amount=Decimal("5"),
        adjustment_amount=Decimal("0"),
    )
    assert subtotal == Decimal("180.0000")
    assert discount == Decimal("20.0000")
    assert tax_total == Decimal("9.0000")
    assert grand == Decimal("174.0000")


def test_export_and_outside_uae_zero_rate_standard_items() -> None:
    assert (
        resolve_line_tax_category(
            item_category=TaxCategory.STANDARD,
            tax_treatment=TaxTreatment.EXPORT,
            place_of_supply=PlaceOfSupply.DUBAI,
        )
        == TaxCategory.ZERO_RATED
    )
    assert (
        resolve_line_tax_category(
            item_category=TaxCategory.STANDARD,
            tax_treatment=TaxTreatment.REGISTERED,
            place_of_supply=PlaceOfSupply.OUTSIDE_UAE,
        )
        == TaxCategory.ZERO_RATED
    )


def test_exempt_item_keeps_exempt_even_for_domestic_registered() -> None:
    assert (
        resolve_line_tax_category(
            item_category=TaxCategory.EXEMPT,
            tax_treatment=TaxTreatment.REGISTERED,
            place_of_supply=PlaceOfSupply.DUBAI,
        )
        == TaxCategory.EXEMPT
    )


def test_registered_domestic_standard_stays_standard() -> None:
    assert (
        resolve_line_tax_category(
            item_category=TaxCategory.STANDARD,
            tax_treatment=TaxTreatment.REGISTERED,
            place_of_supply=PlaceOfSupply.DUBAI,
        )
        == TaxCategory.STANDARD
    )


def test_place_of_supply_from_shipping_address() -> None:
    dubai = AddressResponse(
        id=uuid4(),
        address_line_1="1 Sheikh Zayed Rd",
        city="Dubai",
        state="DUBAI",
        country="United Arab Emirates",
        country_code="AE",
        postal_code=None,
        address_line_2=None,
    )
    export = AddressResponse(
        id=uuid4(),
        address_line_1="1 King St",
        city="London",
        state=None,
        country="United Kingdom",
        country_code="GB",
        postal_code=None,
        address_line_2=None,
    )
    assert place_of_supply_from_address(dubai) == PlaceOfSupply.DUBAI
    assert place_of_supply_from_address(export) == PlaceOfSupply.OUTSIDE_UAE
