"""Account statement legacy consolidation (cost sheet chains, document merges)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.core.enums import AccountType
from app.erp.accounting.reports.account_statement_consolidation import (
    consolidate_account_statement_lines,
)
from app.erp.accounting.reports.schemas import AccountStatementLine

_ZERO = Decimal("0")
_SHEET = uuid4()
_J1 = uuid4()
_J2 = uuid4()


def _line(
    *,
    journal_id,
    doc: str,
    source_type: str,
    source_id,
    debit: str,
    credit: str,
    line_number: int = 1,
) -> AccountStatementLine:
    return AccountStatementLine(
        journal_entry_id=journal_id,
        journal_line_number=line_number,
        document_number=doc,
        entry_date=date(2026, 11, 5),
        due_date=None,
        external_reference=None,
        debit=Decimal(debit),
        credit=Decimal(credit),
        running_balance=_ZERO,
        description=None,
        voucher_code="CSI" if source_type == "cost_sheet" else "JV",
        source_type=source_type,
        source_id=source_id,
        balance_side=None,
    )


def test_consolidates_cost_sheet_and_linked_reversal_to_net_zero() -> None:
    lines = [
        _line(
            journal_id=_J1,
            doc="JV1",
            source_type="cost_sheet",
            source_id=_SHEET,
            debit="0",
            credit="1500.0000",
        ),
        _line(
            journal_id=_J2,
            doc="JV2",
            source_type="journal_entry",
            source_id=_J1,
            debit="1500.0000",
            credit="0",
        ),
    ]
    merged = consolidate_account_statement_lines(
        lines, account_type=AccountType.EXPENSE.value
    )
    assert merged == []


def test_consolidates_repeated_cost_sheet_posts_to_one_net_line() -> None:
    j3, j4, j5, j6, j7 = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    lines = [
        _line(journal_id=j3, doc="JV3", source_type="cost_sheet", source_id=_SHEET, debit="0", credit="1500"),
        _line(journal_id=j4, doc="JV4", source_type="journal_entry", source_id=j3, debit="1500", credit="0"),
        _line(journal_id=j5, doc="JV5", source_type="cost_sheet", source_id=_SHEET, debit="0", credit="1500"),
        _line(journal_id=j6, doc="JV6", source_type="journal_entry", source_id=j5, debit="1500", credit="0"),
        _line(
            journal_id=j7,
            doc="JV7",
            source_type="cost_sheet",
            source_id=_SHEET,
            debit="0",
            credit="1500",
            line_number=1,
        ),
    ]
    merged = consolidate_account_statement_lines(
        lines, account_type=AccountType.EXPENSE.value
    )
    assert len(merged) == 1


def test_reposted_cost_sheet_nets_reversal_journals_per_line() -> None:
    sheet = uuid4()
    j_old, j_rev, j_new = uuid4(), uuid4(), uuid4()
    lines = [
        _line(
            journal_id=j_old,
            doc="JV1",
            source_type="cost_sheet",
            source_id=sheet,
            debit="1000",
            credit="0",
            line_number=1,
        ),
        _line(
            journal_id=j_old,
            doc="JV1",
            source_type="cost_sheet",
            source_id=sheet,
            debit="500",
            credit="0",
            line_number=2,
        ),
        _line(
            journal_id=j_rev,
            doc="JV2",
            source_type="journal_entry",
            source_id=j_old,
            debit="0",
            credit="1000",
            line_number=1,
        ),
        _line(
            journal_id=j_rev,
            doc="JV2",
            source_type="journal_entry",
            source_id=j_old,
            debit="0",
            credit="500",
            line_number=2,
        ),
        _line(
            journal_id=j_new,
            doc="JV3",
            source_type="cost_sheet",
            source_id=sheet,
            debit="1000",
            credit="0",
            line_number=1,
        ),
        _line(
            journal_id=j_new,
            doc="JV3",
            source_type="cost_sheet",
            source_id=sheet,
            debit="500",
            credit="0",
            line_number=2,
        ),
    ]
    merged = consolidate_account_statement_lines(
        lines, account_type=AccountType.EXPENSE.value
    )
    assert len(merged) == 2
    debits = sorted(row.debit for row in merged)
    assert debits == [Decimal("500.0000"), Decimal("1000.0000")]


def test_duplicate_cost_sheet_posts_use_latest_line_not_gross_sum() -> None:
    """Stale repost orphans must not inflate document-line amounts."""
    old, new = uuid4(), uuid4()
    lines = [
        _line(
            journal_id=old,
            doc="CSI1",
            source_type="cost_sheet",
            source_id=_SHEET,
            debit="0",
            credit="1000",
            line_number=2,
        ),
        _line(
            journal_id=new,
            doc="CSI1",
            source_type="cost_sheet",
            source_id=_SHEET,
            debit="0",
            credit="1000",
            line_number=2,
        ),
    ]
    merged = consolidate_account_statement_lines(
        lines, account_type=AccountType.EXPENSE.value
    )
    assert len(merged) == 1
    assert merged[0].credit == Decimal("1000.0000")
    assert merged[0].debit == Decimal("0.0000")


def test_document_line_merge_preserves_cost_sheet_credit_column() -> None:
    lines = [
        _line(
            journal_id=uuid4(),
            doc="JV1",
            source_type="cost_sheet",
            source_id=_SHEET,
            debit="0",
            credit="1000",
            line_number=1,
        ),
    ]
    merged = consolidate_account_statement_lines(
        lines, account_type=AccountType.EXPENSE.value
    )
    assert len(merged) == 1
    assert merged[0].debit == Decimal("0.0000")
    assert merged[0].credit == Decimal("1000.0000")


def test_keeps_separate_cost_sheet_lines_on_same_sheet() -> None:
    j1, j2 = uuid4(), uuid4()
    lines = [
        _line(
            journal_id=j1,
            doc="JV1",
            source_type="cost_sheet",
            source_id=_SHEET,
            debit="100",
            credit="0",
            line_number=1,
        ),
        _line(
            journal_id=j1,
            doc="JV1",
            source_type="cost_sheet",
            source_id=_SHEET,
            debit="200",
            credit="0",
            line_number=2,
        ),
    ]
    merged = consolidate_account_statement_lines(
        lines, account_type=AccountType.EXPENSE.value
    )
    assert len(merged) == 2
    debits = sorted(row.debit for row in merged)
    assert debits == [Decimal("100.0000"), Decimal("200.0000")]


def test_links_reversal_via_reversal_of_id_when_source_id_missing() -> None:
    original, reversal = uuid4(), uuid4()
    lines = [
        _line(
            journal_id=original,
            doc="JV1",
            source_type="cost_sheet",
            source_id=_SHEET,
            debit="0",
            credit="100",
        ),
        _line(
            journal_id=reversal,
            doc="JV2",
            source_type="journal_entry",
            source_id=uuid4(),
            debit="100",
            credit="0",
        ),
    ]
    merged = consolidate_account_statement_lines(
        lines,
        account_type=AccountType.EXPENSE.value,
        reversal_of={reversal: original},
    )
    assert merged == []


def test_keeps_separate_voucher_lines_on_same_voucher() -> None:
    voucher_id = uuid4()
    j1 = uuid4()
    lines = [
        _line(
            journal_id=j1,
            doc="JV1",
            source_type="journal_voucher",
            source_id=voucher_id,
            debit="100",
            credit="0",
            line_number=1,
        ),
        _line(
            journal_id=j1,
            doc="JV1",
            source_type="journal_voucher",
            source_id=voucher_id,
            debit="200",
            credit="0",
            line_number=2,
        ),
    ]
    merged = consolidate_account_statement_lines(
        lines, account_type=AccountType.EXPENSE.value
    )
    assert len(merged) == 2
    debits = sorted(row.debit for row in merged)
    assert debits == [Decimal("100.0000"), Decimal("200.0000")]


def test_merges_reposted_voucher_journals_by_voucher_source_id() -> None:
    voucher_id = uuid4()
    j1, j2 = uuid4(), uuid4()
    lines = [
        _line(
            journal_id=j1,
            doc="BP1",
            source_type="bank_payment_voucher",
            source_id=voucher_id,
            debit="500",
            credit="0",
        ),
        _line(
            journal_id=j2,
            doc="BP2",
            source_type="bank_payment_voucher",
            source_id=voucher_id,
            debit="200",
            credit="0",
        ),
    ]
    merged = consolidate_account_statement_lines(
        lines, account_type=AccountType.ASSET.value
    )
    assert len(merged) == 1
    assert merged[0].debit == Decimal("700.0000")
    assert merged[0].credit == Decimal("0.0000")
