"""Pure quotation total and UAE VAT helpers. No I/O."""

from __future__ import annotations

from decimal import Decimal

from app.auth.schemas import AddressResponse, format_address_label
from app.common.utils.currency import quantize_money, quantize_quantity
from app.core.enums import DiscountType, PlaceOfSupply, TaxCategory, TaxTreatment

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")

_UAE_COUNTRY_TOKENS = frozenset({"AE", "UAE", "UNITED ARAB EMIRATES"})
_EMIRATE_ALIASES: dict[str, PlaceOfSupply] = {
    "ABU_DHABI": PlaceOfSupply.ABU_DHABI,
    "ABU DHABI": PlaceOfSupply.ABU_DHABI,
    "DUBAI": PlaceOfSupply.DUBAI,
    "SHARJAH": PlaceOfSupply.SHARJAH,
    "AJMAN": PlaceOfSupply.AJMAN,
    "UMM_AL_QUWAIN": PlaceOfSupply.UMM_AL_QUWAIN,
    "UMM AL QUWAIN": PlaceOfSupply.UMM_AL_QUWAIN,
    "RAS_AL_KHAIMAH": PlaceOfSupply.RAS_AL_KHAIMAH,
    "RAS AL KHAIMAH": PlaceOfSupply.RAS_AL_KHAIMAH,
    "FUJAIRAH": PlaceOfSupply.FUJAIRAH,
    "OUTSIDE_UAE": PlaceOfSupply.OUTSIDE_UAE,
}


def discount_amount(
    base: Decimal,
    discount_type: DiscountType | None,
    discount_value: Decimal | None,
) -> Decimal:
    if discount_type is None or discount_value is None:
        return quantize_money(_ZERO)
    if discount_type == DiscountType.PERCENTAGE:
        return quantize_money(base * discount_value / _HUNDRED)
    return quantize_money(min(discount_value, base))


def compute_line_amounts(
    *,
    quantity: Decimal,
    rate: Decimal,
    discount_type: DiscountType | None,
    discount_value: Decimal | None,
    tax_rate: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return (qty, line_discount, tax_amount, net_amount)."""

    qty = quantize_quantity(quantity)
    gross = quantize_money(qty * rate)
    line_discount = discount_amount(gross, discount_type, discount_value)
    net = quantize_money(gross - line_discount)
    tax = quantize_money(net * tax_rate / _HUNDRED)
    return qty, line_discount, tax, net


def compute_header_totals(
    *,
    line_nets: list[Decimal],
    line_taxes: list[Decimal],
    discount_type: DiscountType | None,
    discount_value: Decimal | None,
    shipping_amount: Decimal,
    adjustment_amount: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return (subtotal, doc_discount, tax_total, grand_total)."""

    subtotal = quantize_money(sum(line_nets, start=_ZERO))
    tax_total = quantize_money(sum(line_taxes, start=_ZERO))
    doc_discount = discount_amount(subtotal, discount_type, discount_value)
    grand = quantize_money(
        subtotal - doc_discount + tax_total + shipping_amount + adjustment_amount
    )
    return subtotal, doc_discount, tax_total, grand


def resolve_line_tax_category(
    *,
    item_category: TaxCategory | None,
    tax_treatment: TaxTreatment,
    place_of_supply: PlaceOfSupply,
) -> TaxCategory:
    """Decide the VAT category snapshotted onto a quote line."""

    if item_category in {
        TaxCategory.EXEMPT,
        TaxCategory.OUT_OF_SCOPE,
        TaxCategory.ZERO_RATED,
    }:
        return item_category
    if tax_treatment in {TaxTreatment.EXPORT, TaxTreatment.GCC, TaxTreatment.EXEMPT}:
        return TaxCategory.ZERO_RATED
    if place_of_supply == PlaceOfSupply.OUTSIDE_UAE:
        return TaxCategory.ZERO_RATED
    return item_category or TaxCategory.STANDARD


def place_of_supply_from_address(address: AddressResponse | None) -> PlaceOfSupply:
    if address is None:
        return PlaceOfSupply.DUBAI
    country = (address.country_code or address.country or "").strip().upper()
    if country and country not in _UAE_COUNTRY_TOKENS:
        return PlaceOfSupply.OUTSIDE_UAE
    state = (address.state or "").strip().upper()
    if not state:
        return PlaceOfSupply.DUBAI
    try:
        return PlaceOfSupply(state.replace(" ", "_"))
    except ValueError:
        return _EMIRATE_ALIASES.get(state, PlaceOfSupply.DUBAI)


def format_address_snapshot(address: AddressResponse | None) -> str | None:
    return format_address_label(address)
