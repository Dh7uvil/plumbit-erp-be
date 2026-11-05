"""Legacy account-statement row consolidation (one net line per business document)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.common.utils.currency import quantize_money
from app.core.enums import AccountType
from app.erp.accounting.reports.schemas import AccountStatementLine

_ZERO = Decimal("0")
_DEBIT_NORMAL = frozenset({AccountType.ASSET.value, AccountType.EXPENSE.value})

# Source types where reposts/reversals share source_id and should merge on SOA.
# Same debit/credit columns as supplier statement (credit = cost sheet / bill, debit = payment).
VOUCHER_JOURNAL_SOURCE_TYPES = frozenset(
    {
        "journal_voucher",
        "contra_voucher",
        "cash_receipt_voucher",
        "cash_payment_voucher",
        "bank_receipt_voucher",
        "bank_payment_voucher",
        "payment_voucher",
        "general_purchase_voucher",
    }
)

SUPPLIER_STATEMENT_PRESENTATION_SOURCES = frozenset(
    {"cost_sheet", "supplier_payment", *VOUCHER_JOURNAL_SOURCE_TYPES}
)

# One statement row per posted journal line on the selected account (cost sheets, vouchers, …).
STATEMENT_LINE_LEVEL_SOURCES = frozenset(
    {
        "cost_sheet",
        "supplier_payment",
        "customer_payment",
        *VOUCHER_JOURNAL_SOURCE_TYPES,
    }
)

# Party document statements: journal-backed lines (exclude payments — those use payment documents).
PARTY_JOURNAL_LINE_SOURCES = frozenset({"cost_sheet", *VOUCHER_JOURNAL_SOURCE_TYPES})

# Cost sheet / voucher rows: keep document debit-credit columns (not supplier-style flip).
DOCUMENT_LINE_SOURCES = frozenset({"cost_sheet", *VOUCHER_JOURNAL_SOURCE_TYPES})

# Manual journals and storno entries — not listed on account SOA.
ACCOUNT_STATEMENT_HIDDEN_SOURCES = frozenset({"journal_entry"})

STATEMENT_DOCUMENT_SOURCES = frozenset(
    {
        "cost_sheet",
        "purchase_invoice",
        "sales_invoice",
        "credit_note",
        "debit_note",
        "customer_payment",
        "supplier_payment",
        "customer_payment_allocation",
        "supplier_payment_allocation",
        "customer_payment_refund",
        "supplier_payment_refund",
        "sales_invoice_write_off",
        "purchase_invoice_write_off",
        "goods_receipt",
        "delivery_note",
        "sales_return",
        "purchase_return",
        "stock_adjustment",
        "goods_receipt_charge_adjustment",
        "quality_inspection",
        "cheque_issue",
        "cheque_clear",
        "cheque_allocation",
        "voucher_allocation",
        "journal_voucher",
        "contra_voucher",
        "cash_receipt_voucher",
        "cash_payment_voucher",
        "bank_receipt_voucher",
        "bank_payment_voucher",
        "payment_voucher",
        "general_purchase_voucher",
        "fx_revaluation",
        "landed_cost",
    }
)


def _delta(account_type: str, debit: Decimal, credit: Decimal) -> Decimal:
    if account_type in _DEBIT_NORMAL:
        return quantize_money(debit - credit)
    return quantize_money(credit - debit)


def net_statement_debit_credit(
    account_type: str | None,
    debit: Decimal,
    credit: Decimal,
) -> tuple[Decimal, Decimal]:
    """One-sided debit/credit for legacy SOA rows (net movement on the account)."""

    if account_type is None:
        net = quantize_money(debit - credit)
        if net >= _ZERO:
            return net, _ZERO
        return _ZERO, quantize_money(-net)
    net = _delta(account_type, debit, credit)
    if account_type in _DEBIT_NORMAL:
        if net >= _ZERO:
            return quantize_money(net), _ZERO
        return _ZERO, quantize_money(-net)
    if net >= _ZERO:
        return _ZERO, quantize_money(net)
    return quantize_money(-net), _ZERO


def statement_line_net(
    line: AccountStatementLine, *, account_type: str | None
) -> Decimal:
    if line.source_type in DOCUMENT_LINE_SOURCES:
        if account_type is not None:
            return _delta(account_type, line.debit, line.credit)
        return quantize_money(line.debit - line.credit)
    if line.source_type in SUPPLIER_STATEMENT_PRESENTATION_SOURCES:
        return statement_line_net_supplier(line)
    if account_type is not None:
        return _delta(account_type, line.debit, line.credit)
    return quantize_money(line.debit - line.credit)


def statement_line_net_supplier(line: AccountStatementLine) -> Decimal:
    return quantize_money(line.credit - line.debit)


def document_line_merged_debit_credit(
    gross_debit: Decimal,
    gross_credit: Decimal,
) -> tuple[Decimal, Decimal]:
    """Net repost/reversal chains; keep amount in the column used on the cost sheet / voucher."""

    if gross_debit >= gross_credit:
        return quantize_money(gross_debit - gross_credit), _ZERO
    return _ZERO, quantize_money(gross_credit - gross_debit)


def net_supplier_statement_debit_credit(
    debit: Decimal,
    credit: Decimal,
) -> tuple[Decimal, Decimal]:
    net = quantize_money(credit - debit)
    if net >= _ZERO:
        return _ZERO, quantize_money(net)
    return quantize_money(-net), _ZERO


def _merge_line_group(
    group: list[AccountStatementLine],
    *,
    account_type: str | None,
    ) -> AccountStatementLine:
    if not group:
        raise ValueError("cannot merge empty statement line group")
    anchor = next(
        (line for line in group if line.source_type == "cost_sheet"),
        group[0],
    )
    gross_debit = sum((line.debit for line in group), _ZERO)
    gross_credit = sum((line.credit for line in group), _ZERO)
    if anchor.source_type in DOCUMENT_LINE_SOURCES:
        has_storno = any(line.source_type == "journal_entry" for line in group)
        cost_sheet_lines = [line for line in group if line.source_type == "cost_sheet"]
        if (
            anchor.source_type == "cost_sheet"
            and not has_storno
            and len(cost_sheet_lines) > 1
        ):
            winner = max(
                cost_sheet_lines,
                key=lambda line: (line.entry_date, str(line.journal_entry_id or "")),
            )
            debit, credit = winner.debit, winner.credit
        else:
            debit, credit = document_line_merged_debit_credit(gross_debit, gross_credit)
    elif anchor.source_type in SUPPLIER_STATEMENT_PRESENTATION_SOURCES:
        debit, credit = net_supplier_statement_debit_credit(gross_debit, gross_credit)
    else:
        debit, credit = net_statement_debit_credit(account_type, gross_debit, gross_credit)
    description = next(
        (line.description for line in group if line.description),
        anchor.description,
    )
    return anchor.model_copy(
        update={
            "debit": debit,
            "credit": credit,
            "description": description,
            "entry_date": min(line.entry_date for line in group),
        }
    )


def _expand_journal_chain(
    lines: list[AccountStatementLine],
    group: list[AccountStatementLine],
    journal_ids: set[UUID],
    used_journal_ids: set[UUID],
    reversal_of: dict[UUID, UUID],
) -> None:
    expanded = True
    while expanded:
        expanded = False
        for jid in list(journal_ids):
            rev_of = reversal_of.get(jid)
            if rev_of is not None:
                journal_ids.add(rev_of)
        for line in lines:
            jid = line.journal_entry_id
            if jid is None or jid in used_journal_ids:
                continue
            if jid in journal_ids:
                continue
            rev_of = reversal_of.get(jid)
            if rev_of is not None and rev_of in journal_ids:
                group.append(line)
                journal_ids.add(jid)
                expanded = True
                continue
            if line.source_type == "journal_entry" and line.source_id in journal_ids:
                group.append(line)
                journal_ids.add(jid)
                expanded = True


def _collect_document_line_chain(
    lines: list[AccountStatementLine],
    *,
    source_type: str,
    source_id: UUID,
    line_number: int | None,
    used_line_slots: set[tuple[UUID, int | None]],
    reversal_of: dict[UUID, UUID],
) -> list[AccountStatementLine]:
    group = [
        line
        for line in lines
        if line.source_type == source_type
        and line.source_id == source_id
        and line.journal_line_number == line_number
        and (
            line.journal_entry_id is None
            or (line.journal_entry_id, line.journal_line_number) not in used_line_slots
        )
    ]
    journal_ids = {line.journal_entry_id for line in group if line.journal_entry_id}
    _expand_journal_chain_for_line(
        lines, group, journal_ids, used_line_slots, reversal_of, line_number
    )
    for line in group:
        if line.journal_entry_id and line.source_type != source_type:
            used_line_slots.add((line.journal_entry_id, line.journal_line_number))
    return group


def _expand_journal_chain_for_line(
    lines: list[AccountStatementLine],
    group: list[AccountStatementLine],
    journal_ids: set[UUID],
    used_line_slots: set[tuple[UUID, int | None]],
    reversal_of: dict[UUID, UUID],
    line_number: int | None,
) -> None:
    expanded = True
    while expanded:
        expanded = False
        for jid in list(journal_ids):
            rev_of = reversal_of.get(jid)
            if rev_of is not None:
                journal_ids.add(rev_of)
        for line in lines:
            jid = line.journal_entry_id
            if jid is None or (jid, line_number) in used_line_slots:
                continue
            if line.journal_line_number != line_number:
                continue
            if jid in journal_ids:
                continue
            rev_of = reversal_of.get(jid)
            if rev_of is not None and rev_of in journal_ids:
                group.append(line)
                journal_ids.add(jid)
                expanded = True
                continue
            if line.source_type == "journal_entry" and line.source_id in journal_ids:
                group.append(line)
                journal_ids.add(jid)
                expanded = True


def consolidate_account_statement_lines(
    lines: list[AccountStatementLine],
    *,
    account_type: str | None,
    reversal_of: dict[UUID, UUID] | None = None,
) -> list[AccountStatementLine]:
    """One net row per business document; drop same-period net-zero post/reversal chains."""

    if not lines:
        return lines

    reversal_of = reversal_of or {}
    used_journal_ids: set[UUID] = set()
    used_line_slots: set[tuple[UUID, int | None]] = set()
    consolidated: list[AccountStatementLine] = []

    document_line_keys = {
        (line.source_type, line.source_id, line.journal_line_number)
        for line in lines
        if line.source_type in STATEMENT_LINE_LEVEL_SOURCES
        and line.source_id is not None
    }
    processed_document_lines: set[tuple[str, UUID, int | None]] = set()
    for doc_type, doc_id, line_number in document_line_keys:
        group = _collect_document_line_chain(
            lines,
            source_type=doc_type,
            source_id=doc_id,
            line_number=line_number,
            used_line_slots=used_line_slots,
            reversal_of=reversal_of,
        )
        if not group:
            continue
        merged = _merge_line_group(group, account_type=account_type)
        if statement_line_net(merged, account_type=account_type) == _ZERO:
            processed_document_lines.add((doc_type, doc_id, line_number))
            continue
        consolidated.append(merged)
        processed_document_lines.add((doc_type, doc_id, line_number))

    doc_keys: set[tuple[str, UUID]] = set()
    for line in lines:
        if line.journal_entry_id and line.journal_entry_id in used_journal_ids:
            continue
        if (
            line.source_type in STATEMENT_DOCUMENT_SOURCES
            and line.source_id is not None
            and line.source_type not in STATEMENT_LINE_LEVEL_SOURCES
        ):
            doc_keys.add((line.source_type, line.source_id))

    for doc_type, doc_id in doc_keys:
        group = [
            line
            for line in lines
            if line.source_type == doc_type
            and line.source_id == doc_id
            and (line.journal_entry_id is None or line.journal_entry_id not in used_journal_ids)
        ]
        journal_ids = {line.journal_entry_id for line in group if line.journal_entry_id}
        _expand_journal_chain(lines, group, journal_ids, used_journal_ids, reversal_of)
        for line in group:
            if line.journal_entry_id:
                used_journal_ids.add(line.journal_entry_id)
        if not group:
            continue
        merged = _merge_line_group(group, account_type=account_type)
        if statement_line_net(merged, account_type=account_type) == _ZERO:
            continue
        consolidated.append(merged)

    for line in lines:
        if line.journal_entry_id and line.journal_entry_id in used_journal_ids:
            continue
        if line.source_type == "journal_entry":
            continue
        if (
            line.source_type in STATEMENT_LINE_LEVEL_SOURCES
            and line.source_id is not None
            and (line.source_type, line.source_id, line.journal_line_number)
            in processed_document_lines
        ):
            continue
        consolidated.append(line)
        if line.journal_entry_id:
            used_journal_ids.add(line.journal_entry_id)

    return consolidated
