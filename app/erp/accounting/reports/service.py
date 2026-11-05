"""Trial balance, general ledger, party statements, and Stage I reports."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.registries.unposted_documents import registered_probes
from app.common.schemas.pagination import PageParams
from app.common.utils.currency import quantize_money
from app.common.utils.datetime import utcnow
from app.common.utils.export_evidence import has_export_evidence
from app.core.enums import (
    AccountSubtype,
    AccountType,
    ChequeDirection,
    ChequeStatus,
    CogsStatus,
    CompanyType,
    InvoiceDocumentStatus,
    JournalEntryStatus,
    JournalType,
    OpenItemType,
    PartyType,
    PurchaseOrderStatus,
    StockDocumentStatus,
    VoucherType,
)
from app.core.exceptions import ValidationError
from app.crm.customers.models import Customer
from app.erp.accounting.accounts.service import AccountService
from app.erp.accounting.budgets.schemas import BudgetVsActualResponse
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
from app.erp.accounting.reports.account_statement_consolidation import (
    ACCOUNT_STATEMENT_HIDDEN_SOURCES,
    DOCUMENT_LINE_SOURCES,
    PARTY_JOURNAL_LINE_SOURCES,
    STATEMENT_LINE_LEVEL_SOURCES,
    SUPPLIER_STATEMENT_PRESENTATION_SOURCES,
    STATEMENT_DOCUMENT_SOURCES,
    VOUCHER_JOURNAL_SOURCE_TYPES,
    consolidate_account_statement_lines,
    net_statement_debit_credit,
    net_supplier_statement_debit_credit,
)
from app.erp.accounting.reports.amounts import (
    document_base_grand,
    open_item_base_amount,
    payment_base_amount,
)
from app.erp.accounting.reports.analytical import AnalyticalReports
from app.erp.accounting.reports.financials import FinancialReports
from app.erp.accounting.reports.inventory import InventoryReports
from app.erp.accounting.reports.schemas import (
    AccountStatementLine,
    AccountStatementOpening,
    AccountStatementResponse,
    AgingBucketTotals,
    AgingDocument,
    AgingPartyRow,
    AgingResponse,
    DashboardCreditBreach,
    DashboardResponse,
    DashboardUnpostedCount,
    DayBookAccountSection,
    DayBookLine,
    DayBookResponse,
    ExportEvidenceExceptionLine,
    ExportEvidenceExceptionResponse,
    GeneralLedgerLine,
    GeneralLedgerResponse,
    InvoicedNotDispatchedLine,
    InvoicedNotDispatchedResponse,
    OutstandingDocument,
    OutstandingDocumentsResponse,
    OutstandingSummary,
    PartyStatementLine,
    PartyStatementResponse,
    PdcRegisterLine,
    PdcRegisterResponse,
    ReceivedNotBilledLine,
    ReceivedNotBilledResponse,
    ReportWarning,
    ThreeWayMatchLine,
    ThreeWayMatchResponse,
    TrialBalanceLine,
    TrialBalanceResponse,
)
from app.erp.accounting.reports.tax_registers import TaxRegisters
from app.erp.exchange_rates.service import CurrencyService
from app.erp.sales_invoices.models import SalesInvoice, SalesInvoiceLine

_ZERO = Decimal("0")
_DEBIT_NORMAL = frozenset({AccountType.ASSET.value, AccountType.EXPENSE.value})
EXPORT_EVIDENCE_WINDOW_DAYS = 90
_UNCLEARED_CHEQUE_STATUSES = frozenset(
    {ChequeStatus.ISSUED.value, ChequeStatus.DEPOSITED.value}
)
def _statement_ref_number(
    header: JournalEntry,
    *,
    cost_sheet_document_numbers: dict[UUID, str],
    vouchers_by_id: dict[UUID, object],
    source_type: str | None = None,
    source_id: UUID | None = None,
) -> str:
    resolved_type = source_type if source_type is not None else header.source_type
    resolved_id = source_id if source_id is not None else header.source_id
    if resolved_type == "cost_sheet" and resolved_id is not None:
        return cost_sheet_document_numbers.get(resolved_id, header.document_number)
    if resolved_type in VOUCHER_JOURNAL_SOURCE_TYPES and resolved_id is not None:
        voucher = vouchers_by_id.get(resolved_id)
        if voucher is not None:
            return getattr(voucher, "document_number", header.document_number)
    if resolved_type == "general_purchase_voucher" and resolved_id is not None:
        voucher = vouchers_by_id.get(resolved_id)
        if voucher is not None:
            return getattr(voucher, "document_number", header.document_number)
    return header.document_number


def _account_statement_line_visible(line: AccountStatementLine) -> bool:
    if line.source_type in ACCOUNT_STATEMENT_HIDDEN_SOURCES:
        return False
    if line.source_type is None:
        return False
    if line.voucher_code == "PD" or line.source_type == "cheque":
        return True
    if line.source_type in DOCUMENT_LINE_SOURCES:
        return True
    if line.source_type in STATEMENT_DOCUMENT_SOURCES:
        return True
    return False


def _statement_cheque_number(
    *,
    cheque: object | None,
    entry_line: JournalEntryLine | None = None,
) -> str | None:
    """Cheque column: real cheque metadata only (never cost sheet / voucher document refs)."""

    if cheque is not None:
        return getattr(cheque, "cheque_number", None)
    if entry_line is not None and entry_line.external_reference:
        ref = entry_line.external_reference.strip()
        return ref or None
    return None


_SOURCE_VOUCHER_CODES: dict[str, str] = {
    "journal_entry": "JV",
    "cash_receipt_voucher": "CR",
    "cash_payment_voucher": "CP",
    "bank_receipt_voucher": "BR",
    "bank_payment_voucher": "BP",
    "contra_voucher": "CV",
    "sales_invoice": "SI",
    "purchase_invoice": "PI",
    "credit_note": "CN",
    "debit_note": "DN",
    "customer_payment": "RC",
    "supplier_payment": "SP",
    "customer_payment_allocation": "RC",
    "supplier_payment_allocation": "SP",
    "customer_payment_refund": "RR",
    "supplier_payment_refund": "SR",
    "credit_note_refund": "CN",
    "debit_note_refund": "DN",
    "cheque_issue": "CQ",
    "cheque_clear": "CL",
    "cheque_allocation": "CQ",
    "OPENING_BALANCE": "OB",
    "fx_revaluation": "FX",
    "sales_invoice_write_off": "WO",
    "purchase_invoice_write_off": "WO",
    "cost_sheet": "CS",
    "journal_voucher": "JV",
    "contra_voucher": "CV",
    "cash_receipt_voucher": "CR",
    "cash_payment_voucher": "CP",
    "bank_receipt_voucher": "BR",
    "bank_payment_voucher": "BP",
    "payment_voucher": "PV",
    "general_purchase_voucher": "GP",
}
_JOURNAL_LIKE_VOUCHER_TYPES = frozenset(
    {
        VoucherType.JOURNAL,
        VoucherType.GENERAL_PURCHASE,
        VoucherType.CONTRA,
    }
)
_COST_SHEET_TYPE_CODES: dict[str, str] = {
    "IMPORT": "CSI",
    "EXPORT": "CSE",
    "OTHER": "CSO",
}
def _net_sides(debit: Decimal, credit: Decimal) -> tuple[Decimal, Decimal]:
    net = quantize_money(debit - credit)
    if net >= _ZERO:
        return net, _ZERO
    return _ZERO, quantize_money(-net)


def _balance_side(balance: Decimal) -> str:
    return "DR" if balance >= _ZERO else "CR"


def _voucher_code(source_type: str | None, *, journal_type: str) -> str | None:
    if source_type:
        mapped = _SOURCE_VOUCHER_CODES.get(source_type)
        if mapped:
            return mapped
        compact = source_type.replace("_", "")
        return compact[:2].upper() if compact else None
    if journal_type == JournalType.OPENING_BALANCE.value:
        return "OB"
    return "JV"


def _posted_join():
    return and_(
        JournalEntryLine.journal_entry_id == JournalEntry.id,
        JournalEntry.tenant_id == JournalEntryLine.tenant_id,
        JournalEntry.status == JournalEntryStatus.POSTED.value,
        JournalEntry.deleted_at.is_(None),
    )


class ReportService(InventoryReports, FinancialReports, TaxRegisters, AnalyticalReports):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounts = AccountService(session)
        self.currencies = CurrencyService(session)

    async def _report_currency_code(self, tenant_id: UUID) -> str:
        return (await self.currencies.get_base(tenant_id)).code

    async def trial_balance(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        branch_id: UUID | None = None,
        include_zero: bool = False,
    ) -> TrialBalanceResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        accounts = await self.accounts.repo.list_all(tenant_id)
        opening_map = await self._sum_by_account(
            tenant_id, before=from_date, branch_id=branch_id
        )
        period_map = await self._sum_by_account(
            tenant_id,
            start=from_date,
            end=to_date,
            branch_id=branch_id,
        )
        lines: list[TrialBalanceLine] = []
        tot_od = tot_oc = tot_pd = tot_pc = tot_cd = tot_cc = tot_nd = tot_nc = _ZERO
        for account in accounts:
            if account.is_group and not include_zero:
                continue
            opening = opening_map.get(account.id, (_ZERO, _ZERO))
            period = period_map.get(account.id, (_ZERO, _ZERO))
            closing_d = quantize_money(opening[0] + period[0])
            closing_c = quantize_money(opening[1] + period[1])
            net_d, net_c = _net_sides(closing_d, closing_c)
            if not include_zero and opening == (_ZERO, _ZERO) and period == (_ZERO, _ZERO):
                continue
            lines.append(
                TrialBalanceLine(
                    account_id=account.id,
                    account_code=account.code,
                    account_name=account.name,
                    account_type=account.account_type,
                    is_group=account.is_group,
                    opening_debit=opening[0],
                    opening_credit=opening[1],
                    period_debit=period[0],
                    period_credit=period[1],
                    closing_debit=closing_d,
                    closing_credit=closing_c,
                    closing_net_debit=net_d,
                    closing_net_credit=net_c,
                )
            )
            tot_od += opening[0]
            tot_oc += opening[1]
            tot_pd += period[0]
            tot_pc += period[1]
            tot_cd += closing_d
            tot_cc += closing_c
            tot_nd += net_d
            tot_nc += net_c
        tot_od, tot_oc, tot_pd, tot_pc, tot_cd, tot_cc, tot_nd, tot_nc = (
            quantize_money(tot_od),
            quantize_money(tot_oc),
            quantize_money(tot_pd),
            quantize_money(tot_pc),
            quantize_money(tot_cd),
            quantize_money(tot_cc),
            quantize_money(tot_nd),
            quantize_money(tot_nc),
        )
        return TrialBalanceResponse(
            currency_code=await self._report_currency_code(tenant_id),
            from_date=from_date,
            to_date=to_date,
            is_balanced=tot_cd == tot_cc,
            total_opening_debit=tot_od,
            total_opening_credit=tot_oc,
            total_period_debit=tot_pd,
            total_period_credit=tot_pc,
            total_closing_debit=tot_cd,
            total_closing_credit=tot_cc,
            total_closing_net_debit=tot_nd,
            total_closing_net_credit=tot_nc,
            lines=lines,
        )

    async def general_ledger(
        self,
        tenant_id: UUID,
        *,
        account_id: UUID,
        from_date: date,
        to_date: date,
        party_id: UUID | None = None,
        branch_id: UUID | None = None,
        source_type: str | None = None,
        side: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> GeneralLedgerResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        account = await self.accounts.get(tenant_id, account_id)
        opening_map = await self._sum_by_account(
            tenant_id,
            before=from_date,
            account_id=account_id,
            party_id=party_id,
            branch_id=branch_id,
        )
        opening_d, opening_c = opening_map.get(account_id, (_ZERO, _ZERO))
        running = self._signed(account.account_type, opening_d, opening_c)
        statement = (
            select(JournalEntryLine, JournalEntry)
            .join(JournalEntry, _posted_join())
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntryLine.account_id == account_id,
                JournalEntry.entry_date >= from_date,
                JournalEntry.entry_date <= to_date,
            )
            .order_by(JournalEntry.entry_date.asc(), JournalEntryLine.line_number.asc())
        )
        if party_id is not None:
            statement = statement.where(JournalEntryLine.party_id == party_id)
        if branch_id is not None:
            statement = statement.where(
                (JournalEntryLine.branch_id == branch_id) | (JournalEntry.branch_id == branch_id)
            )
        if source_type:
            statement = statement.where(JournalEntry.source_type == source_type)
        rows = (await self.session.execute(statement)).all()
        lines: list[GeneralLedgerLine] = []
        for line, header in rows:
            if side == "debit" and line.debit_base == _ZERO:
                continue
            if side == "credit" and line.credit_base == _ZERO:
                continue
            running = quantize_money(
                running + self._delta(account.account_type, line.debit_base, line.credit_base)
            )
            lines.append(
                GeneralLedgerLine(
                    journal_entry_id=header.id,
                    journal_entry_line_id=line.id,
                    document_number=header.document_number,
                    entry_date=header.entry_date,
                    source_type=header.source_type,
                    source_id=header.source_id,
                    account_id=line.account_id,
                    debit=line.debit,
                    credit=line.credit,
                    debit_base=line.debit_base,
                    credit_base=line.credit_base,
                    running_balance=running,
                    party_id=line.party_id,
                    description=line.description,
                    narration=header.narration,
                )
            )
        period_debit = sum((line.debit_base for line in lines), _ZERO)
        period_credit = sum((line.credit_base for line in lines), _ZERO)
        total_lines = len(lines)
        page_size_value = page_size
        if page_size is not None:
            start = (max(page, 1) - 1) * page_size
            lines = lines[start : start + page_size]
        return GeneralLedgerResponse(
            currency_code=await self._report_currency_code(tenant_id),
            account_id=account.id,
            account_code=account.code,
            account_name=account.name,
            from_date=from_date,
            to_date=to_date,
            opening_balance=self._signed(account.account_type, opening_d, opening_c),
            closing_balance=running,
            total_debit=quantize_money(period_debit),
            total_credit=quantize_money(period_credit),
            page=page,
            page_size=page_size_value,
            total_lines=total_lines,
            lines=lines,
        )

    async def cash_book(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        account_id: UUID | None = None,
        branch_id: UUID | None = None,
        source_type: str | None = None,
        side: str | None = None,
    ) -> DayBookResponse:
        return await self._day_book(
            tenant_id,
            book_kind="cash",
            account_subtype=AccountSubtype.CASH,
            from_date=from_date,
            to_date=to_date,
            account_id=account_id,
            branch_id=branch_id,
            source_type=source_type,
            side=side,
        )

    async def bank_book(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        account_id: UUID | None = None,
        branch_id: UUID | None = None,
        source_type: str | None = None,
        side: str | None = None,
    ) -> DayBookResponse:
        return await self._day_book(
            tenant_id,
            book_kind="bank",
            account_subtype=AccountSubtype.BANK,
            from_date=from_date,
            to_date=to_date,
            account_id=account_id,
            branch_id=branch_id,
            source_type=source_type,
            side=side,
        )

    async def day_book(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        account_id: UUID | None = None,
        party_id: UUID | None = None,
        branch_id: UUID | None = None,
        source_type: str | None = None,
        voucher_type: str | None = None,
        side: str | None = None,
    ) -> DayBookResponse:
        resolved_source = source_type
        if voucher_type:
            mapping = {
                "CASH_RECEIPT": "cash_receipt_voucher",
                "CASH_PAYMENT": "cash_payment_voucher",
                "BANK_RECEIPT": "bank_receipt_voucher",
                "BANK_PAYMENT": "bank_payment_voucher",
                "CONTRA": "contra_voucher",
            }
            resolved_source = mapping.get(voucher_type, voucher_type)
        return await self._day_book(
            tenant_id,
            book_kind="all",
            account_subtype=None,
            from_date=from_date,
            to_date=to_date,
            account_id=account_id,
            branch_id=branch_id,
            source_type=resolved_source,
            side=side,
            party_id=party_id,
        )

    async def _day_book(
        self,
        tenant_id: UUID,
        *,
        book_kind: str,
        account_subtype: AccountSubtype | None,
        from_date: date,
        to_date: date,
        account_id: UUID | None,
        branch_id: UUID | None,
        source_type: str | None,
        side: str | None,
        party_id: UUID | None = None,
    ) -> DayBookResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        all_accounts = await self.accounts.repo.list_all(tenant_id)
        subtype_accounts = [
            row
            for row in all_accounts
            if not row.is_group
            and row.is_active
            and (account_subtype is None or row.account_subtype == account_subtype.value)
        ]
        if account_id is not None:
            match = next((row for row in subtype_accounts if row.id == account_id), None)
            if match is None:
                account = await self.accounts.get(tenant_id, account_id)
                if account.is_group or not account.is_active:
                    raise ValidationError(
                        "Account must be an active postable account",
                        details={"account_id": str(account_id)},
                    )
                if account_subtype is not None and account.account_subtype != account_subtype.value:
                    raise ValidationError(
                        f"Account must have subtype {account_subtype.value}",
                        details={
                            "account_id": str(account_id),
                            "account_subtype": account.account_subtype,
                        },
                    )
                target_accounts = [account]
            else:
                target_accounts = [match]
        else:
            target_accounts = sorted(subtype_accounts, key=lambda row: row.code)
        sections: list[DayBookAccountSection] = []
        flat_lines: list[DayBookLine] = []
        combined_opening = _ZERO
        combined_closing = _ZERO
        for account in target_accounts:
            opening_map = await self._sum_by_account(
                tenant_id,
                before=from_date,
                account_id=account.id,
                branch_id=branch_id,
            )
            opening_d, opening_c = opening_map.get(account.id, (_ZERO, _ZERO))
            opening_signed = self._signed(account.account_type, opening_d, opening_c)
            movements = await self._ledger_movements(
                tenant_id,
                account_id=account.id,
                from_date=from_date,
                to_date=to_date,
                branch_id=branch_id,
                source_type=source_type,
                side=side,
                party_id=party_id,
            )
            section_lines = self._build_day_book_lines(
                account_id=account.id,
                account_code=account.code,
                account_name=account.name,
                account_type=account.account_type,
                from_date=from_date,
                to_date=to_date,
                opening_signed=opening_signed,
                movements=movements,
            )
            closing_signed = (
                section_lines[-1].running_balance
                if section_lines
                else opening_signed
            )
            if not section_lines and party_id is not None and not movements:
                continue
            sections.append(
                DayBookAccountSection(
                    account_id=account.id,
                    account_code=account.code,
                    account_name=account.name,
                    opening_balance=opening_signed,
                    closing_balance=closing_signed,
                    lines=section_lines,
                )
            )
            flat_lines.extend(section_lines)
            combined_opening = quantize_money(combined_opening + opening_signed)
            combined_closing = quantize_money(combined_closing + closing_signed)
        return DayBookResponse(
            currency_code=await self._report_currency_code(tenant_id),
            book_kind=book_kind,
            from_date=from_date,
            to_date=to_date,
            account_id=account_id,
            combined_opening_balance=combined_opening,
            combined_closing_balance=combined_closing,
            sections=sections,
            lines=flat_lines,
        )

    async def _ledger_movements(
        self,
        tenant_id: UUID,
        *,
        account_id: UUID,
        from_date: date,
        to_date: date,
        branch_id: UUID | None,
        source_type: str | None,
        side: str | None,
        party_id: UUID | None = None,
    ) -> list[tuple[JournalEntryLine, JournalEntry]]:
        statement = (
            select(JournalEntryLine, JournalEntry)
            .join(JournalEntry, _posted_join())
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntryLine.account_id == account_id,
                JournalEntry.entry_date >= from_date,
                JournalEntry.entry_date <= to_date,
            )
            .order_by(
                JournalEntry.entry_date.asc(),
                JournalEntryLine.line_number.asc(),
            )
        )
        if branch_id is not None:
            statement = statement.where(
                (JournalEntryLine.branch_id == branch_id) | (JournalEntry.branch_id == branch_id)
            )
        if source_type:
            statement = statement.where(JournalEntry.source_type == source_type)
        if party_id is not None:
            statement = statement.where(JournalEntryLine.party_id == party_id)
        rows = (await self.session.execute(statement)).all()
        movements: list[tuple[JournalEntryLine, JournalEntry]] = []
        for line, header in rows:
            if side == "debit" and line.debit_base == _ZERO:
                continue
            if side == "credit" and line.credit_base == _ZERO:
                continue
            movements.append((line, header))
        return movements

    def _build_day_book_lines(
        self,
        *,
        account_id: UUID,
        account_code: str,
        account_name: str,
        account_type: str,
        from_date: date,
        to_date: date,
        opening_signed: Decimal,
        movements: list[tuple[JournalEntryLine, JournalEntry]],
    ) -> list[DayBookLine]:
        by_date: dict[date, list[tuple[JournalEntryLine, JournalEntry]]] = defaultdict(list)
        for line, header in movements:
            by_date[header.entry_date].append((line, header))
        lines: list[DayBookLine] = []
        running = opening_signed
        current = from_date
        account_fields = {
            "account_id": account_id,
            "account_code": account_code,
            "account_name": account_name,
        }
        while current <= to_date:
            lines.append(
                DayBookLine(
                    row_type="opening",
                    entry_date=current,
                    running_balance=running,
                    **account_fields,
                )
            )
            day_debit = _ZERO
            day_credit = _ZERO
            for line, header in by_date.get(current, []):
                day_debit = quantize_money(day_debit + line.debit_base)
                day_credit = quantize_money(day_credit + line.credit_base)
                running = quantize_money(
                    running + self._delta(account_type, line.debit_base, line.credit_base)
                )
                lines.append(
                    DayBookLine(
                        row_type="movement",
                        entry_date=current,
                        journal_entry_id=header.id,
                        journal_entry_line_id=line.id,
                        document_number=header.document_number,
                        source_type=header.source_type,
                        source_id=header.source_id,
                        debit=line.debit_base,
                        credit=line.credit_base,
                        running_balance=running,
                        party_id=line.party_id,
                        description=line.description,
                        narration=header.narration,
                        **account_fields,
                    )
                )
            lines.append(
                DayBookLine(
                    row_type="day_total",
                    entry_date=current,
                    debit=day_debit,
                    credit=day_credit,
                    running_balance=running,
                    **account_fields,
                )
            )
            lines.append(
                DayBookLine(
                    row_type="closing",
                    entry_date=current,
                    running_balance=running,
                    **account_fields,
                )
            )
            current += timedelta(days=1)
        return lines

    async def account_statement(
        self,
        tenant_id: UUID,
        *,
        party_type: PartyType | None = None,
        party_id: UUID | None = None,
        account_id: UUID | None = None,
        from_date: date,
        to_date: date,
        include_opening: bool = True,
        include_pdc: bool = False,
        currency_id: UUID | None = None,
    ) -> AccountStatementResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        if party_id is None and party_type is None and account_id is None:
            raise ValidationError("Either party or account_id is required")
        if (party_id is None) != (party_type is None):
            raise ValidationError("party_type and party_id must both be provided")
        if party_id is None and account_id is None:
            raise ValidationError("account_id is required when party is not provided")

        account = None
        account_type: str | None = None
        if account_id is not None:
            account = await self.accounts.get(tenant_id, account_id)
            account_type = account.account_type

        if party_type is not None and party_id is not None and account_id is None:
            party_stmt = await self._party_document_statement(
                tenant_id,
                party_type,
                party_id,
                from_date=from_date,
                to_date=to_date,
                include_opening=include_opening,
                include_pdc=include_pdc,
            )
            return self._account_statement_from_party(
                party_stmt,
                account=None,
                include_opening=include_opening,
            )

        party_type_value = party_type.value if party_type is not None else None
        opening_d, opening_c = await self._sum_statement_opening(
            tenant_id,
            before=from_date,
            party_type=party_type_value,
            party_id=party_id,
            account_id=account_id,
            currency_id=currency_id,
        )
        statement = (
            select(JournalEntryLine, JournalEntry)
            .join(JournalEntry, _posted_join())
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntry.entry_date >= from_date,
                JournalEntry.entry_date <= to_date,
            )
            .order_by(
                JournalEntry.entry_date.asc(),
                JournalEntryLine.due_date.asc().nulls_last(),
                JournalEntryLine.line_number.asc(),
            )
        )
        if party_type_value is not None:
            statement = statement.where(JournalEntryLine.party_type == party_type_value)
        if party_id is not None:
            statement = statement.where(JournalEntryLine.party_id == party_id)
        if account_id is not None:
            statement = statement.where(JournalEntryLine.account_id == account_id)
        if currency_id is not None:
            statement = statement.where(JournalEntryLine.currency_id == currency_id)

        rows = (await self.session.execute(statement)).all()
        cost_sheet_ids_for_filter = {
            header.source_id
            for _, header in rows
            if header.source_type == "cost_sheet" and header.source_id is not None
        }
        cost_sheet_active_journals = await self._cost_sheet_active_journal_ids(
            tenant_id, cost_sheet_ids_for_filter
        )
        if cost_sheet_active_journals:
            rows = [
                pair
                for pair in rows
                if not (
                    pair[1].source_type == "cost_sheet"
                    and pair[1].source_id is not None
                    and (active := cost_sheet_active_journals.get(pair[1].source_id))
                    is not None
                    and pair[1].id != active
                )
            ]
        journal_ids_pre = {header.id for _, header in rows}
        vouchers_by_journal = await self._vouchers_for_journals(
            tenant_id, journal_ids_pre
        )
        voucher_active_journals = {
            voucher.id: voucher.journal_entry_id
            for voucher in vouchers_by_journal.values()
            if voucher.journal_entry_id is not None
        }
        if voucher_active_journals:
            rows = [
                pair
                for pair in rows
                if not self._orphan_voucher_journal(pair[1], voucher_active_journals)
            ]
        use_supplier_balance = party_type == PartyType.SUPPLIER or any(
            header.source_type in SUPPLIER_STATEMENT_PRESENTATION_SOURCES
            for _, header in rows
        )
        if use_supplier_balance:
            opening_signed = quantize_money(opening_d - opening_c)
        elif account_type is not None:
            opening_signed = self._signed(account_type, opening_d, opening_c)
        else:
            opening_signed = quantize_money(opening_d - opening_c)
        running = opening_signed if include_opening else _ZERO

        journal_ids = {header.id for _, header in rows}
        lines_by_journal = await self._journal_entry_lines_grouped(tenant_id, journal_ids)
        cost_sheet_ids = {
            header.source_id
            for _, header in rows
            if header.source_type == "cost_sheet" and header.source_id is not None
        }
        cost_sheet_type_codes, cost_sheet_document_numbers = (
            await self._cost_sheet_statement_meta(tenant_id, cost_sheet_ids)
        )
        voucher_ids = {
            header.source_id
            for _, header in rows
            if header.source_type in VOUCHER_JOURNAL_SOURCE_TYPES
            and header.source_id is not None
        }
        voucher_ids |= {
            header.source_id
            for _, header in rows
            if header.source_type == "journal_entry" and header.source_id is not None
        }
        voucher_ids |= set(vouchers_by_journal.keys())
        vouchers_by_id = await self._vouchers_for_statement(tenant_id, voucher_ids)
        for voucher_id, voucher in vouchers_by_journal.items():
            vouchers_by_id.setdefault(voucher_id, voucher)

        cheque_meta = await self._cheque_meta_for_journals(
            tenant_id,
            [
                header.source_id
                for _, header in rows
                if header.source_type in {"cheque_issue", "cheque_clear"} and header.source_id
            ],
        )

        pending: list[AccountStatementLine] = []
        journal_ids_on_statement: set[UUID] = set()
        supplier_presentation_keys: set[tuple[UUID, int | None]] = set()
        for journal_id, pairs in self._group_journal_lines_by_entry(rows):
            journal_ids_on_statement.add(journal_id)
            header = pairs[0][1]
            statement_source_type, statement_source_id = self._statement_document_source(
                header, vouchers_by_id
            )
            if statement_source_type in STATEMENT_LINE_LEVEL_SOURCES:
                for entry_line, _entry_header in pairs:
                    pending.append(
                        self._account_statement_line_from_journal_line(
                            entry_line,
                            header,
                            statement_source_type=statement_source_type,
                            statement_source_id=statement_source_id,
                            account_type=account_type,
                            party_type=party_type,
                            party_id=party_id,
                            currency_id=currency_id,
                            lines_by_journal=lines_by_journal,
                            vouchers_by_id=vouchers_by_id,
                            cost_sheet_type_codes=cost_sheet_type_codes,
                            cost_sheet_document_numbers=cost_sheet_document_numbers,
                            cheque_meta=cheque_meta,
                            supplier_presentation_keys=supplier_presentation_keys,
                        )
                    )
                continue
            # Reversal/storno journals: per-line rows for consolidation only (not shown on SOA).
            if header.source_type == "journal_entry":
                for entry_line, _entry_header in pairs:
                    pending.append(
                        self._account_statement_line_from_journal_line(
                            entry_line,
                            header,
                            account_type=account_type,
                            party_type=party_type,
                            party_id=party_id,
                            currency_id=currency_id,
                            lines_by_journal=lines_by_journal,
                            vouchers_by_id=vouchers_by_id,
                            cost_sheet_type_codes=cost_sheet_type_codes,
                            cost_sheet_document_numbers=cost_sheet_document_numbers,
                            cheque_meta=cheque_meta,
                            supplier_presentation_keys=supplier_presentation_keys,
                        )
                    )
                continue
            line, _ = pairs[0]
            debit = _ZERO
            credit = _ZERO
            due: date | None = None
            description: str | None = None
            external_reference: str | None = None
            for entry_line, _entry_header in pairs:
                line_debit, line_credit = self._statement_line_amounts(
                    entry_line, currency_id=currency_id
                )
                debit = quantize_money(debit + line_debit)
                credit = quantize_money(credit + line_credit)
                if due is None and entry_line.due_date is not None:
                    due = entry_line.due_date
                if description is None and entry_line.description:
                    description = entry_line.description
                if external_reference is None and entry_line.external_reference:
                    external_reference = entry_line.external_reference
            supplier_amounts = self._supplier_statement_journal_amounts(
                header,
                lines_by_journal.get(journal_id, []),
                vouchers_by_id=vouchers_by_id,
                party_type=party_type,
                party_id=party_id,
                currency_id=currency_id,
            )
            if supplier_amounts is not None:
                debit, credit = supplier_amounts
                supplier_presentation_keys.add((journal_id, None))
            voucher_code = _voucher_code(
                header.source_type, journal_type=header.journal_type
            )
            cheque = cheque_meta.get(header.source_id) if header.source_id else None
            pending.append(
                AccountStatementLine(
                    journal_entry_id=header.id,
                    journal_line_number=None,
                    document_number=_statement_ref_number(
                        header,
                        cost_sheet_document_numbers=cost_sheet_document_numbers,
                        vouchers_by_id=vouchers_by_id,
                    ),
                    entry_date=header.entry_date,
                    due_date=due,
                    external_reference=external_reference,
                    debit=debit,
                    credit=credit,
                    running_balance=_ZERO,
                    description=description or header.narration,
                    voucher_code=voucher_code,
                    source_type=header.source_type,
                    source_id=header.source_id,
                    cheque_number=_statement_cheque_number(cheque=cheque),
                    cheque_date=cheque.cheque_date if cheque is not None else None,
                    cheque_clearing_date=self._cheque_clearing_date(cheque),
                    balance_side=None,
                    narration=header.narration,
                )
            )

        if include_pdc:
            pdc_rows = await self._uncleared_cheques_for_statement(
                tenant_id,
                from_date=from_date,
                to_date=to_date,
                party_type=party_type_value,
                party_id=party_id,
                account_id=account_id,
                currency_id=currency_id,
            )
            for cheque in pdc_rows:
                if (
                    cheque.journal_entry_id is not None
                    and cheque.journal_entry_id in journal_ids_on_statement
                ):
                    continue
                debit, credit = self._pdc_amounts(cheque, currency_id=currency_id)
                entry_date = cheque.due_date or cheque.cheque_date
                pending.append(
                    AccountStatementLine(
                        journal_entry_id=cheque.journal_entry_id,
                        document_number=cheque.document_number,
                        entry_date=entry_date,
                        due_date=cheque.due_date,
                        external_reference=None,
                        debit=debit,
                        credit=credit,
                        running_balance=_ZERO,
                        description=cheque.narration or f"PDC {cheque.cheque_number}",
                        voucher_code="PD",
                        source_type="cheque",
                        source_id=cheque.id,
                        cheque_number=cheque.cheque_number,
                        cheque_date=cheque.cheque_date,
                        cheque_clearing_date=cheque.due_date,
                        balance_side=None,
                        narration=cheque.narration,
                    )
                )

        reversal_of: dict[UUID, UUID] = {}
        for _, header in rows:
            if header.reversal_of_id is not None:
                reversal_of[header.id] = header.reversal_of_id
        pending = consolidate_account_statement_lines(
            pending,
            account_type=account_type,
            reversal_of=reversal_of,
        )

        pending.sort(
            key=lambda row: (
                row.entry_date,
                row.due_date or row.entry_date,
                row.document_number,
            )
        )
        lines: list[AccountStatementLine] = []
        running = opening_signed if include_opening else _ZERO
        for row in pending:
            if row.journal_entry_id is not None and (
                (row.journal_entry_id, row.journal_line_number)
                in supplier_presentation_keys
                or (row.journal_entry_id, None) in supplier_presentation_keys
            ):
                running = quantize_money(running + row.debit - row.credit)
            elif account_type is not None:
                running = quantize_money(
                    running + self._delta(account_type, row.debit, row.credit)
                )
            else:
                running = quantize_money(running + row.debit - row.credit)
            lines.append(
                row.model_copy(
                    update={
                        "running_balance": running,
                        "balance_side": _balance_side(running),
                    }
                )
            )

        visible_lines = [line for line in lines if _account_statement_line_visible(line)]
        total_debit = sum((line.debit for line in visible_lines), _ZERO)
        total_credit = sum((line.credit for line in visible_lines), _ZERO)
        lines = visible_lines

        currency_code = await self._statement_currency_code(tenant_id, currency_id)
        opening_row = None
        if include_opening and opening_signed != _ZERO:
            opening_row = AccountStatementOpening(
                entry_date=from_date,
                debit=_ZERO,
                credit=_ZERO,
                running_balance=opening_signed,
                balance_side=_balance_side(opening_signed),
            )

        return AccountStatementResponse(
            currency_code=currency_code,
            party_type=party_type_value,
            party_id=party_id,
            account_id=account.id if account is not None else None,
            account_code=account.code if account is not None else None,
            account_name=account.name if account is not None else None,
            from_date=from_date,
            to_date=to_date,
            opening_balance=opening_signed,
            closing_balance=running,
            total_debit=total_debit,
            total_credit=total_credit,
            opening=opening_row,
            lines=lines,
        )

    async def pdc_register(
        self,
        tenant_id: UUID,
        *,
        due_date_from: date | None = None,
        due_date_to: date | None = None,
        direction: str | None = None,
        status: str | None = None,
        bank_account_id: UUID | None = None,
    ) -> PdcRegisterResponse:
        from app.erp.accounting.bank_accounts.models import BankAccount
        from app.erp.accounting.cheques.models import Cheque

        due_or_cheque = func.coalesce(Cheque.due_date, Cheque.cheque_date)
        statement = select(Cheque, BankAccount).join(
            BankAccount,
            (BankAccount.id == Cheque.bank_account_id) & (BankAccount.tenant_id == tenant_id),
        ).where(
            Cheque.tenant_id == tenant_id,
            Cheque.deleted_at.is_(None),
        )
        if due_date_from is not None:
            statement = statement.where(due_or_cheque >= due_date_from)
        if due_date_to is not None:
            statement = statement.where(due_or_cheque <= due_date_to)
        if direction is not None:
            statement = statement.where(Cheque.direction == direction)
        if status is not None:
            statement = statement.where(Cheque.status == status)
        else:
            statement = statement.where(Cheque.status.in_(tuple(_UNCLEARED_CHEQUE_STATUSES)))
        if bank_account_id is not None:
            statement = statement.where(Cheque.bank_account_id == bank_account_id)
        statement = statement.order_by(due_or_cheque.asc(), Cheque.document_number.asc())
        rows = (await self.session.execute(statement)).all()

        party_ids = {cheque.party_id for cheque, _ in rows if cheque.party_id}
        party_names: dict[UUID, str] = {}
        if party_ids:
            party_names = {
                row[0]: row[1]
                for row in (
                    await self.session.execute(
                        select(Customer.id, Customer.name).where(
                            Customer.tenant_id == tenant_id,
                            Customer.id.in_(list(party_ids)),
                        )
                    )
                ).all()
            }

        lines: list[PdcRegisterLine] = []
        total_inbound = _ZERO
        total_outbound = _ZERO
        for cheque, bank in rows:
            party_name = (
                party_names.get(cheque.party_id) if cheque.party_id is not None else None
            )
            if cheque.direction == ChequeDirection.INBOUND.value:
                total_inbound = quantize_money(total_inbound + cheque.amount)
            else:
                total_outbound = quantize_money(total_outbound + cheque.amount)
            lines.append(
                PdcRegisterLine(
                    cheque_id=cheque.id,
                    document_number=cheque.document_number,
                    cheque_number=cheque.cheque_number,
                    direction=cheque.direction,
                    status=cheque.status,
                    cheque_date=cheque.cheque_date,
                    due_date=cheque.due_date,
                    amount=cheque.amount,
                    party_type=cheque.party_type,
                    party_id=cheque.party_id,
                    party_name=party_name,
                    bank_account_id=cheque.bank_account_id,
                    bank_name=bank.bank_name,
                )
            )
        return PdcRegisterResponse(
            currency_code=await self._report_currency_code(tenant_id),
            from_date=due_date_from,
            to_date=due_date_to,
            total_inbound=total_inbound,
            total_outbound=total_outbound,
            lines=lines,
        )

    async def export_evidence_exceptions(
        self,
        tenant_id: UUID,
        *,
        as_of: date | None = None,
    ) -> ExportEvidenceExceptionResponse:
        as_of_date = as_of or utcnow().date()
        statement = (
            select(SalesInvoice)
            .where(
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                SalesInvoice.is_export.is_(True),
            )
            .options(selectinload(SalesInvoice.lines))
            .order_by(SalesInvoice.invoice_date, SalesInvoice.document_number)
        )
        invoices = list((await self.session.execute(statement)).scalars().unique().all())
        customer_ids = {row.customer_id for row in invoices}
        names: dict[UUID, str] = {}
        if customer_ids:
            name_rows = (
                await self.session.execute(
                    select(Customer.id, Customer.name).where(
                        Customer.tenant_id == tenant_id,
                        Customer.id.in_(list(customer_ids)),
                    )
                )
            ).all()
            names = {row[0]: row[1] for row in name_rows}
        lines: list[ExportEvidenceExceptionLine] = []
        for invoice in invoices:
            dn_ids = list(
                {
                    line.delivery_note_id
                    for line in invoice.lines
                    if line.delivery_note_id is not None
                }
            )
            evidence_ok = bool(dn_ids) and await has_export_evidence(
                self.session, tenant_id, dn_ids
            )
            if evidence_ok:
                continue
            days_elapsed = (as_of_date - invoice.invoice_date).days
            lines.append(
                ExportEvidenceExceptionLine(
                    sales_invoice_id=invoice.id,
                    document_number=invoice.document_number,
                    invoice_date=invoice.invoice_date,
                    customer_id=invoice.customer_id,
                    customer_name=names.get(invoice.customer_id, ""),
                    grand_total=document_base_grand(invoice),
                    days_elapsed=days_elapsed,
                    window_days=EXPORT_EVIDENCE_WINDOW_DAYS,
                    overdue=days_elapsed > EXPORT_EVIDENCE_WINDOW_DAYS,
                )
            )
        return ExportEvidenceExceptionResponse(
            currency_code=await self._report_currency_code(tenant_id),
            as_of=as_of_date,
            window_days=EXPORT_EVIDENCE_WINDOW_DAYS,
            lines=lines,
        )

    async def invoiced_not_dispatched(self, tenant_id: UUID) -> InvoicedNotDispatchedResponse:
        statement = (
            select(
                SalesInvoice.id,
                SalesInvoiceLine.id,
                SalesInvoice.document_number,
                SalesInvoice.invoice_date,
                SalesInvoice.customer_id,
                Customer.name,
                SalesInvoiceLine.product_id,
                SalesInvoiceLine.description,
                SalesInvoiceLine.quantity,
                SalesInvoiceLine.amount,
                SalesInvoiceLine.cogs_status,
                SalesInvoice.exchange_rate,
            )
            .select_from(SalesInvoiceLine)
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.sales_invoice_id)
            .join(Customer, Customer.id == SalesInvoice.customer_id)
            .where(
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                SalesInvoiceLine.tenant_id == tenant_id,
                SalesInvoiceLine.cogs_status == CogsStatus.PENDING.value,
            )
            .order_by(
                SalesInvoice.invoice_date,
                SalesInvoice.document_number,
                SalesInvoiceLine.line_number,
            )
        )
        rows = (await self.session.execute(statement)).all()
        return InvoicedNotDispatchedResponse(
            currency_code=await self._report_currency_code(tenant_id),
            lines=[
                InvoicedNotDispatchedLine(
                    sales_invoice_id=row[0],
                    sales_invoice_line_id=row[1],
                    document_number=str(row[2]),
                    invoice_date=row[3],
                    customer_id=row[4],
                    customer_name=str(row[5]),
                    product_id=row[6],
                    description=str(row[7]),
                    quantity=row[8],
                    amount=quantize_money(row[9] * row[11]),
                    cogs_status=str(row[10]),
                )
                for row in rows
            ],
        )

    async def received_not_billed(self, tenant_id: UUID) -> ReceivedNotBilledResponse:
        from app.inventory_management.goods_receipts.models import GoodsReceipt, GoodsReceiptLine

        outstanding = (
            GoodsReceiptLine.quantity - GoodsReceiptLine.qty_billed - GoodsReceiptLine.qty_returned
        )
        statement = (
            select(
                GoodsReceipt.id,
                GoodsReceiptLine.id,
                GoodsReceipt.document_number,
                GoodsReceipt.document_date,
                GoodsReceipt.supplier_id,
                Customer.name,
                GoodsReceiptLine.product_id,
                GoodsReceiptLine.description,
                GoodsReceiptLine.quantity,
                GoodsReceiptLine.qty_billed,
                outstanding,
                GoodsReceiptLine.rate,
                GoodsReceipt.exchange_rate,
            )
            .select_from(GoodsReceiptLine)
            .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.goods_receipt_id)
            .join(Customer, Customer.id == GoodsReceipt.supplier_id)
            .where(
                GoodsReceipt.tenant_id == tenant_id,
                GoodsReceipt.deleted_at.is_(None),
                GoodsReceipt.status == StockDocumentStatus.POSTED.value,
                GoodsReceiptLine.tenant_id == tenant_id,
                outstanding > _ZERO,
            )
            .order_by(
                GoodsReceipt.document_date,
                GoodsReceipt.document_number,
                GoodsReceiptLine.line_number,
            )
        )
        rows = (await self.session.execute(statement)).all()
        return ReceivedNotBilledResponse(
            currency_code=await self._report_currency_code(tenant_id),
            lines=[
                ReceivedNotBilledLine(
                    goods_receipt_id=row[0],
                    goods_receipt_line_id=row[1],
                    document_number=str(row[2]),
                    document_date=row[3],
                    supplier_id=row[4],
                    supplier_name=str(row[5]),
                    product_id=row[6],
                    description=str(row[7] or ""),
                    quantity=row[8],
                    qty_billed=row[9],
                    outstanding_qty=row[10],
                    amount=quantize_money(row[10] * row[11] * row[12]),
                )
                for row in rows
            ],
        )

    async def three_way_match(self, tenant_id: UUID) -> ThreeWayMatchResponse:
        from app.erp.purchase_invoices.models import PurchaseInvoice, PurchaseInvoiceLine
        from app.erp.purchase_orders.models import PurchaseOrder, PurchaseOrderLine

        billed_qty = func.coalesce(
            select(func.coalesce(func.sum(PurchaseInvoiceLine.quantity), _ZERO))
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
            .where(
                PurchaseInvoiceLine.purchase_order_line_id == PurchaseOrderLine.id,
                PurchaseInvoice.tenant_id == tenant_id,
                PurchaseInvoice.deleted_at.is_(None),
                PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
                PurchaseInvoiceLine.tenant_id == tenant_id,
            )
            .correlate(PurchaseOrderLine)
            .scalar_subquery(),
            _ZERO,
        )
        billed_value = func.coalesce(
            select(func.coalesce(func.sum(PurchaseInvoiceLine.amount), _ZERO))
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
            .where(
                PurchaseInvoiceLine.purchase_order_line_id == PurchaseOrderLine.id,
                PurchaseInvoice.tenant_id == tenant_id,
                PurchaseInvoice.deleted_at.is_(None),
                PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
                PurchaseInvoiceLine.tenant_id == tenant_id,
            )
            .correlate(PurchaseOrderLine)
            .scalar_subquery(),
            _ZERO,
        )
        billed_value_base = func.coalesce(
            select(
                func.coalesce(
                    func.sum(PurchaseInvoiceLine.amount * PurchaseInvoice.exchange_rate),
                    _ZERO,
                )
            )
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
            .where(
                PurchaseInvoiceLine.purchase_order_line_id == PurchaseOrderLine.id,
                PurchaseInvoice.tenant_id == tenant_id,
                PurchaseInvoice.deleted_at.is_(None),
                PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
                PurchaseInvoiceLine.tenant_id == tenant_id,
            )
            .correlate(PurchaseOrderLine)
            .scalar_subquery(),
            _ZERO,
        )
        statement = (
            select(
                PurchaseOrder.id,
                PurchaseOrderLine.id,
                PurchaseOrder.document_number,
                PurchaseOrder.order_date,
                PurchaseOrder.supplier_id,
                Customer.name,
                PurchaseOrderLine.product_id,
                PurchaseOrderLine.description,
                PurchaseOrderLine.quantity,
                PurchaseOrderLine.qty_received,
                PurchaseOrderLine.qty_returned,
                billed_qty,
                PurchaseOrderLine.amount,
                PurchaseOrderLine.rate,
                billed_value,
                PurchaseOrder.exchange_rate,
                billed_value_base,
            )
            .select_from(PurchaseOrderLine)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
            .join(Customer, Customer.id == PurchaseOrder.supplier_id)
            .where(
                PurchaseOrder.tenant_id == tenant_id,
                PurchaseOrder.deleted_at.is_(None),
                PurchaseOrder.status.notin_(
                    (
                        PurchaseOrderStatus.DRAFT.value,
                        PurchaseOrderStatus.CANCELLED.value,
                        PurchaseOrderStatus.REJECTED.value,
                    )
                ),
                PurchaseOrderLine.tenant_id == tenant_id,
            )
            .order_by(
                PurchaseOrder.order_date,
                PurchaseOrder.document_number,
                PurchaseOrderLine.line_number,
            )
        )
        rows = (await self.session.execute(statement)).all()
        lines: list[ThreeWayMatchLine] = []
        for row in rows:
            ordered_qty = row[8]
            received_qty = max(row[9] - row[10], _ZERO)
            billed = row[11]
            ordered_value = row[12]
            rate = row[13]
            billed_amt = row[14]
            exchange_rate = row[15]
            billed_amt_base = row[16]
            received_value = quantize_money(received_qty * rate * exchange_rate)
            status = self._three_way_status(
                ordered_qty=ordered_qty,
                received_qty=received_qty,
                billed_qty=billed,
                ordered_rate=rate,
                billed_value=billed_amt,
            )
            lines.append(
                ThreeWayMatchLine(
                    purchase_order_id=row[0],
                    purchase_order_line_id=row[1],
                    document_number=str(row[2]),
                    order_date=row[3],
                    supplier_id=row[4],
                    supplier_name=str(row[5]),
                    product_id=row[6],
                    description=str(row[7] or ""),
                    ordered_qty=ordered_qty,
                    received_qty=received_qty,
                    billed_qty=billed,
                    ordered_value=quantize_money(ordered_value * exchange_rate),
                    received_value=received_value,
                    billed_value=quantize_money(billed_amt_base),
                    status=status,
                )
            )
        return ThreeWayMatchResponse(
            currency_code=await self._report_currency_code(tenant_id),
            lines=lines,
        )

    def _three_way_status(
        self,
        *,
        ordered_qty: Decimal,
        received_qty: Decimal,
        billed_qty: Decimal,
        ordered_rate: Decimal,
        billed_value: Decimal,
    ) -> str:
        if received_qty <= _ZERO:
            return "UNRECEIVED"
        if billed_qty <= _ZERO:
            return "UNBILLED"
        if ordered_qty != received_qty or received_qty != billed_qty:
            return "QTY_VARIANCE"
        if billed_qty > _ZERO:
            billed_rate = billed_value / billed_qty
            if abs(billed_rate - ordered_rate) > Decimal("0.01"):
                return "PRICE_VARIANCE"
        return "MATCHED"

    async def dashboard(self, tenant_id: UUID, *, as_of: date | None = None) -> DashboardResponse:
        from app.inventory_management.delivery_notes.models import DeliveryNote
        from app.inventory_management.goods_receipts.models import GoodsReceipt

        as_of_date = as_of or utcnow().date()
        ar = await self.ar_aging(tenant_id, as_of=as_of_date)
        ap = await self.ap_aging(tenant_id, as_of=as_of_date)

        def _overdue(row: AgingPartyRow) -> Decimal:
            return row.days_1_30 + row.days_31_60 + row.days_61_90 + row.days_91_plus

        overdue_ar = sum(1 for row in ar.rows if _overdue(row) > _ZERO)
        overdue_ap = sum(1 for row in ap.rows if _overdue(row) > _ZERO)
        valuation = await self.stock_valuation(tenant_id, as_of=as_of_date)
        page = PageParams(page=1, page_size=1)
        unposted: list[DashboardUnpostedCount] = []
        for probe in registered_probes():
            documents, total = await probe(self.session, tenant_id, as_of_date, page)
            name = documents[0].document_type if documents else "unposted"
            if total:
                unposted.append(DashboardUnpostedCount(document_type=name, count=total))
        deliveries = await self.session.scalar(
            select(func.count())
            .select_from(DeliveryNote)
            .where(
                DeliveryNote.tenant_id == tenant_id,
                DeliveryNote.deleted_at.is_(None),
                DeliveryNote.status == StockDocumentStatus.POSTED.value,
                DeliveryNote.document_date == as_of_date,
            )
        )
        receipts = await self.session.scalar(
            select(func.count())
            .select_from(GoodsReceipt)
            .where(
                GoodsReceipt.tenant_id == tenant_id,
                GoodsReceipt.deleted_at.is_(None),
                GoodsReceipt.status == StockDocumentStatus.POSTED.value,
                GoodsReceipt.document_date == as_of_date,
            )
        )
        ar_by_party = {row.party_id: row.total for row in ar.rows}
        customers = (
            (
                await self.session.execute(
                    select(Customer).where(
                        Customer.tenant_id == tenant_id,
                        Customer.deleted_at.is_(None),
                        Customer.credit_limit.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        breaches: list[DashboardCreditBreach] = []
        for customer in customers:
            outstanding = ar_by_party.get(customer.id, _ZERO)
            if customer.credit_limit is not None and outstanding > customer.credit_limit:
                breaches.append(
                    DashboardCreditBreach(
                        customer_id=customer.id,
                        customer_name=customer.name,
                        credit_limit=customer.credit_limit,
                        outstanding=outstanding,
                    )
                )
        ar_open = ar.totals.total
        ap_open = ap.totals.total
        return DashboardResponse(
            currency_code=await self._report_currency_code(tenant_id),
            as_of=as_of_date,
            open_ar=ar_open,
            open_ap=ap_open,
            overdue_ar_count=overdue_ar,
            overdue_ap_count=overdue_ap,
            stock_valuation=valuation.total_value,
            unposted=unposted,
            deliveries_today=int(deliveries or 0),
            receipts_today=int(receipts or 0),
            credit_limit_breaches=breaches,
        )

    async def _sum_by_account(
        self,
        tenant_id: UUID,
        *,
        before: date | None = None,
        start: date | None = None,
        end: date | None = None,
        account_id: UUID | None = None,
        party_id: UUID | None = None,
        branch_id: UUID | None = None,
        exclude_source_types: Sequence[str] | None = None,
    ) -> dict[UUID, tuple[Decimal, Decimal]]:
        statement = (
            select(
                JournalEntryLine.account_id,
                func.coalesce(func.sum(JournalEntryLine.debit_base), 0),
                func.coalesce(func.sum(JournalEntryLine.credit_base), 0),
            )
            .join(JournalEntry, _posted_join())
            .where(JournalEntryLine.tenant_id == tenant_id)
            .group_by(JournalEntryLine.account_id)
        )
        if before is not None:
            statement = statement.where(JournalEntry.entry_date < before)
        if start is not None:
            statement = statement.where(JournalEntry.entry_date >= start)
        if end is not None:
            statement = statement.where(JournalEntry.entry_date <= end)
        if account_id is not None:
            statement = statement.where(JournalEntryLine.account_id == account_id)
        if party_id is not None:
            statement = statement.where(JournalEntryLine.party_id == party_id)
        if branch_id is not None:
            statement = statement.where(
                (JournalEntryLine.branch_id == branch_id) | (JournalEntry.branch_id == branch_id)
            )
        if exclude_source_types:
            statement = statement.where(JournalEntry.source_type.notin_(exclude_source_types))
        result: dict[UUID, tuple[Decimal, Decimal]] = {}
        for account_id_row, debit, credit in (await self.session.execute(statement)).all():
            result[account_id_row] = (
                quantize_money(Decimal(debit)),
                quantize_money(Decimal(credit)),
            )
        return result


    async def budget_vs_actual(
        self,
        tenant_id: UUID,
        budget_id: UUID,
        *,
        from_date: date,
        to_date: date,
    ) -> BudgetVsActualResponse:
        from app.erp.accounting.budgets.schemas import BudgetVsActualLine
        from app.erp.accounting.budgets.service import (
            BudgetService,
            empty_vs_actual,
            line_variance,
            month_end,
            month_start,
        )

        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        budget = await BudgetService(self.session).get(tenant_id, budget_id)
        accounts = {account.id: account for account in await self.accounts.repo.list_all(tenant_id)}
        actual_cache: dict[
            tuple[date, date, UUID | None], dict[UUID, tuple[Decimal, Decimal]]
        ] = {}
        lines: list[BudgetVsActualLine] = []
        for line in budget.lines:
            if line.period_start < month_start(from_date) or line.period_start > to_date:
                continue
            account = accounts.get(line.account_id)
            if account is None:
                continue
            end = min(month_end(line.period_start), to_date)
            cache_key = (line.period_start, end, line.branch_id)
            actual_map = actual_cache.get(cache_key)
            if actual_map is None:
                actual_map = await self._sum_by_account(
                    tenant_id,
                    start=line.period_start,
                    end=end,
                    branch_id=line.branch_id,
                )
                actual_cache[cache_key] = actual_map
            actual = self._signed(
                account.account_type, *actual_map.get(line.account_id, (_ZERO, _ZERO))
            )
            lines.append(
                BudgetVsActualLine(
                    account_id=account.id,
                    account_code=account.code,
                    account_name=account.name,
                    account_type=account.account_type,
                    period_start=line.period_start,
                    branch_id=line.branch_id,
                    budget_amount=line.amount,
                    actual_amount=actual,
                    variance_amount=line_variance(line.amount, actual),
                    source_id=account.id,
                )
            )
        return empty_vs_actual(
            budget_id=budget.id,
            budget_name=budget.name,
            currency_code=await self._report_currency_code(tenant_id),
            from_date=from_date,
            to_date=to_date,
            lines=lines,
        )

    @staticmethod
    def _group_journal_lines_by_entry(
        rows: Sequence[tuple[JournalEntryLine, JournalEntry]],
    ) -> list[tuple[UUID, list[tuple[JournalEntryLine, JournalEntry]]]]:
        """One statement row per journal entry (legacy SOA), preserving entry order."""

        grouped: dict[UUID, list[tuple[JournalEntryLine, JournalEntry]]] = defaultdict(list)
        order: list[UUID] = []
        for line, header in rows:
            if header.id not in grouped:
                order.append(header.id)
            grouped[header.id].append((line, header))
        return [(journal_id, grouped[journal_id]) for journal_id in order]

    async def _statement_currency_code(
        self, tenant_id: UUID, currency_id: UUID | None
    ) -> str:
        if currency_id is None:
            return await self._report_currency_code(tenant_id)
        return (await self.currencies.get(tenant_id, currency_id)).code

    async def _journal_entry_lines_grouped(
        self, tenant_id: UUID, journal_ids: set[UUID]
    ) -> dict[UUID, list[JournalEntryLine]]:
        if not journal_ids:
            return {}
        rows = (
            await self.session.execute(
                select(JournalEntryLine).where(
                    JournalEntryLine.tenant_id == tenant_id,
                    JournalEntryLine.journal_entry_id.in_(journal_ids),
                )
            )
        ).scalars().all()
        grouped: dict[UUID, list[JournalEntryLine]] = defaultdict(list)
        for line in rows:
            grouped[line.journal_entry_id].append(line)
        return grouped

    async def _cost_sheet_statement_meta(
        self, tenant_id: UUID, sheet_ids: set[UUID]
    ) -> tuple[dict[UUID, str], dict[UUID, str]]:
        if not sheet_ids:
            return {}, {}
        from app.erp.cost_sheets.models import CostSheet

        rows = (
            await self.session.execute(
                select(CostSheet.id, CostSheet.sheet_type, CostSheet.document_number).where(
                    CostSheet.tenant_id == tenant_id,
                    CostSheet.id.in_(sheet_ids),
                    CostSheet.deleted_at.is_(None),
                )
            )
        ).all()
        type_codes = {
            row_id: _COST_SHEET_TYPE_CODES.get(sheet_type, "CS")
            for row_id, sheet_type, _ in rows
        }
        document_numbers = {row_id: doc_number for row_id, _, doc_number in rows}
        return type_codes, document_numbers

    async def _cost_sheet_active_journal_ids(
        self, tenant_id: UUID, sheet_ids: set[UUID]
    ) -> dict[UUID, UUID]:
        if not sheet_ids:
            return {}
        from app.erp.cost_sheets.models import CostSheet

        rows = (
            await self.session.execute(
                select(CostSheet.id, CostSheet.journal_entry_id).where(
                    CostSheet.tenant_id == tenant_id,
                    CostSheet.id.in_(sheet_ids),
                    CostSheet.deleted_at.is_(None),
                    CostSheet.journal_entry_id.is_not(None),
                )
            )
        ).all()
        return {sheet_id: journal_id for sheet_id, journal_id in rows}

    async def _vouchers_for_statement(
        self, tenant_id: UUID, voucher_ids: set[UUID]
    ) -> dict[UUID, object]:
        if not voucher_ids:
            return {}
        from app.erp.accounting.vouchers.models import Voucher

        rows = (
            (
                await self.session.execute(
                    select(Voucher)
                    .options(selectinload(Voucher.lines))
                    .where(
                        Voucher.tenant_id == tenant_id,
                        Voucher.id.in_(voucher_ids),
                        Voucher.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.id: row for row in rows}

    @staticmethod
    def _orphan_voucher_journal(
        header: JournalEntry, active_by_voucher: dict[UUID, UUID]
    ) -> bool:
        voucher_id: UUID | None = None
        if header.source_type in VOUCHER_JOURNAL_SOURCE_TYPES and header.source_id is not None:
            voucher_id = header.source_id
        elif header.source_type == "general_purchase_voucher" and header.source_id is not None:
            voucher_id = header.source_id
        elif header.source_type == "journal_entry" and header.source_id is not None:
            voucher_id = header.source_id
        if voucher_id is None:
            return False
        active = active_by_voucher.get(voucher_id)
        return active is not None and header.id != active

    @staticmethod
    def _statement_document_source(
        header: JournalEntry, vouchers_by_id: dict[UUID, object]
    ) -> tuple[str | None, UUID | None]:
        if header.source_type in STATEMENT_LINE_LEVEL_SOURCES:
            return header.source_type, header.source_id
        if header.source_type != "journal_entry":
            return header.source_type, header.source_id
        voucher = None
        if header.source_id is not None:
            voucher = vouchers_by_id.get(header.source_id)
        if voucher is None:
            for candidate in vouchers_by_id.values():
                if getattr(candidate, "journal_entry_id", None) == header.id:
                    voucher = candidate
                    break
        if voucher is None:
            return header.source_type, header.source_id
        from app.core.enums import VoucherType
        from app.erp.accounting.vouchers.service import _VOUCHER_META

        voucher_type = VoucherType(voucher.voucher_type)
        source_type = _VOUCHER_META[voucher_type][2]
        return source_type, voucher.id

    async def _vouchers_for_journals(
        self, tenant_id: UUID, journal_ids: set[UUID]
    ) -> dict[UUID, object]:
        if not journal_ids:
            return {}
        from app.erp.accounting.vouchers.models import Voucher

        rows = (
            (
                await self.session.execute(
                    select(Voucher).where(
                        Voucher.tenant_id == tenant_id,
                        Voucher.journal_entry_id.in_(journal_ids),
                        Voucher.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.id: row for row in rows}

    def _account_statement_line_from_journal_line(
        self,
        entry_line: JournalEntryLine,
        header: JournalEntry,
        *,
        statement_source_type: str | None = None,
        statement_source_id: UUID | None = None,
        account_type: str | None,
        party_type: PartyType | None,
        party_id: UUID | None,
        currency_id: UUID | None,
        lines_by_journal: dict[UUID, list[JournalEntryLine]],
        vouchers_by_id: dict[UUID, object],
        cost_sheet_type_codes: dict[UUID, str],
        cost_sheet_document_numbers: dict[UUID, str],
        cheque_meta: dict,
        supplier_presentation_keys: set[tuple[UUID, int | None]],
    ) -> AccountStatementLine:
        if statement_source_type is None or statement_source_id is None:
            statement_source_type, statement_source_id = self._statement_document_source(
                header, vouchers_by_id
            )
        debit, credit = self._statement_line_amounts(entry_line, currency_id=currency_id)
        if statement_source_type not in DOCUMENT_LINE_SOURCES:
            if entry_line.party_type == PartyType.SUPPLIER.value and (
                party_id is None or entry_line.party_id == party_id
            ):
                debit, credit = net_supplier_statement_debit_credit(debit, credit)
                supplier_presentation_keys.add((header.id, entry_line.line_number))
            elif entry_line.party_type == PartyType.CUSTOMER.value and (
                party_id is None or entry_line.party_id == party_id
            ):
                net = quantize_money(debit - credit)
                if net >= _ZERO:
                    debit, credit = net, _ZERO
                else:
                    debit, credit = _ZERO, quantize_money(-net)
                supplier_presentation_keys.add((header.id, entry_line.line_number))
            elif account_type is not None:
                debit, credit = net_statement_debit_credit(account_type, debit, credit)
        voucher_code = _voucher_code(
            statement_source_type, journal_type=header.journal_type
        )
        if statement_source_type == "cost_sheet" and statement_source_id is not None:
            voucher_code = cost_sheet_type_codes.get(statement_source_id, voucher_code)
        cheque = cheque_meta.get(header.source_id) if header.source_id else None
        return AccountStatementLine(
            journal_entry_id=header.id,
            journal_line_number=entry_line.line_number,
            document_number=_statement_ref_number(
                header,
                cost_sheet_document_numbers=cost_sheet_document_numbers,
                vouchers_by_id=vouchers_by_id,
                source_type=statement_source_type,
                source_id=statement_source_id,
            ),
            entry_date=header.entry_date,
            due_date=entry_line.due_date,
            external_reference=entry_line.external_reference,
            debit=debit,
            credit=credit,
            running_balance=_ZERO,
            description=entry_line.description or header.narration,
            voucher_code=voucher_code,
            source_type=statement_source_type,
            source_id=statement_source_id,
            cheque_number=_statement_cheque_number(cheque=cheque, entry_line=entry_line),
            cheque_date=cheque.cheque_date if cheque is not None else None,
            cheque_clearing_date=self._cheque_clearing_date(cheque),
            balance_side=None,
            narration=header.narration,
        )

    def _supplier_party_line_amounts(
        self,
        journal_lines: list[JournalEntryLine],
        *,
        party_id: UUID | None,
        currency_id: UUID | None,
    ) -> tuple[Decimal, Decimal] | None:
        supplier_lines = [
            line
            for line in journal_lines
            if line.party_type == PartyType.SUPPLIER.value
            and (party_id is None or line.party_id == party_id)
        ]
        if not supplier_lines:
            return None
        debit = _ZERO
        credit = _ZERO
        for line in supplier_lines:
            line_debit, line_credit = self._statement_line_amounts(
                line, currency_id=currency_id
            )
            debit = quantize_money(debit + line_debit)
            credit = quantize_money(credit + line_credit)
        return debit, credit

    def _supplier_statement_journal_amounts(
        self,
        header: JournalEntry,
        journal_lines: list[JournalEntryLine],
        *,
        vouchers_by_id: dict[UUID, object],
        party_type: PartyType | None,
        party_id: UUID | None,
        currency_id: UUID | None,
    ) -> tuple[Decimal, Decimal] | None:
        if party_type == PartyType.CUSTOMER:
            return None
        if header.source_type in {"cost_sheet", "supplier_payment"}:
            return self._supplier_party_line_amounts(
                journal_lines, party_id=party_id, currency_id=currency_id
            )
        if (
            header.source_type in VOUCHER_JOURNAL_SOURCE_TYPES
            and header.source_id is not None
        ):
            voucher = vouchers_by_id.get(header.source_id)
            if voucher is None:
                return None
            party_type_value = PartyType.SUPPLIER.value
            target_party = party_id
            if target_party is None and getattr(voucher, "party_type", None) == party_type_value:
                target_party = voucher.party_id
            if target_party is None:
                for line in getattr(voucher, "lines", []):
                    if line.party_type == party_type_value and line.party_id is not None:
                        target_party = line.party_id
                        break
            if target_party is None:
                return None
            debit, credit, _ = self._party_voucher_amounts(
                voucher,
                party_type=PartyType.SUPPLIER,
                party_id=target_party,
                party_type_value=party_type_value,
            )
            return debit, credit
        return None

    @staticmethod
    def _statement_line_amounts(
        line: JournalEntryLine, *, currency_id: UUID | None
    ) -> tuple[Decimal, Decimal]:
        if currency_id is None:
            return line.debit_base, line.credit_base
        return line.debit, line.credit

    @staticmethod
    def _pdc_amounts(cheque, *, currency_id: UUID | None) -> tuple[Decimal, Decimal]:
        amount = cheque.base_amount if currency_id is None else cheque.amount
        amount = quantize_money(amount)
        if ChequeDirection(cheque.direction) == ChequeDirection.INBOUND:
            return amount, _ZERO
        return _ZERO, amount

    @staticmethod
    def _cheque_clearing_date(cheque) -> date | None:
        if cheque is None:
            return None
        if cheque.cleared_at is not None:
            return cheque.cleared_at.date()
        if ChequeStatus(cheque.status) == ChequeStatus.CLEARED:
            return cheque.due_date or cheque.cheque_date
        return None

    async def _cheque_meta_for_journals(
        self, tenant_id: UUID, cheque_ids: list[UUID]
    ) -> dict[UUID, object]:
        if not cheque_ids:
            return {}
        from app.erp.accounting.cheques.models import Cheque

        unique_ids = list(dict.fromkeys(cheque_ids))
        rows = (
            await self.session.execute(
                select(Cheque).where(
                    Cheque.tenant_id == tenant_id,
                    Cheque.id.in_(unique_ids),
                    Cheque.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        return {row.id: row for row in rows}

    async def _uncleared_cheques_for_statement(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        party_type: str | None,
        party_id: UUID | None,
        account_id: UUID | None,
        currency_id: UUID | None,
    ) -> list:
        from app.erp.accounting.cheques.models import Cheque

        due_or_cheque = func.coalesce(Cheque.due_date, Cheque.cheque_date)
        statement = select(Cheque).where(
            Cheque.tenant_id == tenant_id,
            Cheque.deleted_at.is_(None),
            Cheque.status.in_(tuple(_UNCLEARED_CHEQUE_STATUSES)),
            due_or_cheque >= from_date,
            due_or_cheque <= to_date,
        )
        if party_id is not None:
            statement = statement.where(Cheque.party_id == party_id)
        if party_type is not None:
            statement = statement.where(Cheque.party_type == party_type)
        if currency_id is not None:
            statement = statement.where(Cheque.currency_id == currency_id)
        if account_id is not None and party_id is None:
            party_ids = (
                select(JournalEntryLine.party_id)
                .join(JournalEntry, _posted_join())
                .where(
                    JournalEntryLine.tenant_id == tenant_id,
                    JournalEntryLine.account_id == account_id,
                    JournalEntryLine.party_id.is_not(None),
                )
                .distinct()
            )
            statement = statement.where(Cheque.party_id.in_(party_ids))
        statement = statement.order_by(due_or_cheque.asc(), Cheque.document_number.asc())
        return list((await self.session.execute(statement)).scalars().all())

    async def _sum_statement_opening(
        self,
        tenant_id: UUID,
        *,
        before: date,
        party_type: str | None = None,
        party_id: UUID | None = None,
        account_id: UUID | None = None,
        currency_id: UUID | None = None,
    ) -> tuple[Decimal, Decimal]:
        debit_col = (
            JournalEntryLine.debit_base if currency_id is None else JournalEntryLine.debit
        )
        credit_col = (
            JournalEntryLine.credit_base if currency_id is None else JournalEntryLine.credit
        )
        statement = (
            select(
                func.coalesce(func.sum(debit_col), 0),
                func.coalesce(func.sum(credit_col), 0),
            )
            .join(JournalEntry, _posted_join())
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntry.entry_date < before,
            )
        )
        if party_type is not None:
            statement = statement.where(JournalEntryLine.party_type == party_type)
        if party_id is not None:
            statement = statement.where(JournalEntryLine.party_id == party_id)
        if account_id is not None:
            statement = statement.where(JournalEntryLine.account_id == account_id)
        if currency_id is not None:
            statement = statement.where(JournalEntryLine.currency_id == currency_id)
        debit, credit = (await self.session.execute(statement)).one()
        return quantize_money(Decimal(debit)), quantize_money(Decimal(credit))

    async def _sum_party(
        self,
        tenant_id: UUID,
        *,
        party_type: str,
        party_id: UUID,
        before: date,
    ) -> tuple[Decimal, Decimal]:
        statement = (
            select(
                func.coalesce(func.sum(JournalEntryLine.debit_base), 0),
                func.coalesce(func.sum(JournalEntryLine.credit_base), 0),
            )
            .join(JournalEntry, _posted_join())
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntryLine.party_type == party_type,
                JournalEntryLine.party_id == party_id,
                JournalEntry.entry_date < before,
            )
        )
        debit, credit = (await self.session.execute(statement)).one()
        return quantize_money(Decimal(debit)), quantize_money(Decimal(credit))

    @staticmethod
    def _signed(account_type: str, debit: Decimal, credit: Decimal) -> Decimal:
        if account_type in _DEBIT_NORMAL:
            return quantize_money(debit - credit)
        return quantize_money(credit - debit)

    @staticmethod
    def _delta(account_type: str, debit: Decimal, credit: Decimal) -> Decimal:
        if account_type in _DEBIT_NORMAL:
            return quantize_money(debit - credit)
        return quantize_money(credit - debit)

    async def ar_aging(self, tenant_id: UUID, *, as_of: date) -> AgingResponse:
        return await self._aging(tenant_id, as_of=as_of, party_type=PartyType.CUSTOMER)

    async def ap_aging(self, tenant_id: UUID, *, as_of: date) -> AgingResponse:
        return await self._aging(tenant_id, as_of=as_of, party_type=PartyType.SUPPLIER)

    async def customer_statement(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        *,
        from_date: date,
        to_date: date,
        include_opening: bool = True,
        include_pdc: bool = False,
    ) -> PartyStatementResponse:
        return await self._party_document_statement(
            tenant_id,
            PartyType.CUSTOMER,
            customer_id,
            from_date=from_date,
            to_date=to_date,
            include_opening=include_opening,
            include_pdc=include_pdc,
        )

    async def supplier_statement(
        self,
        tenant_id: UUID,
        supplier_id: UUID,
        *,
        from_date: date,
        to_date: date,
        include_opening: bool = True,
        include_pdc: bool = False,
    ) -> PartyStatementResponse:
        return await self._party_document_statement(
            tenant_id,
            PartyType.SUPPLIER,
            supplier_id,
            from_date=from_date,
            to_date=to_date,
            include_opening=include_opening,
            include_pdc=include_pdc,
        )

    async def customer_outstanding(
        self, tenant_id: UUID, customer_id: UUID, *, as_of: date | None = None
    ) -> OutstandingSummary:
        from app.crm.customers.service import CustomerService
        from app.erp.accounting.open_items.as_of import as_of_balances

        customer = await CustomerService(self.session).get(tenant_id, customer_id)
        as_of_date = as_of or utcnow().date()
        items = [
            row.to_open_item_row()
            for row in await as_of_balances(
                self.session, tenant_id, PartyType.CUSTOMER, as_of_date
            )
            if row.party_id == customer_id
        ]
        return self._outstanding_from_items(
            customer_id,
            items,
            as_of=as_of_date,
            credit_limit=customer.credit_limit,
            party_type=PartyType.CUSTOMER,
            currency_code=await self._report_currency_code(tenant_id),
        )

    async def supplier_outstanding(
        self, tenant_id: UUID, supplier_id: UUID, *, as_of: date | None = None
    ) -> OutstandingSummary:
        from app.erp.accounting.open_items.as_of import as_of_balances

        as_of_date = as_of or utcnow().date()
        items = [
            row.to_open_item_row()
            for row in await as_of_balances(
                self.session, tenant_id, PartyType.SUPPLIER, as_of_date
            )
            if row.party_id == supplier_id
        ]
        return self._outstanding_from_items(
            supplier_id,
            items,
            as_of=as_of_date,
            credit_limit=None,
            party_type=PartyType.SUPPLIER,
            currency_code=await self._report_currency_code(tenant_id),
        )

    async def _aging(self, tenant_id: UUID, *, as_of: date, party_type: PartyType) -> AgingResponse:
        from app.erp.accounting.open_items.as_of import as_of_balances

        if party_type == PartyType.CUSTOMER:
            company_types = (CompanyType.CUSTOMER.value, CompanyType.BOTH.value)
        else:
            company_types = (CompanyType.SUPPLIER.value, CompanyType.BOTH.value)
        parties = list(
            (
                await self.session.execute(
                    select(Customer).where(
                        Customer.tenant_id == tenant_id,
                        Customer.deleted_at.is_(None),
                        Customer.company_type.in_(company_types),
                    )
                )
            )
            .scalars()
            .all()
        )
        as_of_items = await as_of_balances(self.session, tenant_id, party_type, as_of)
        items_by_party: dict[UUID, list] = {}
        for item in as_of_items:
            items_by_party.setdefault(item.party_id, []).append(item.to_open_item_row())
        rows: list[AgingPartyRow] = []
        totals = AgingBucketTotals()
        warnings: list[ReportWarning] = []
        report_currency = await self._report_currency_code(tenant_id)
        for party in parties:
            items = items_by_party.get(party.id, [])
            buckets, documents, item_warnings = self._bucket_items(
                items, as_of=as_of, party_type=party_type
            )
            warnings.extend(item_warnings)
            if all(value == _ZERO for value in buckets.model_dump().values()):
                continue
            rows.append(
                AgingPartyRow(
                    party_id=party.id,
                    party_name=party.name,
                    documents=documents,
                    **buckets.model_dump(),
                )
            )
            for name, value in buckets.model_dump().items():
                setattr(totals, name, quantize_money(getattr(totals, name) + value))
        rows.sort(key=lambda row: row.party_name)
        return AgingResponse(
            currency_code=report_currency,
            as_of=as_of,
            rows=rows,
            totals=totals,
            warnings=warnings,
        )

    async def outstanding_documents(
        self,
        tenant_id: UUID,
        *,
        party_type: PartyType,
        as_of: date | None = None,
    ) -> OutstandingDocumentsResponse:
        aging = await self._aging(
            tenant_id, as_of=as_of or utcnow().date(), party_type=party_type
        )
        lines: list[OutstandingDocument] = []
        total_balance = _ZERO
        for row in aging.rows:
            for document in row.documents:
                due = document.due_date or document.document_date
                days = max((aging.as_of - due).days, 0)
                lines.append(
                    OutstandingDocument(
                        item_type=document.item_type,
                        document_id=document.document_id,
                        document_number=document.document_number,
                        document_date=document.document_date,
                        due_date=document.due_date,
                        party_id=row.party_id,
                        party_name=row.party_name,
                        currency_code=document.currency_code,
                        exchange_rate=document.exchange_rate,
                        document_balance=document.document_balance,
                        balance=document.balance,
                        bucket=document.bucket,
                        days_overdue=days,
                    )
                )
                total_balance = quantize_money(total_balance + document.balance)
        lines.sort(key=lambda item: (item.party_name, item.document_date, item.document_number))
        return OutstandingDocumentsResponse(
            currency_code=aging.currency_code,
            as_of=aging.as_of,
            party_type=party_type.value,
            total_balance=total_balance,
            lines=lines,
            warnings=aging.warnings,
        )

    def _aging_bucket(self, as_of: date, due: date) -> str:
        days = (as_of - due).days
        if days <= 0:
            return "current"
        if days <= 30:
            return "days_1_30"
        if days <= 60:
            return "days_31_60"
        if days <= 90:
            return "days_61_90"
        return "days_91_plus"

    def _bucket_items(
        self, items, *, as_of: date, party_type: PartyType
    ) -> tuple[AgingBucketTotals, list[AgingDocument], list[ReportWarning]]:
        buckets = AgingBucketTotals()
        documents: list[AgingDocument] = []
        warnings: list[ReportWarning] = []
        outstanding_types = (
            {OpenItemType.SALES_INVOICE, OpenItemType.OPENING_AR}
            if party_type == PartyType.CUSTOMER
            else {OpenItemType.PURCHASE_INVOICE, OpenItemType.OPENING_AP}
        )
        credit_types = (
            {OpenItemType.CREDIT_NOTE, OpenItemType.CUSTOMER_PAYMENT}
            if party_type == PartyType.CUSTOMER
            else {OpenItemType.DEBIT_NOTE, OpenItemType.SUPPLIER_PAYMENT}
        )

        def _add(target: AgingBucketTotals, field: str, amount: Decimal) -> None:
            setattr(target, field, quantize_money(getattr(target, field) + amount))

        for item in items:
            if item.document_date > as_of:
                continue
            base_amount = open_item_base_amount(item)
            if base_amount is None:
                warnings.append(
                    ReportWarning(
                        code="MISSING_EXCHANGE_RATE",
                        message="Open item excluded from aging: no base amount could be resolved.",
                        document_id=item.document_id,
                        document_number=item.document_number,
                    )
                )
                continue
            if item.item_type in credit_types:
                bucket = "unapplied_credits"
            elif item.item_type in outstanding_types:
                bucket = self._aging_bucket(as_of, item.due_date or item.document_date)
            else:
                continue
            if item.item_type in credit_types:
                _add(buckets, "unapplied_credits", base_amount)
            else:
                _add(buckets, bucket, base_amount)
            documents.append(
                AgingDocument(
                    item_type=item.item_type.value
                    if hasattr(item.item_type, "value")
                    else str(item.item_type),
                    document_id=item.document_id,
                    document_number=item.document_number,
                    document_date=item.document_date,
                    due_date=item.due_date,
                    currency_code=item.currency_code,
                    exchange_rate=item.exchange_rate,
                    document_balance=item.balance,
                    balance=base_amount,
                    bucket=bucket,
                )
            )
        buckets.total = quantize_money(
            buckets.current
            + buckets.days_1_30
            + buckets.days_31_60
            + buckets.days_61_90
            + buckets.days_91_plus
            - buckets.unapplied_credits
        )
        return buckets, documents, warnings

    def _outstanding_from_items(
        self,
        party_id: UUID,
        items,
        *,
        as_of: date,
        credit_limit: Decimal | None,
        party_type: PartyType,
        currency_code: str | None = None,
    ) -> OutstandingSummary:
        outstanding_types = (
            {OpenItemType.SALES_INVOICE, OpenItemType.OPENING_AR}
            if party_type == PartyType.CUSTOMER
            else {OpenItemType.PURCHASE_INVOICE, OpenItemType.OPENING_AP}
        )
        credit_types = (
            {OpenItemType.CREDIT_NOTE, OpenItemType.CUSTOMER_PAYMENT}
            if party_type == PartyType.CUSTOMER
            else {OpenItemType.DEBIT_NOTE, OpenItemType.SUPPLIER_PAYMENT}
        )
        balance_due = overdue = unapplied = _ZERO
        for item in items:
            amount = open_item_base_amount(item)
            if amount is None:
                continue
            if item.item_type in credit_types:
                unapplied = quantize_money(unapplied + amount)
                continue
            if item.item_type not in outstanding_types:
                continue
            balance_due = quantize_money(balance_due + amount)
            due = item.due_date or item.document_date
            if due < as_of:
                overdue = quantize_money(overdue + amount)
        available = None
        if credit_limit is not None:
            available = quantize_money(credit_limit - (balance_due - unapplied))
        return OutstandingSummary(
            currency_code=currency_code,
            party_id=party_id,
            balance_due=balance_due,
            overdue=overdue,
            unapplied_credits=unapplied,
            credit_limit=credit_limit,
            available_credit=available,
        )

    @staticmethod
    def _document_type_as_source_type(document_type: str) -> str:
        if document_type.startswith("VOUCHER_"):
            kind = document_type.removeprefix("VOUCHER_").lower()
            if kind == "journal":
                return "journal_voucher"
            if kind == "general_purchase":
                return "journal_voucher"
            if kind == "contra":
                return "contra_voucher"
            if kind == "payment_voucher":
                return "bank_payment_voucher"
            if kind in {"cash_receipt", "cash_payment", "bank_receipt", "bank_payment"}:
                return f"{kind}_voucher"
            return kind
        return document_type.lower()

    def _account_statement_from_party(
        self,
        party_stmt: PartyStatementResponse,
        *,
        account,
        include_opening: bool,
    ) -> AccountStatementResponse:
        opening_row = None
        if include_opening and party_stmt.opening_balance != _ZERO:
            opening_row = AccountStatementOpening(
                entry_date=party_stmt.from_date,
                debit=_ZERO,
                credit=_ZERO,
                running_balance=party_stmt.opening_balance,
                balance_side=party_stmt.opening_balance_side or _balance_side(party_stmt.opening_balance),
            )
        lines: list[AccountStatementLine] = []
        for row in party_stmt.lines:
            source_type = self._document_type_as_source_type(row.document_type)
            lines.append(
                AccountStatementLine(
                    journal_entry_id=None,
                    document_number=row.document_number,
                    entry_date=row.document_date,
                    due_date=row.due_date,
                    external_reference=None,
                    debit=row.debit,
                    credit=row.credit,
                    running_balance=row.running_balance,
                    description=row.description,
                    voucher_code=row.type_code,
                    source_type=source_type,
                    source_id=row.document_id,
                    cheque_number=row.cheque_number,
                    cheque_date=row.cheque_date,
                    balance_side=row.balance_side,
                    narration=None,
                )
            )
        return AccountStatementResponse(
            currency_code=party_stmt.currency_code,
            party_type=party_stmt.party_type,
            party_id=party_stmt.party_id,
            account_id=account.id if account is not None else None,
            account_code=account.code if account is not None else party_stmt.account_code,
            account_name=account.name if account is not None else party_stmt.account_name,
            from_date=party_stmt.from_date,
            to_date=party_stmt.to_date,
            opening_balance=party_stmt.opening_balance,
            closing_balance=party_stmt.closing_balance,
            total_debit=party_stmt.total_debit,
            total_credit=party_stmt.total_credit,
            opening=opening_row,
            lines=lines,
        )

    @staticmethod
    def _legacy_party_type_code(document_type: str) -> str:
        mapping = {
            "SALES_INVOICE": "SI",
            "PURCHASE_INVOICE": "PI",
            "CREDIT_NOTE": "CN",
            "DEBIT_NOTE": "DN",
            "CUSTOMER_PAYMENT": "CR",
            "SUPPLIER_PAYMENT": "PV",
            "VOUCHER_CASH_RECEIPT": "CR",
            "VOUCHER_BANK_RECEIPT": "BR",
            "VOUCHER_CASH_PAYMENT": "CP",
            "VOUCHER_BANK_PAYMENT": "BP",
            "VOUCHER_JOURNAL": "JV",
            "VOUCHER_GENERAL_PURCHASE": "GP",
            "VOUCHER_PAYMENT_VOUCHER": "PV",
            "VOUCHER_CONTRA": "CV",
            "COST_SHEET": "CS",
            "PURCHASE_ORDER": "PO",
            "SALES_ORDER": "SO",
            "OPENING_AR": "OB",
            "OPENING_AP": "OB",
            "SALES_INVOICE_WRITE_OFF": "WO",
            "PURCHASE_INVOICE_WRITE_OFF": "WO",
            "CUSTOMER_PAYMENT_REFUND": "RR",
            "SUPPLIER_PAYMENT_REFUND": "SR",
        }
        return mapping.get(document_type, document_type.replace("_", "")[:4])

    async def _append_party_journal_line_events(
        self,
        tenant_id: UUID,
        party_id: UUID,
        party_type: PartyType,
        events: list,
    ) -> set[UUID]:
        """One party statement row per cost sheet / voucher journal line (net per line slot)."""

        from app.erp.accounting.vouchers.models import Voucher
        from app.erp.cost_sheets.models import CostSheet

        party_type_value = (
            PartyType.CUSTOMER.value
            if party_type == PartyType.CUSTOMER
            else PartyType.SUPPLIER.value
        )
        journal_rows = (
            await self.session.execute(
                select(JournalEntryLine, JournalEntry)
                .join(JournalEntry, _posted_join())
                .where(
                    JournalEntryLine.tenant_id == tenant_id,
                    JournalEntry.source_type.in_(tuple(PARTY_JOURNAL_LINE_SOURCES)),
                    JournalEntry.source_id.is_not(None),
                    JournalEntryLine.party_id == party_id,
                    JournalEntryLine.party_type == party_type_value,
                )
                .order_by(
                    JournalEntry.entry_date.asc(),
                    JournalEntry.document_number.asc(),
                    JournalEntryLine.line_number.asc(),
                )
            )
        ).all()
        emitted_voucher_ids: set[UUID] = set()
        if not journal_rows:
            return emitted_voucher_ids
        by_document_line: dict[
            tuple[str, UUID, int], list[tuple[JournalEntryLine, JournalEntry]]
        ] = defaultdict(list)
        for line, header in journal_rows:
            if header.source_id is None:
                continue
            by_document_line[
                (header.source_type, header.source_id, line.line_number)
            ].append((line, header))
        sheet_ids = {
            source_id
            for source_type, source_id, _ in by_document_line
            if source_type == "cost_sheet"
        }
        voucher_ids = {
            source_id
            for source_type, source_id, _ in by_document_line
            if source_type in VOUCHER_JOURNAL_SOURCE_TYPES
        }
        sheets_by_id: dict[UUID, CostSheet] = {}
        if sheet_ids:
            sheets = (
                await self.session.execute(
                    select(CostSheet).where(
                        CostSheet.tenant_id == tenant_id,
                        CostSheet.id.in_(sheet_ids),
                        CostSheet.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            sheets_by_id = {row.id: row for row in sheets}
        vouchers_by_id: dict[UUID, Voucher] = {}
        if voucher_ids:
            vouchers = (
                await self.session.execute(
                    select(Voucher).where(
                        Voucher.tenant_id == tenant_id,
                        Voucher.id.in_(voucher_ids),
                        Voucher.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            vouchers_by_id = {row.id: row for row in vouchers}
        for (source_type, source_id, _line_number), pairs in by_document_line.items():
            debit = _ZERO
            credit = _ZERO
            description: str | None = None
            latest_date: date | None = None
            latest_doc: str | None = None
            for line, header in pairs:
                debit = quantize_money(debit + line.debit)
                credit = quantize_money(credit + line.credit)
                if description is None and line.description:
                    description = line.description
                if latest_date is None or header.entry_date >= latest_date:
                    latest_date = header.entry_date
                    latest_doc = header.document_number
            if party_type == PartyType.SUPPLIER:
                debit, credit = net_supplier_statement_debit_credit(debit, credit)
            elif party_type == PartyType.CUSTOMER:
                net = quantize_money(debit - credit)
                if net >= _ZERO:
                    debit, credit = net, _ZERO
                else:
                    debit, credit = _ZERO, quantize_money(-net)
            if debit == _ZERO and credit == _ZERO:
                continue
            if source_type == "cost_sheet":
                sheet = sheets_by_id.get(source_id)
                doc_type = "COST_SHEET"
                type_code = (
                    _COST_SHEET_TYPE_CODES.get(sheet.sheet_type, "CS")
                    if sheet is not None
                    else "CS"
                )
                ref_number = sheet.document_number if sheet is not None else latest_doc
                currency_id = sheet.currency_id if sheet is not None else pairs[0][1].currency_id
                exchange_rate = (
                    sheet.exchange_rate if sheet is not None else pairs[0][1].exchange_rate
                )
                notes = sheet.notes if sheet is not None else None
            else:
                voucher = vouchers_by_id.get(source_id)
                if voucher is None:
                    continue
                emitted_voucher_ids.add(source_id)
                voucher_type = VoucherType(voucher.voucher_type)
                doc_type = f"VOUCHER_{voucher_type.value}"
                type_code = self._legacy_party_type_code(doc_type)
                ref_number = voucher.document_number
                currency_id = voucher.currency_id
                exchange_rate = voucher.exchange_rate
                notes = voucher.reference or voucher.narration
            event_date = latest_date
            if event_date is None and source_type == "cost_sheet":
                sheet = sheets_by_id.get(source_id)
                if sheet is not None:
                    event_date = sheet.document_date
            if event_date is None:
                event_date = pairs[0][1].entry_date
            events.append(
                (
                    event_date,
                    doc_type,
                    source_id,
                    ref_number or "—",
                    debit,
                    credit,
                    None,
                    description or notes,
                    currency_id,
                    exchange_rate,
                    type_code,
                    vouchers_by_id.get(source_id).cheque_number
                    if source_id in vouchers_by_id
                    else None,
                    vouchers_by_id.get(source_id).cheque_date
                    if source_id in vouchers_by_id
                    else None,
                )
            )
        return emitted_voucher_ids

    @staticmethod
    def _party_voucher_amounts(
        row,
        *,
        party_type: PartyType,
        party_id: UUID,
        party_type_value: str,
    ) -> tuple[Decimal, Decimal, str | None]:
        voucher_type = VoucherType(row.voucher_type)
        amount = payment_base_amount(row.total_amount, row.exchange_rate)
        debit = _ZERO
        credit = _ZERO
        description: str | None = row.reference or row.narration
        if voucher_type in _JOURNAL_LIKE_VOUCHER_TYPES:
            party_lines = [
                line
                for line in row.lines
                if line.party_id == party_id and line.party_type == party_type_value
            ]
            if party_lines:
                debit = sum((quantize_money(line.debit) for line in party_lines), _ZERO)
                credit = sum(
                    (quantize_money(line.credit) for line in party_lines), _ZERO
                )
                description = next(
                    (line.description for line in party_lines if line.description),
                    description,
                )
            elif row.party_id == party_id and row.party_type == party_type_value:
                if party_type == PartyType.SUPPLIER:
                    credit = amount
                else:
                    debit = amount
            return debit, credit, description
        party_lines = [
            line
            for line in row.lines
            if line.party_id == party_id and line.party_type == party_type_value
        ]
        if party_lines:
            debit = sum((quantize_money(line.debit) for line in party_lines), _ZERO)
            credit = sum(
                (quantize_money(line.credit) for line in party_lines), _ZERO
            )
            description = next(
                (line.description for line in party_lines if line.description),
                description,
            )
            return debit, credit, description
        if row.party_id != party_id or row.party_type != party_type_value:
            return _ZERO, _ZERO, description
        if party_type == PartyType.CUSTOMER:
            if voucher_type in {
                VoucherType.CASH_RECEIPT,
                VoucherType.BANK_RECEIPT,
            }:
                credit = amount
            elif voucher_type in {
                VoucherType.CASH_PAYMENT,
                VoucherType.BANK_PAYMENT,
                VoucherType.PAYMENT_VOUCHER,
            }:
                debit = amount
        else:
            if voucher_type in {
                VoucherType.CASH_PAYMENT,
                VoucherType.BANK_PAYMENT,
                VoucherType.PAYMENT_VOUCHER,
            }:
                debit = amount
            elif voucher_type in {
                VoucherType.CASH_RECEIPT,
                VoucherType.BANK_RECEIPT,
            }:
                credit = amount
        return debit, credit, description

    async def _party_document_statement(
        self,
        tenant_id: UUID,
        party_type: PartyType,
        party_id: UUID,
        *,
        from_date: date,
        to_date: date,
        include_opening: bool = True,
        include_pdc: bool = False,
    ) -> PartyStatementResponse:
        from app.crm.customers.service import (
            CUSTOMER_PARTY_ROLE,
            SUPPLIER_PARTY_ROLE,
            CustomerService,
        )
        from app.erp.accounting.customer_payments.models import CustomerPayment
        from app.erp.accounting.reports.party_statement_events import (
            append_party_invoice_events,
            append_party_opening_events,
            append_party_order_events,
            append_party_payment_refund_events,
            append_party_write_off_events,
        )
        from app.erp.accounting.supplier_payments.models import SupplierPayment
        from app.erp.credit_notes.models import CreditNote
        from app.erp.debit_notes.models import DebitNote
        from app.erp.accounting.vouchers.models import Voucher, VoucherLine
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        role = CUSTOMER_PARTY_ROLE if party_type == PartyType.CUSTOMER else SUPPLIER_PARTY_ROLE
        party = await CustomerService(self.session, role=role).get(tenant_id, party_id)
        events: list[tuple] = []
        journal_ids_on_statement: set[UUID] = set()
        await append_party_order_events(
            self.session, tenant_id, party_id, party_type, events
        )
        await append_party_invoice_events(
            self.session, tenant_id, party_id, party_type, events
        )
        if party_type == PartyType.CUSTOMER:
            notes = (
                (
                    await self.session.execute(
                        select(CreditNote).where(
                            CreditNote.tenant_id == tenant_id,
                            CreditNote.customer_id == party_id,
                            CreditNote.deleted_at.is_(None),
                            CreditNote.status == InvoiceDocumentStatus.POSTED.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in notes:
                amount = document_base_grand(row)
                events.append(
                    (
                        row.credit_note_date,
                        "CREDIT_NOTE",
                        row.id,
                        row.document_number,
                        _ZERO,
                        amount,
                        row.due_date,
                        None,
                        row.currency_id,
                        row.exchange_rate,
                    )
                )
            payments = (
                (
                    await self.session.execute(
                        select(CustomerPayment).where(
                            CustomerPayment.tenant_id == tenant_id,
                            CustomerPayment.customer_id == party_id,
                            CustomerPayment.deleted_at.is_(None),
                            CustomerPayment.status == InvoiceDocumentStatus.POSTED.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in payments:
                if row.journal_entry_id is not None:
                    journal_ids_on_statement.add(row.journal_entry_id)
                if row.refund_journal_entry_id is not None:
                    journal_ids_on_statement.add(row.refund_journal_entry_id)
                amount = payment_base_amount(row.amount_received, row.exchange_rate)
                events.append(
                    (
                        row.payment_date,
                        "CUSTOMER_PAYMENT",
                        row.id,
                        row.document_number,
                        _ZERO,
                        amount,
                        None,
                        row.reference,
                        row.currency_id,
                        row.exchange_rate,
                    )
                )
        else:
            notes = (
                (
                    await self.session.execute(
                        select(DebitNote).where(
                            DebitNote.tenant_id == tenant_id,
                            DebitNote.supplier_id == party_id,
                            DebitNote.deleted_at.is_(None),
                            DebitNote.status == InvoiceDocumentStatus.POSTED.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in notes:
                amount = document_base_grand(row)
                events.append(
                    (
                        row.debit_note_date,
                        "DEBIT_NOTE",
                        row.id,
                        row.document_number,
                        amount,
                        _ZERO,
                        row.due_date,
                        None,
                        row.currency_id,
                        row.exchange_rate,
                    )
                )
            payments = (
                (
                    await self.session.execute(
                        select(SupplierPayment).where(
                            SupplierPayment.tenant_id == tenant_id,
                            SupplierPayment.supplier_id == party_id,
                            SupplierPayment.deleted_at.is_(None),
                            SupplierPayment.status == InvoiceDocumentStatus.POSTED.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in payments:
                if row.journal_entry_id is not None:
                    journal_ids_on_statement.add(row.journal_entry_id)
                if row.refund_journal_entry_id is not None:
                    journal_ids_on_statement.add(row.refund_journal_entry_id)
                amount = payment_base_amount(row.amount_paid, row.exchange_rate)
                events.append(
                    (
                        row.payment_date,
                        "SUPPLIER_PAYMENT",
                        row.id,
                        row.document_number,
                        amount,
                        _ZERO,
                        None,
                        row.reference,
                        row.currency_id,
                        row.exchange_rate,
                    )
                )
        await append_party_opening_events(
            self.session, tenant_id, party_id, party_type, events
        )
        await append_party_write_off_events(
            self.session, tenant_id, party_id, party_type, events
        )
        await append_party_payment_refund_events(
            self.session, tenant_id, party_id, party_type, events
        )
        voucher_ids_from_journals = await self._append_party_journal_line_events(
            tenant_id, party_id, party_type, events
        )
        party_type_value = PartyType.CUSTOMER.value if party_type == PartyType.CUSTOMER else PartyType.SUPPLIER.value
        party_on_header = and_(
            Voucher.party_id == party_id,
            Voucher.party_type == party_type_value,
        )
        party_on_line = exists(
            select(VoucherLine.voucher_id).where(
                VoucherLine.voucher_id == Voucher.id,
                VoucherLine.party_id == party_id,
                VoucherLine.party_type == party_type_value,
            )
        )
        vouchers = (
            (
                await self.session.execute(
                    select(Voucher)
                    .options(selectinload(Voucher.lines))
                    .where(
                        Voucher.tenant_id == tenant_id,
                        Voucher.deleted_at.is_(None),
                        Voucher.status == InvoiceDocumentStatus.POSTED.value,
                        or_(party_on_header, party_on_line),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in vouchers:
            if row.id in voucher_ids_from_journals:
                if row.journal_entry_id is not None:
                    journal_ids_on_statement.add(row.journal_entry_id)
                continue
            if row.journal_entry_id is not None:
                journal_ids_on_statement.add(row.journal_entry_id)
            debit, credit, description = self._party_voucher_amounts(
                row,
                party_type=party_type,
                party_id=party_id,
                party_type_value=party_type_value,
            )
            if debit == _ZERO and credit == _ZERO:
                continue
            voucher_type = VoucherType(row.voucher_type)
            doc_type = f"VOUCHER_{voucher_type.value}"
            events.append(
                (
                    row.voucher_date,
                    doc_type,
                    row.id,
                    row.document_number,
                    debit,
                    credit,
                    None,
                    description,
                    row.currency_id,
                    row.exchange_rate,
                    self._legacy_party_type_code(doc_type),
                    row.cheque_number,
                    row.cheque_date,
                )
            )
        if include_pdc:
            pdc_rows = await self._uncleared_cheques_for_statement(
                tenant_id,
                from_date=from_date,
                to_date=to_date,
                party_type=party_type.value,
                party_id=party_id,
                account_id=None,
                currency_id=None,
            )
            for cheque in pdc_rows:
                if (
                    cheque.journal_entry_id is not None
                    and cheque.journal_entry_id in journal_ids_on_statement
                ):
                    continue
                debit, credit = self._pdc_amounts(cheque, currency_id=None)
                entry_date = cheque.due_date or cheque.cheque_date
                events.append(
                    (
                        entry_date,
                        "CHEQUE_PDC",
                        cheque.id,
                        cheque.document_number,
                        debit,
                        credit,
                        cheque.due_date,
                        cheque.narration or f"PDC {cheque.cheque_number}",
                        cheque.currency_id,
                        cheque.exchange_rate or _ZERO,
                        "PD",
                        cheque.cheque_number,
                        cheque.cheque_date,
                    )
                )
        events.sort(key=lambda item: (item[0], item[3]))
        currency_codes = await self.currencies.codes_by_ids(
            tenant_id, [event[8] for event in events]
        )
        opening = _ZERO
        lines: list[PartyStatementLine] = []
        running = _ZERO
        for raw in events:
            if len(raw) == 10:
                raw = (
                    *raw,
                    self._legacy_party_type_code(raw[1]),
                    None,
                    None,
                )
            (
                doc_date,
                doc_type,
                doc_id,
                number,
                debit,
                credit,
                due,
                description,
                currency_id,
                exchange_rate,
                type_code,
                cheque_number,
                cheque_date,
            ) = raw
            signed = quantize_money(debit - credit)
            if doc_date < from_date:
                if include_opening:
                    opening = quantize_money(opening + signed)
                continue
            if doc_date > to_date:
                continue
            if not lines:
                running = opening if include_opening else _ZERO
            running = quantize_money(running + signed)
            lines.append(
                PartyStatementLine(
                    document_type=doc_type,
                    type_code=type_code,
                    document_id=doc_id,
                    document_number=number,
                    document_date=doc_date,
                    due_date=due,
                    currency_code=currency_codes.get(currency_id),
                    exchange_rate=exchange_rate,
                    debit=debit,
                    credit=credit,
                    running_balance=running,
                    balance_side=_balance_side(running),
                    description=description,
                    cheque_number=cheque_number,
                    cheque_date=cheque_date,
                )
            )
        if not lines:
            running = opening if include_opening else _ZERO
        total_debit = sum((line.debit for line in lines), _ZERO)
        total_credit = sum((line.credit for line in lines), _ZERO)
        opening_reported = opening if include_opening else _ZERO
        return PartyStatementResponse(
            currency_code=await self._report_currency_code(tenant_id),
            party_type=party_type.value,
            party_id=party_id,
            party_name=party.name,
            account_code=party.code,
            account_name=party.name,
            from_date=from_date,
            to_date=to_date,
            opening_balance=opening_reported,
            opening_balance_side=_balance_side(opening_reported)
            if opening_reported != _ZERO
            else None,
            closing_balance=running,
            closing_balance_side=_balance_side(running) if running != _ZERO else None,
            total_debit=quantize_money(total_debit),
            total_credit=quantize_money(total_credit),
            lines=lines,
        )
