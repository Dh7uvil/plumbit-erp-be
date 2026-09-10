"""Trial balance, general ledger, and party account statement."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.currency import quantize_money
from app.core.enums import AccountType, JournalEntryStatus, PartyType
from app.core.exceptions import ValidationError
from app.erp.accounting.accounts.service import AccountService
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
from app.erp.accounting.reports.schemas import (
    AccountStatementLine,
    AccountStatementResponse,
    GeneralLedgerLine,
    GeneralLedgerResponse,
    TrialBalanceLine,
    TrialBalanceResponse,
)

_ZERO = Decimal("0")
_DEBIT_NORMAL = frozenset({AccountType.ASSET.value, AccountType.EXPENSE.value})


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
