"""Party PDC and fiscal period balance summaries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.currency import quantize_money
from app.core.enums import (
    AccountSubtype,
    AccountType,
    ChequeDirection,
    ChequeStatus,
    JournalEntryStatus,
)
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.crm.customers.models import Customer
from app.crm.customers.schemas import (
    PartyPdcBalanceResponse,
    PartyPeriodBalance,
    PartyPeriodBalancesResponse,
)
from app.erp.accounting.accounts.service import PartyAccountResolver
from app.erp.accounting.cheques.models import Cheque
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
from app.erp.exchange_rates.service import CurrencyService
from app.erp.accounting.fiscal import FiscalYearConfig


class PartyBalanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.party_accounts = PartyAccountResolver(session)
        self.currencies = CurrencyService(session)

    async def pdc_balance(
        self,
        tenant_id: UUID,
        party_id: UUID,
        *,
        receivable: bool,
    ) -> PartyPdcBalanceResponse:
        row = await self.session.get(Customer, party_id)
        if row is None or row.tenant_id != tenant_id or row.deleted_at is not None:
            raise ResourceNotFoundError("Party not found")
        direction = ChequeDirection.INBOUND if receivable else ChequeDirection.OUTBOUND
        pending = (ChequeStatus.ISSUED.value, ChequeStatus.DEPOSITED.value)
        statement = select(Cheque.amount, Cheque.base_amount, Cheque.currency_id).where(
            Cheque.tenant_id == tenant_id,
            Cheque.deleted_at.is_(None),
            Cheque.party_id == party_id,
            Cheque.direction == direction.value,
            Cheque.status.in_(pending),
        )
        rows = (await self.session.execute(statement)).all()
        party_currency = await self.currencies.get(tenant_id, row.currency_id)
        base = await self.currencies.get_base(tenant_id)
        party_total = Decimal("0")
        base_total = Decimal("0")
        for amount, base_amount, currency_id in rows:
            base_total += Decimal(base_amount)
            if currency_id == row.currency_id:
                party_total += Decimal(amount)
            else:
                party_total += Decimal(base_amount)
        return PartyPdcBalanceResponse(
            party_id=party_id,
            cheque_count=len(rows),
            amount=quantize_money(party_total),
            base_amount=quantize_money(base_total),
            currency_code=party_currency.code,
            base_currency_code=base.code,
        )

    async def period_balances(
        self,
        tenant_id: UUID,
        party_id: UUID,
        *,
        receivable: bool,
        currency_mode: str,
        fiscal_year: int | None = None,
    ) -> PartyPeriodBalancesResponse:
        if currency_mode not in {"home", "party"}:
            raise ValidationError("currency_mode must be home or party")
        row = await self.session.get(Customer, party_id)
        if row is None or row.tenant_id != tenant_id or row.deleted_at is not None:
            raise ResourceNotFoundError("Party not found")
        if receivable:
            account = await self.party_accounts.resolve_receivable(tenant_id, party_id)
        else:
            account = await self.party_accounts.resolve_payable(tenant_id, party_id)

        config = await FiscalYearConfig.load(self.session, tenant_id)
        year = fiscal_year if fiscal_year is not None else config.year_for(date.today())
        fy_start, fy_end = config.bounds(year)
        base = await self.currencies.get_base(tenant_id)
        party_currency = await self.currencies.get(tenant_id, row.currency_id)
        use_party = currency_mode == "party"
        currency_code = party_currency.code if use_party else base.code

        debit_col = JournalEntryLine.debit if use_party else JournalEntryLine.debit_base
        credit_col = JournalEntryLine.credit if use_party else JournalEntryLine.credit_base

        statement = (
            select(
                JournalEntry.entry_date,
                debit_col,
                credit_col,
            )
            .select_from(JournalEntryLine)
            .join(
                JournalEntry,
                (JournalEntry.id == JournalEntryLine.journal_entry_id)
                & (JournalEntry.tenant_id == tenant_id)
                & (JournalEntry.deleted_at.is_(None))
                & (JournalEntry.status == JournalEntryStatus.POSTED.value),
            )
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntryLine.account_id == account.id,
                JournalEntryLine.party_id == party_id,
                JournalEntry.entry_date <= fy_end,
            )
        )
        if use_party:
            statement = statement.where(JournalEntryLine.currency_id == row.currency_id)

        rows = (await self.session.execute(statement)).all()
        period_ranges = config.period_bounds(year)
        period_totals: dict[int, tuple[Decimal, Decimal]] = {
            period: (Decimal("0"), Decimal("0")) for period, _, _ in period_ranges
        }
        opening_debit = Decimal("0")
        opening_credit = Decimal("0")
        for entry_date, debit, credit in rows:
            debit = Decimal(debit)
            credit = Decimal(credit)
            if entry_date < fy_start:
                opening_debit += debit
                opening_credit += credit
                continue
            for period, start, end in period_ranges:
                if start <= entry_date <= end:
                    current = period_totals[period]
                    period_totals[period] = (current[0] + debit, current[1] + credit)
                    break

        account_type = AccountType(account.account_type)
        subtype = AccountSubtype(account.account_subtype)

        def signed_balance(debit_total: Decimal, credit_total: Decimal) -> Decimal:
            if account_type in {AccountType.ASSET, AccountType.EXPENSE}:
                return quantize_money(debit_total - credit_total)
            if subtype == AccountSubtype.ACCOUNTS_PAYABLE:
                return quantize_money(credit_total - debit_total)
            return quantize_money(credit_total - debit_total)

        opening = signed_balance(opening_debit, opening_credit)
        running_debit = opening_debit
        running_credit = opening_credit
        periods: list[PartyPeriodBalance] = []
        for period, start, end in period_ranges:
            debit, credit = period_totals[period]
            running_debit += debit
            running_credit += credit
            periods.append(
                PartyPeriodBalance(
                    period=period,
                    from_date=start,
                    to_date=end,
                    debit=quantize_money(debit),
                    credit=quantize_money(credit),
                    closing=signed_balance(running_debit, running_credit),
                )
            )
        closing = signed_balance(running_debit, running_credit)
        return PartyPeriodBalancesResponse(
            party_id=party_id,
            account_id=account.id,
            fiscal_year=year,
            currency_code=currency_code,
            currency_mode=currency_mode,
            opening=opening,
            periods=periods,
            closing=closing,
        )
