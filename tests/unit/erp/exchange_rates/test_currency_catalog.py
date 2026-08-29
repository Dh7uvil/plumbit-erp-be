"""Unit tests for the ISO 4217 currency catalog."""

from app.erp.exchange_rates.catalog import BASE_CURRENCY_CODE, ISO_4217_CURRENCIES

_EXCLUDED_NON_TENDER = frozenset({"XAU", "XAG", "XPT", "XPD", "XXX", "XTS"})
_REGIONAL_TENDERS = ("EUR", "XCD", "XOF", "XAF", "XPF")
_ZERO_DECIMAL = frozenset({"JPY", "KRW"})
_THREE_DECIMAL = frozenset({"BHD", "KWD", "OMR", "JOD"})


def test_catalog_codes_are_unique_and_well_formed() -> None:
    codes = [entry.code for entry in ISO_4217_CURRENCIES]
    assert len(codes) == len(set(codes))
    by_code = {entry.code: entry for entry in ISO_4217_CURRENCIES}

    aed = by_code[BASE_CURRENCY_CODE]
    assert aed.code == "AED"
    assert aed.name == "UAE Dirham"
    assert aed.symbol == "د.إ"
    assert aed.decimal_places == 2

    for entry in ISO_4217_CURRENCIES:
        assert len(entry.code) == 3
        assert entry.code.isalpha()
        assert entry.code.isupper()
        assert entry.name
        assert 1 <= len(entry.symbol) <= 10
        assert 0 <= entry.decimal_places <= 6

    assert _EXCLUDED_NON_TENDER.isdisjoint(by_code)
    for code in _REGIONAL_TENDERS:
        assert code in by_code
    for code in _ZERO_DECIMAL:
        assert by_code[code].decimal_places == 0
    for code in _THREE_DECIMAL:
        assert by_code[code].decimal_places == 3
