from uuid import UUID

from app.cli.renumber_documents import (
    _PADDING,
    _temp_unique_value,
    plan_document_number,
    plan_party_code_updates,
)
from app.erp.accounting.numbering import parse_old_document_number


def test_cli_module_loads() -> None:
    assert _PADDING == 6


def test_old_numbers_are_detected_for_rewrite() -> None:
    assert parse_old_document_number("SO-2026-000001") == ("SO", 2026, 1)
    assert parse_old_document_number("SOAGM26000001") is None


def test_old_hyphenated_numbers_are_rewritten() -> None:
    new_number, seq = plan_document_number(
        "SO-2026-000006",
        prefix="SO",
        fiscal_year=2026,
        party_code="AGM",
        has_party=True,
    )
    assert new_number == "SOAGM26000006"
    assert seq == 6


def test_internal_old_numbers_omit_party() -> None:
    new_number, seq = plan_document_number(
        "JV-2026-000001",
        prefix="JV",
        fiscal_year=2026,
        party_code=None,
        has_party=False,
    )
    assert new_number == "JV26000001"
    assert seq == 1


def test_compact_numbers_are_not_rewritten() -> None:
    new_number, seq = plan_document_number(
        "SOAGM26000006",
        prefix="SO",
        fiscal_year=2026,
        party_code="XXX",
        has_party=True,
    )
    assert new_number is None
    assert seq == 6


def test_two_phase_party_updates_avoid_unique_index_clash() -> None:
    first = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    second = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    codes, planned = plan_party_code_updates(
        [
            (first, "Acme Global Motors", "CUS202601"),
            (second, "Acme Global Manufacturing", "AGM"),
        ],
        [],
    )
    assert codes[first] == "AGM"
    assert codes[second] == "AGN"
    assert {party_id for party_id, _code in planned} == {first, second}
    temps = [_temp_unique_value(party_id) for party_id, _code in planned]
    assert len(set(temps)) == 2
    assert all(len(value) <= 40 for value in temps)
    assert set(codes.values()).isdisjoint(temps)
    finals = [code for _party_id, code in planned]
    assert len(finals) == len(set(finals))


def test_matching_three_letter_codes_are_skipped() -> None:
    party_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    codes, planned = plan_party_code_updates(
        [(party_id, "Acme Global Motors", "AGM")],
        ["ZZZ"],
    )
    assert codes[party_id] == "AGM"
    assert planned == []
