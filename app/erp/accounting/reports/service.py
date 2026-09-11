"""Trial balance, general ledger, party statements, and tax exception reports."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.utils.currency import quantize_money
from app.common.utils.datetime import utcnow
from app.common.utils.export_evidence import has_export_evidence
from app.core.enums import (
    AccountType,
    CogsStatus,
    CompanyType,
    InvoiceDocumentStatus,
    JournalEntryStatus,
    OpenItemType,
    PartyType,
)
from app.core.exceptions import ValidationError
from app.crm.customers.models import Customer
from app.erp.accounting.accounts.service import AccountService
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
from app.erp.accounting.reports.schemas import (
    AccountStatementLine,
    AccountStatementResponse,
    AgingBucketTotals,
    AgingPartyRow,
    AgingResponse,
    ExportEvidenceExceptionLine,
    ExportEvidenceExceptionResponse,
    GeneralLedgerLine,
    GeneralLedgerResponse,
    InvoicedNotDispatchedLine,
    InvoicedNotDispatchedResponse,
    OutstandingSummary,
    PartyStatementLine,
    PartyStatementResponse,
    TrialBalanceLine,
    TrialBalanceResponse,
)
from app.erp.sales_invoices.models import SalesInvoice, SalesInvoiceLine

_ZERO = Decimal("0")
_DEBIT_NORMAL = frozenset({AccountType.ASSET.value, AccountType.EXPENSE.value})
EXPORT_EVIDENCE_WINDOW_DAYS = 90


def _posted_join():
    return and_(
        JournalEntryLine.journal_entry_id == JournalEntry.id,
        JournalEntry.tenant_id == JournalEntryLine.tenant_id,
        JournalEntry.status == JournalEntryStatus.POSTED.value,
        JournalEntry.deleted_at.is_(None),
    )


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounts = AccountService(session)

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
            tenant_id, start=from_date, end=to_date, branch_id=branch_id
        )
        lines: list[TrialBalanceLine] = []
        tot_od = tot_oc = tot_pd = tot_pc = tot_cd = tot_cc = _ZERO
        for account in accounts:
            if account.is_group and not include_zero:
                continue
            opening = opening_map.get(account.id, (_ZERO, _ZERO))
            period = period_map.get(account.id, (_ZERO, _ZERO))
            closing_d = quantize_money(opening[0] + period[0])
            closing_c = quantize_money(opening[1] + period[1])
            if (
                not include_zero
                and opening == (_ZERO, _ZERO)
                and period == (_ZERO, _ZERO)
            ):
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
                )
            )
            tot_od += opening[0]
            tot_oc += opening[1]
            tot_pd += period[0]
            tot_pc += period[1]
            tot_cd += closing_d
            tot_cc += closing_c
        tot_od, tot_oc, tot_pd, tot_pc, tot_cd, tot_cc = (
            quantize_money(tot_od),
            quantize_money(tot_oc),
            quantize_money(tot_pd),
            quantize_money(tot_pc),
            quantize_money(tot_cd),
            quantize_money(tot_cc),
        )
        return TrialBalanceResponse(
            from_date=from_date,
            to_date=to_date,
            is_balanced=tot_cd == tot_cc,
            total_opening_debit=tot_od,
            total_opening_credit=tot_oc,
            total_period_debit=tot_pd,
            total_period_credit=tot_pc,
            total_closing_debit=tot_cd,
            total_closing_credit=tot_cc,
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
        rows = (await self.session.execute(statement)).all()
        lines: list[GeneralLedgerLine] = []
        for line, header in rows:
            running = quantize_money(
                running
                + self._delta(account.account_type, line.debit_base, line.credit_base)
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
        return GeneralLedgerResponse(
            account_id=account.id,
            account_code=account.code,
            account_name=account.name,
            from_date=from_date,
            to_date=to_date,
            opening_balance=self._signed(account.account_type, opening_d, opening_c),
            closing_balance=running,
            lines=lines,
        )

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
                    grand_total=invoice.grand_total,
                    days_elapsed=days_elapsed,
                    window_days=EXPORT_EVIDENCE_WINDOW_DAYS,
                    overdue=days_elapsed > EXPORT_EVIDENCE_WINDOW_DAYS,
                )
            )
        return ExportEvidenceExceptionResponse(
            as_of=as_of_date,
            window_days=EXPORT_EVIDENCE_WINDOW_DAYS,
            lines=lines,
        )

    async def invoiced_not_dispatched(
        self, tenant_id: UUID
    ) -> InvoicedNotDispatchedResponse:
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
                    amount=row[9],
                    cogs_status=str(row[10]),
                )
                for row in rows
            ]
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
        result: dict[UUID, tuple[Decimal, Decimal]] = {}
        for account_id_row, debit, credit in (await self.session.execute(statement)).all():
            result[account_id_row] = (
                quantize_money(Decimal(debit)),
                quantize_money(Decimal(credit)),
            )
        return result

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
        )

    async def _aging(
        self, tenant_id: UUID, *, as_of: date, party_type: PartyType
    ) -> AgingResponse:
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
        for party in parties:
            if party_type == PartyType.CUSTOMER:
                items = await open_items.list_ar_open_items(tenant_id, party.id)
            else:
                items = await open_items.list_ap_open_items(tenant_id, party.id)
            buckets = self._bucket_items(items, as_of=as_of, party_type=party_type)
            if all(value == _ZERO for value in buckets.model_dump().values()):
                continue
            rows.append(
                AgingPartyRow(
                    party_id=party.id,
                    party_name=party.name,
                    currency_id=party.currency_id,
                    **buckets.model_dump(),
                )
            )
            for name, value in buckets.model_dump().items():
                setattr(totals, name, quantize_money(getattr(totals, name) + value))
        rows.sort(key=lambda row: row.party_name)
        return AgingResponse(as_of=as_of, rows=rows, totals=totals)

    def _bucket_items(
        self, items, *, as_of: date, party_type: PartyType
    ) -> AgingBucketTotals:
        buckets = AgingBucketTotals()
        outstanding_types = (
            {OpenItemType.SALES_INVOICE, OpenItemType.OPENING_AR}
            if party_type == PartyType.CUSTOMER
            else {OpenItemType.PURCHASE_INVOICE, OpenItemType.OPENING_AP}
        )
        credit_types = (
            {OpenItemType.CREDIT_NOTE}
            if party_type == PartyType.CUSTOMER
            else {OpenItemType.DEBIT_NOTE}
        )
        for item in items:
            if item.document_date > as_of:
                continue
            if item.item_type in credit_types:
                buckets.unapplied_credits = quantize_money(
                    buckets.unapplied_credits + item.balance
                )
                continue
            if item.item_type not in outstanding_types:
                continue
            due = item.due_date or item.document_date
            days = (as_of - due).days
            amount = item.balance
            if days <= 0:
                buckets.current = quantize_money(buckets.current + amount)
            elif days <= 30:
                buckets.days_1_30 = quantize_money(buckets.days_1_30 + amount)
            elif days <= 60:
                buckets.days_31_60 = quantize_money(buckets.days_31_60 + amount)
            elif days <= 90:
                buckets.days_61_90 = quantize_money(buckets.days_61_90 + amount)
            else:
                buckets.days_91_plus = quantize_money(buckets.days_91_plus + amount)
        buckets.total = quantize_money(
            buckets.current
            + buckets.days_1_30
            + buckets.days_31_60
            + buckets.days_61_90
            + buckets.days_91_plus
            - buckets.unapplied_credits
        )
        return buckets

    def _outstanding_from_items(
        self,
        party_id: UUID,
        items,
        *,
        as_of: date,
        credit_limit: Decimal | None,
        party_type: PartyType,
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
            if item.item_type in credit_types:
                unapplied = quantize_money(unapplied + item.balance)
                continue
            if item.item_type not in outstanding_types:
                continue
            balance_due = quantize_money(balance_due + item.balance)
            due = item.due_date or item.document_date
            if due < as_of:
                overdue = quantize_money(overdue + item.balance)
        available = None
        if credit_limit is not None:
            available = quantize_money(credit_limit - (balance_due - unapplied))
        return OutstandingSummary(
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
        from app.erp.credit_notes.models import CreditNote
        from app.erp.customer_payments.models import CustomerPayment
        from app.erp.debit_notes.models import DebitNote
        from app.erp.purchase_invoices.models import PurchaseInvoice
        from app.erp.supplier_payments.models import SupplierPayment

        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        role = CUSTOMER_PARTY_ROLE if party_type == PartyType.CUSTOMER else SUPPLIER_PARTY_ROLE
        party = await CustomerService(self.session, role=role).get(tenant_id, party_id)
        events: list[tuple[date, str, UUID, str, Decimal, Decimal, date | None, str | None]] = []
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
                events.append(
                    (
                        row.invoice_date,
                        "SALES_INVOICE",
                        row.id,
                        row.document_number,
                        row.grand_total,
                        _ZERO,
                        row.due_date,
                        None,
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
                events.append(
                    (
                        row.credit_note_date,
                        "CREDIT_NOTE",
                        row.id,
                        row.document_number,
                        _ZERO,
                        row.grand_total,
                        row.due_date,
                        None,
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
                events.append(
                    (
                        row.payment_date,
                        "CUSTOMER_PAYMENT",
                        row.id,
                        row.document_number,
                        _ZERO,
                        row.amount_received,
                        None,
                        row.reference,
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
                events.append(
                    (
                        row.invoice_date,
                        "PURCHASE_INVOICE",
                        row.id,
                        row.document_number,
                        _ZERO,
                        row.grand_total,
                        row.due_date,
                        None,
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
                events.append(
                    (
                        row.debit_note_date,
                        "DEBIT_NOTE",
                        row.id,
                        row.document_number,
                        row.grand_total,
                        _ZERO,
                        row.due_date,
                        None,
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
                events.append(
                    (
                        row.payment_date,
                        "SUPPLIER_PAYMENT",
                        row.id,
                        row.document_number,
                        row.amount_paid,
                        _ZERO,
                        None,
                        row.reference,
                    )
                )
        events.sort(key=lambda item: (item[0], item[3]))
        opening = _ZERO
        lines: list[PartyStatementLine] = []
        running = _ZERO
        for doc_date, doc_type, doc_id, number, debit, credit, due, description in events:
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
                    debit=debit,
                    credit=credit,
                    running_balance=running,
                    description=description,
                )
            )
        if not lines:
            running = opening
        return PartyStatementResponse(
            party_type=party_type.value,
            party_id=party_id,
            party_name=party.name,
            from_date=from_date,
            to_date=to_date,
            opening_balance=opening,
            closing_balance=running,
            lines=lines,
        )
