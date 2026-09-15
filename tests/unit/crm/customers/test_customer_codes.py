import pytest
from pydantic import ValidationError

from app.core.enums import TaxTreatment
from app.crm.customers.codes import candidate_party_code, unique_party_code
from app.crm.customers.schemas import CustomerCreate


def test_three_word_name_uses_initials() -> None:
    assert candidate_party_code("Acme Global Motors") == "AGM"


def test_two_word_name_fills_from_longer_word() -> None:
    assert candidate_party_code("Al Ghandi") == "AGH"


def test_one_word_uses_first_three_letters() -> None:
    assert candidate_party_code("Acme") == "ACM"


def test_short_word_is_padded() -> None:
    assert candidate_party_code("AB") == "ABX"


def test_legal_suffixes_are_skipped() -> None:
    assert candidate_party_code("Acme Global Motors LLC") == "AGM"
    assert candidate_party_code("The Acme") == "ACM"


def test_empty_name_falls_back_to_xxx() -> None:
    assert candidate_party_code("   ") == "XXX"


def test_collision_walks_last_character() -> None:
    assert unique_party_code("Acme Global Motors", ["AGM"]) == "AGN"


def test_customer_create_allows_omitted_and_blank_code() -> None:
    omitted = CustomerCreate(name="Acme", tax_treatment=TaxTreatment.UNREGISTERED)
    assert omitted.code is None
    blank = CustomerCreate(name="Acme", tax_treatment=TaxTreatment.UNREGISTERED, code="  ")
    assert blank.code is None
    explicit = CustomerCreate(name="Acme", tax_treatment=TaxTreatment.UNREGISTERED, code="ag1")
    assert explicit.code == "AG1"


def test_customer_create_rejects_non_three_character_code() -> None:
    with pytest.raises(ValidationError):
        CustomerCreate(name="Acme", tax_treatment=TaxTreatment.UNREGISTERED, code="C-1")
