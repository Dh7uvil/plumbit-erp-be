from app.erp.accounting.numbering import (
    format_document_number,
    parse_compact_sequence,
    parse_old_document_number,
)
from app.erp.quotation.service import _display_number


def test_format_includes_party_and_two_digit_year() -> None:
    assert (
        format_document_number(
            prefix="SO",
            party_code="AGM",
            fiscal_year=2026,
            number=6,
            padding=6,
        )
        == "SOAGM26000006"
    )


def test_format_omits_party_for_internal_documents() -> None:
    assert (
        format_document_number(
            prefix="JV",
            party_code=None,
            fiscal_year=2026,
            number=1,
            padding=6,
        )
        == "JV26000001"
    )


def test_parse_old_hyphenated_number() -> None:
    assert parse_old_document_number("SO-2026-000006") == ("SO", 2026, 6)


def test_parse_compact_sequence_with_and_without_party() -> None:
    assert parse_compact_sequence("SOAGM26000006", prefix="SO", has_party=True) == 6
    assert parse_compact_sequence("JV26000001", prefix="JV", has_party=False) == 1


def test_quotation_revision_display_has_no_hyphen() -> None:
    assert _display_number("QUOAGM26000001", 0) == "QUOAGM26000001"
    assert _display_number("QUOAGM26000001", 1) == "QUOAGM26000001R1"
