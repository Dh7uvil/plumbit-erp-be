from app.core.enums import TaxTreatment
from app.crm.customers.repository import next_party_code_from_existing
from app.crm.customers.schemas import CustomerCreate


def test_first_customer_code_is_padded_01() -> None:
    assert next_party_code_from_existing([], prefix="CUS", year=2026) == "CUS202601"


def test_sequence_increments_with_two_digit_padding() -> None:
    assert next_party_code_from_existing(["CUS202601"], prefix="CUS", year=2026) == "CUS202602"


def test_prior_year_codes_do_not_affect_current_year() -> None:
    assert next_party_code_from_existing(["CUS202599"], prefix="CUS", year=2026) == "CUS202601"


def test_sequence_grows_past_two_digits() -> None:
    assert next_party_code_from_existing(["CUS202699"], prefix="CUS", year=2026) == "CUS2026100"


def test_other_prefixes_are_ignored() -> None:
    assert next_party_code_from_existing(["SUP202601", "C-1"], prefix="CUS", year=2026) == (
        "CUS202601"
    )


def test_customer_create_allows_omitted_and_blank_code() -> None:
    omitted = CustomerCreate(name="Acme", tax_treatment=TaxTreatment.UNREGISTERED)
    assert omitted.code is None
    blank = CustomerCreate(name="Acme", tax_treatment=TaxTreatment.UNREGISTERED, code="  ")
    assert blank.code is None
    explicit = CustomerCreate(name="Acme", tax_treatment=TaxTreatment.UNREGISTERED, code="c-1")
    assert explicit.code == "C-1"
