"""Trial balance, general ledger, party statements, and Stage I reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
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
    CogsStatus,
    CompanyType,
    InvoiceDocumentStatus,
    JournalEntryStatus,
    OpenItemType,
    PartyType,
    PurchaseOrderStatus,
    StockDocumentStatus,
)
from app.core.exceptions import ValidationError
from app.crm.customers.models import Customer
from app.erp.accounting.accounts.service import AccountService
from app.erp.accounting.budgets.schemas import BudgetVsActualResponse
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
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


def _net_sides(debit: Decimal, credit: Decimal) -> tuple[Decimal, Decimal]:
    net = quantize_money(debit - credit)
    if net >= _ZERO:
        return net, _ZERO
    return _ZERO, quantize_money(-net)


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
        cost_center_id: UUID | None = None,
        include_zero: bool = False,
    ) -> TrialBalanceResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        accounts = await self.accounts.repo.list_all(tenant_id)
        opening_map = await self._sum_by_account(
            tenant_id, before=from_date, branch_id=branch_id, cost_center_id=cost_center_id
        )
        period_map = await self._sum_by_account(
            tenant_id,
            start=from_date,
            end=to_date,
            branch_id=branch_id,
            cost_center_id=cost_center_id,
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
        cost_center_id: UUID | None = None,
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
            cost_center_id=cost_center_id,
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
        if cost_center_id is not None:
            statement = statement.where(
                (JournalEntryLine.cost_center_id == cost_center_id)
                | (JournalEntry.cost_center_id == cost_center_id)
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
        cost_center_id: UUID | None = None,
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
            cost_center_id=cost_center_id,
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
        cost_center_id: UUID | None = None,
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
            cost_center_id=cost_center_id,
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
        cost_center_id: UUID | None = None,
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
            cost_center_id=cost_center_id,
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
        cost_center_id: UUID | None,
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
                cost_center_id=cost_center_id,
            )
            opening_d, opening_c = opening_map.get(account.id, (_ZERO, _ZERO))
            opening_signed = self._signed(account.account_type, opening_d, opening_c)
            movements = await self._ledger_movements(
                tenant_id,
                account_id=account.id,
                from_date=from_date,
                to_date=to_date,
                branch_id=branch_id,
                cost_center_id=cost_center_id,
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
        cost_center_id: UUID | None,
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
        if cost_center_id is not None:
            statement = statement.where(
                (JournalEntryLine.cost_center_id == cost_center_id)
                | (JournalEntry.cost_center_id == cost_center_id)
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
        party_type: PartyType,
        party_id: UUID,
        from_date: date,
        to_date: date,
    ) -> AccountStatementResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        opening_d, opening_c = await self._sum_party(
            tenant_id, party_type=party_type.value, party_id=party_id, before=from_date
        )
        running = quantize_money(opening_d - opening_c)
        statement = (
            select(JournalEntryLine, JournalEntry)
            .join(JournalEntry, _posted_join())
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntryLine.party_type == party_type.value,
                JournalEntryLine.party_id == party_id,
                JournalEntry.entry_date >= from_date,
                JournalEntry.entry_date <= to_date,
            )
            .order_by(
                JournalEntry.entry_date.asc(),
                JournalEntryLine.due_date.asc().nulls_last(),
                JournalEntryLine.line_number.asc(),
            )
        )
        rows = (await self.session.execute(statement)).all()
        lines: list[AccountStatementLine] = []
        for line, header in rows:
            running = quantize_money(running + line.debit_base - line.credit_base)
            lines.append(
                AccountStatementLine(
                    journal_entry_id=header.id,
                    document_number=header.document_number,
                    entry_date=header.entry_date,
                    due_date=line.due_date,
                    external_reference=line.external_reference,
                    debit=line.debit_base,
                    credit=line.credit_base,
                    running_balance=running,
                    description=line.description,
                )
            )
        return AccountStatementResponse(
            currency_code=await self._report_currency_code(tenant_id),
            party_type=party_type.value,
            party_id=party_id,
            from_date=from_date,
            to_date=to_date,
            opening_balance=quantize_money(opening_d - opening_c),
            closing_balance=running,
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
        cost_center_id: UUID | None = None,
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
        if cost_center_id is not None:
            statement = statement.where(
                (JournalEntryLine.cost_center_id == cost_center_id)
                | (JournalEntry.cost_center_id == cost_center_id)
            )
        result: dict[UUID, tuple[Decimal, Decimal]] = {}
        for account_id_row, debit, credit in (await self.session.execute(statement)).all():
            result[account_id_row] = (
                quantize_money(Decimal(debit)),
                quantize_money(Decimal(credit)),
            )
        return result

    async def _sum_by_account_and_cost_center(
        self,
        tenant_id: UUID,
        *,
        start: date,
        end: date,
        branch_id: UUID | None = None,
    ) -> dict[tuple[UUID | None, UUID], tuple[Decimal, Decimal]]:
        center = func.coalesce(JournalEntryLine.cost_center_id, JournalEntry.cost_center_id)
        statement = (
            select(
                center,
                JournalEntryLine.account_id,
                func.coalesce(func.sum(JournalEntryLine.debit_base), 0),
                func.coalesce(func.sum(JournalEntryLine.credit_base), 0),
            )
            .join(JournalEntry, _posted_join())
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntry.entry_date >= start,
                JournalEntry.entry_date <= end,
            )
            .group_by(center, JournalEntryLine.account_id)
        )
        if branch_id is not None:
            statement = statement.where(
                (JournalEntryLine.branch_id == branch_id) | (JournalEntry.branch_id == branch_id)
            )
        rows = (await self.session.execute(statement)).all()
        result: dict[tuple[UUID | None, UUID], tuple[Decimal, Decimal]] = {}
        for center_id, account_id_row, debit, credit in rows:
            result[(center_id, account_id_row)] = (
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
            tuple[date, date, UUID | None, UUID | None], dict[UUID, tuple[Decimal, Decimal]]
        ] = {}
        lines: list[BudgetVsActualLine] = []
        for line in budget.lines:
            if line.period_start < month_start(from_date) or line.period_start > to_date:
                continue
            account = accounts.get(line.account_id)
            if account is None:
                continue
            end = min(month_end(line.period_start), to_date)
            cache_key = (line.period_start, end, line.cost_center_id, line.branch_id)
            actual_map = actual_cache.get(cache_key)
            if actual_map is None:
                actual_map = await self._sum_by_account(
                    tenant_id,
                    start=line.period_start,
                    end=end,
                    branch_id=line.branch_id,
                    cost_center_id=line.cost_center_id,
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
                    cost_center_id=line.cost_center_id,
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
    ) -> PartyStatementResponse:
        return await self._party_document_statement(
            tenant_id, PartyType.CUSTOMER, customer_id, from_date=from_date, to_date=to_date
        )

    async def supplier_statement(
        self,
        tenant_id: UUID,
        supplier_id: UUID,
        *,
        from_date: date,
        to_date: date,
    ) -> PartyStatementResponse:
        return await self._party_document_statement(
            tenant_id, PartyType.SUPPLIER, supplier_id, from_date=from_date, to_date=to_date
        )

    async def customer_outstanding(
        self, tenant_id: UUID, customer_id: UUID, *, as_of: date | None = None
    ) -> OutstandingSummary:
        from app.crm.customers.service import CustomerService
        from app.erp.accounting.open_items.service import OpenItemsService

        customer = await CustomerService(self.session).get(tenant_id, customer_id)
        items = await OpenItemsService(self.session).list_ar_open_items(tenant_id, customer_id)
        return self._outstanding_from_items(
            customer_id,
            items,
            as_of=as_of or utcnow().date(),
            credit_limit=customer.credit_limit,
            party_type=PartyType.CUSTOMER,
            currency_code=await self._report_currency_code(tenant_id),
        )

    async def supplier_outstanding(
        self, tenant_id: UUID, supplier_id: UUID, *, as_of: date | None = None
    ) -> OutstandingSummary:
        from app.erp.accounting.open_items.service import OpenItemsService

        items = await OpenItemsService(self.session).list_ap_open_items(tenant_id, supplier_id)
        return self._outstanding_from_items(
            supplier_id,
            items,
            as_of=as_of or utcnow().date(),
            credit_limit=None,
            party_type=PartyType.SUPPLIER,
            currency_code=await self._report_currency_code(tenant_id),
        )

    async def _aging(self, tenant_id: UUID, *, as_of: date, party_type: PartyType) -> AgingResponse:
        from app.erp.accounting.open_items.service import OpenItemsService

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
        open_items = OpenItemsService(self.session)
        rows: list[AgingPartyRow] = []
        totals = AgingBucketTotals()
        warnings: list[ReportWarning] = []
        report_currency = await self._report_currency_code(tenant_id)
        for party in parties:
            if party_type == PartyType.CUSTOMER:
                items = await open_items.list_ar_open_items(tenant_id, party.id)
            else:
                items = await open_items.list_ap_open_items(tenant_id, party.id)
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

    async def _party_document_statement(
        self,
        tenant_id: UUID,
        party_type: PartyType,
        party_id: UUID,
        *,
        from_date: date,
        to_date: date,
    ) -> PartyStatementResponse:
        from app.crm.customers.service import (
            CUSTOMER_PARTY_ROLE,
            SUPPLIER_PARTY_ROLE,
            CustomerService,
        )
        from app.erp.accounting.customer_payments.models import CustomerPayment
        from app.erp.accounting.supplier_payments.models import SupplierPayment
        from app.erp.credit_notes.models import CreditNote
        from app.erp.debit_notes.models import DebitNote
        from app.erp.purchase_invoices.models import PurchaseInvoice

        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        role = CUSTOMER_PARTY_ROLE if party_type == PartyType.CUSTOMER else SUPPLIER_PARTY_ROLE
        party = await CustomerService(self.session, role=role).get(tenant_id, party_id)
        events: list[
            tuple[
                date,
                str,
                UUID,
                str,
                Decimal,
                Decimal,
                date | None,
                str | None,
                UUID,
                Decimal,
            ]
        ] = []
        if party_type == PartyType.CUSTOMER:
            invoices = (
                (
                    await self.session.execute(
                        select(SalesInvoice).where(
                            SalesInvoice.tenant_id == tenant_id,
                            SalesInvoice.customer_id == party_id,
                            SalesInvoice.deleted_at.is_(None),
                            SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in invoices:
                amount = document_base_grand(row)
                events.append(
                    (
                        row.invoice_date,
                        "SALES_INVOICE",
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
            invoices = (
                (
                    await self.session.execute(
                        select(PurchaseInvoice).where(
                            PurchaseInvoice.tenant_id == tenant_id,
                            PurchaseInvoice.supplier_id == party_id,
                            PurchaseInvoice.deleted_at.is_(None),
                            PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in invoices:
                amount = document_base_grand(row)
                events.append(
                    (
                        row.invoice_date,
                        "PURCHASE_INVOICE",
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
        events.sort(key=lambda item: (item[0], item[3]))
        currency_codes = await self.currencies.codes_by_ids(
            tenant_id, [event[8] for event in events]
        )
        opening = _ZERO
        lines: list[PartyStatementLine] = []
        running = _ZERO
        for (
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
        ) in events:
            signed = quantize_money(debit - credit)
            if doc_date < from_date:
                opening = quantize_money(opening + signed)
                continue
            if doc_date > to_date:
                continue
            if not lines:
                running = opening
            running = quantize_money(running + signed)
            lines.append(
                PartyStatementLine(
                    document_type=doc_type,
                    document_id=doc_id,
                    document_number=number,
                    document_date=doc_date,
                    due_date=due,
                    currency_code=currency_codes.get(currency_id),
                    exchange_rate=exchange_rate,
                    debit=debit,
                    credit=credit,
                    running_balance=running,
                    description=description,
                )
            )
        if not lines:
            running = opening
        return PartyStatementResponse(
            currency_code=await self._report_currency_code(tenant_id),
            party_type=party_type.value,
            party_id=party_id,
            party_name=party.name,
            from_date=from_date,
            to_date=to_date,
            opening_balance=opening,
            closing_balance=running,
            lines=lines,
        )
