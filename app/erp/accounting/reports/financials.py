"""Profit and loss, balance sheet, and indirect cash flow."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from app.common.utils.currency import quantize_money
from app.core.enums import AccountSubtype, AccountSystemRole, AccountType
from app.core.exceptions import ValidationError
from app.erp.accounting.reports.schemas import (
    BalanceSheetLine,
    BalanceSheetResponse,
    CashFlowLine,
    CashFlowResponse,
    ProfitAndLossLine,
    ProfitAndLossResponse,
)

_ZERO = Decimal("0")
_PL_TYPES = frozenset({AccountType.INCOME.value, AccountType.EXPENSE.value})
_CASH_SUBTYPES = frozenset({AccountSubtype.CASH.value, AccountSubtype.BANK.value})


class FinancialReports:
    async def profit_and_loss(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        branch_id: UUID | None = None,
        include_ytd: bool = False,
    ) -> ProfitAndLossResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        span = (to_date - from_date).days + 1
        comparative_to = from_date - timedelta(days=1)
        comparative_from = comparative_to - timedelta(days=span - 1)
        ytd_from = date(to_date.year, 1, 1) if include_ytd else None
        current_map = await self._sum_by_account(
            tenant_id, start=from_date, end=to_date, branch_id=branch_id
        )
        comparative_map = await self._sum_by_account(
            tenant_id, start=comparative_from, end=comparative_to, branch_id=branch_id
        )
        ytd_map = (
            await self._sum_by_account(tenant_id, start=ytd_from, end=to_date, branch_id=branch_id)
            if ytd_from is not None
            else {}
        )
        accounts = await self.accounts.repo.list_all(tenant_id)
        lines: list[ProfitAndLossLine] = []
        total_income = _ZERO
        total_expense = _ZERO
        comparative_income = _ZERO
        comparative_expense = _ZERO
        ytd_income = _ZERO
        ytd_expense = _ZERO
        for account in accounts:
            if account.is_group or account.account_type not in _PL_TYPES:
                continue
            amount = self._signed(
                account.account_type, *current_map.get(account.id, (_ZERO, _ZERO))
            )
            comparative = self._signed(
                account.account_type, *comparative_map.get(account.id, (_ZERO, _ZERO))
            )
            ytd = (
                self._signed(account.account_type, *ytd_map.get(account.id, (_ZERO, _ZERO)))
                if include_ytd
                else None
            )
            if amount == _ZERO and comparative == _ZERO and (ytd is None or ytd == _ZERO):
                continue
            if account.account_type == AccountType.INCOME.value:
                total_income += amount
                comparative_income += comparative
                if ytd is not None:
                    ytd_income += ytd
            else:
                total_expense += amount
                comparative_expense += comparative
                if ytd is not None:
                    ytd_expense += ytd
            lines.append(
                ProfitAndLossLine(
                    account_id=account.id,
                    account_code=account.code,
                    account_name=account.name,
                    account_type=account.account_type,
                    account_subtype=account.account_subtype,
                    amount=amount,
                    comparative_amount=comparative,
                    ytd_amount=ytd,
                )
            )
        net_profit = quantize_money(total_income - total_expense)
        return ProfitAndLossResponse(
            from_date=from_date,
            to_date=to_date,
            comparative_from=comparative_from,
            comparative_to=comparative_to,
            ytd_from=ytd_from,
            total_income=quantize_money(total_income),
            total_expense=quantize_money(total_expense),
            net_profit=net_profit,
            comparative_net_profit=quantize_money(comparative_income - comparative_expense),
            ytd_net_profit=quantize_money(ytd_income - ytd_expense) if include_ytd else None,
            lines=lines,
        )

    async def balance_sheet(
        self,
        tenant_id: UUID,
        *,
        as_of: date,
        branch_id: UUID | None = None,
        include_comparative: bool = True,
    ) -> BalanceSheetResponse:
        current = await self._balance_sheet_at(tenant_id, as_of=as_of, branch_id=branch_id)
        comparative_as_of: date | None = None
        prior: BalanceSheetResponse | None = None
        if include_comparative:
            try:
                comparative_as_of = as_of.replace(year=as_of.year - 1)
            except ValueError:
                comparative_as_of = as_of.replace(year=as_of.year - 1, day=28)
            prior = await self._balance_sheet_at(
                tenant_id, as_of=comparative_as_of, branch_id=branch_id
            )
            prior_by_id = {line.account_id: line.amount for line in prior.lines}
            for line in current.lines:
                line.comparative_amount = prior_by_id.get(line.account_id, _ZERO)
        current.comparative_as_of = comparative_as_of
        if prior is not None:
            current.comparative_total_assets = prior.total_assets
            current.comparative_total_liabilities = prior.total_liabilities
            current.comparative_total_equity = prior.total_equity
        return current

    async def _balance_sheet_at(
        self,
        tenant_id: UUID,
        *,
        as_of: date,
        branch_id: UUID | None = None,
    ) -> BalanceSheetResponse:
        accounts = await self.accounts.repo.list_all(tenant_id)
        closing = await self._sum_by_account(tenant_id, end=as_of, branch_id=branch_id)
        lines: list[BalanceSheetLine] = []
        total_assets = _ZERO
        total_liabilities = _ZERO
        total_equity = _ZERO
        current_earnings = _ZERO
        retained_earnings_id = None
        for account in accounts:
            if account.is_group:
                continue
            amount = self._signed(account.account_type, *closing.get(account.id, (_ZERO, _ZERO)))
            if account.account_type in _PL_TYPES:
                if account.account_type == AccountType.INCOME.value:
                    current_earnings += amount
                else:
                    current_earnings -= amount
                continue
            if account.system_role == AccountSystemRole.RETAINED_EARNINGS.value:
                retained_earnings_id = account.id
            if amount == _ZERO and account.system_role != AccountSystemRole.RETAINED_EARNINGS.value:
                continue
            if account.account_type == AccountType.ASSET.value:
                total_assets += amount
            elif account.account_type == AccountType.LIABILITY.value:
                total_liabilities += amount
            else:
                total_equity += amount
            lines.append(
                BalanceSheetLine(
                    account_id=account.id,
                    account_code=account.code,
                    account_name=account.name,
                    account_type=account.account_type,
                    account_subtype=account.account_subtype,
                    amount=amount,
                )
            )
        current_earnings = quantize_money(current_earnings)
        if current_earnings != _ZERO:
            rolled = False
            for line in lines:
                if line.account_id == retained_earnings_id:
                    line.amount = quantize_money(line.amount + current_earnings)
                    total_equity = quantize_money(total_equity + current_earnings)
                    rolled = True
                    break
            if not rolled:
                total_equity = quantize_money(total_equity + current_earnings)
                lines.append(
                    BalanceSheetLine(
                        account_id=retained_earnings_id,
                        account_code="RE",
                        account_name="Current earnings",
                        account_type=AccountType.EQUITY.value,
                        account_subtype=AccountSubtype.EQUITY.value,
                        amount=current_earnings,
                    )
                )
        total_assets = quantize_money(total_assets)
        total_liabilities = quantize_money(total_liabilities)
        total_equity = quantize_money(total_equity)
        return BalanceSheetResponse(
            as_of=as_of,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            total_equity=total_equity,
            current_earnings=current_earnings,
            is_balanced=total_assets == quantize_money(total_liabilities + total_equity),
            lines=lines,
        )

    async def cash_flow(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        branch_id: UUID | None = None,
        include_comparative: bool = True,
    ) -> CashFlowResponse:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")
        pnl = await self.profit_and_loss(
            tenant_id, from_date=from_date, to_date=to_date, branch_id=branch_id
        )
        accounts = await self.accounts.repo.list_all(tenant_id)
        opening = await self._sum_by_account(tenant_id, before=from_date, branch_id=branch_id)
        closing = await self._sum_by_account(tenant_id, end=to_date, branch_id=branch_id)

        def _subtype_delta(subtype: str) -> Decimal:
            open_total = _ZERO
            close_total = _ZERO
            for account in accounts:
                if account.is_group or account.account_subtype != subtype:
                    continue
                open_total += self._signed(
                    account.account_type, *opening.get(account.id, (_ZERO, _ZERO))
                )
                close_total += self._signed(
                    account.account_type, *closing.get(account.id, (_ZERO, _ZERO))
                )
            return quantize_money(close_total - open_total)

        def _role_delta(role: AccountSystemRole) -> tuple[Decimal, UUID | None]:
            account = next((row for row in accounts if row.system_role == role.value), None)
            if account is None:
                return _ZERO, None
            open_amt = self._signed(account.account_type, *opening.get(account.id, (_ZERO, _ZERO)))
            close_amt = self._signed(account.account_type, *closing.get(account.id, (_ZERO, _ZERO)))
            return quantize_money(close_amt - open_amt), account.id

        cash_opening = _ZERO
        cash_closing = _ZERO
        cash_account_id = None
        for account in accounts:
            if account.is_group or account.account_subtype not in _CASH_SUBTYPES:
                continue
            cash_opening += self._signed(
                account.account_type, *opening.get(account.id, (_ZERO, _ZERO))
            )
            cash_closing += self._signed(
                account.account_type, *closing.get(account.id, (_ZERO, _ZERO))
            )
            if account.system_role == AccountSystemRole.BANK.value:
                cash_account_id = account.id
        cash_opening = quantize_money(cash_opening)
        cash_closing = quantize_money(cash_closing)
        net_change = quantize_money(cash_closing - cash_opening)

        delta_ar = _subtype_delta(AccountSubtype.ACCOUNTS_RECEIVABLE.value)
        delta_stock = _subtype_delta(AccountSubtype.STOCK.value)
        delta_ap = _subtype_delta(AccountSubtype.ACCOUNTS_PAYABLE.value)
        delta_tax_rec = _subtype_delta(AccountSubtype.TAX_RECEIVABLE.value)
        delta_tax_pay = _subtype_delta(AccountSubtype.TAX_PAYABLE.value)
        delta_adv_in, adv_in_id = _role_delta(AccountSystemRole.ADVANCE_FROM_CUSTOMER)
        delta_adv_out, adv_out_id = _role_delta(AccountSystemRole.ADVANCE_TO_SUPPLIER)

        operations = quantize_money(
            pnl.net_profit
            - delta_ar
            - delta_stock
            + delta_ap
            - delta_tax_rec
            + delta_tax_pay
            + delta_adv_in
            - delta_adv_out
        )
        other = quantize_money(net_change - operations)
        lines = [
            CashFlowLine(key="net_profit", label="Net profit", amount=pnl.net_profit),
            CashFlowLine(
                key="accounts_receivable",
                label="(Increase)/decrease in accounts receivable",
                amount=quantize_money(-delta_ar),
            ),
            CashFlowLine(
                key="inventory",
                label="(Increase)/decrease in inventory",
                amount=quantize_money(-delta_stock),
            ),
            CashFlowLine(
                key="accounts_payable",
                label="Increase/(decrease) in accounts payable",
                amount=delta_ap,
            ),
            CashFlowLine(
                key="tax_receivable",
                label="(Increase)/decrease in tax receivable",
                amount=quantize_money(-delta_tax_rec),
            ),
            CashFlowLine(
                key="tax_payable",
                label="Increase/(decrease) in tax payable",
                amount=delta_tax_pay,
            ),
            CashFlowLine(
                key="customer_advances",
                label="Increase/(decrease) in customer advances",
                amount=delta_adv_in,
                account_id=adv_in_id,
            ),
            CashFlowLine(
                key="supplier_advances",
                label="(Increase)/decrease in supplier advances",
                amount=quantize_money(-delta_adv_out),
                account_id=adv_out_id,
            ),
            CashFlowLine(
                key="other",
                label="Other operating / reconciling items",
                amount=other,
            ),
            CashFlowLine(
                key="net_change_in_cash",
                label="Net change in cash and bank",
                amount=net_change,
                account_id=cash_account_id,
            ),
        ]
        comparative_from = None
        comparative_to = None
        comparative_net_change = None
        if include_comparative:
            span = (to_date - from_date).days + 1
            comparative_to = from_date - timedelta(days=1)
            comparative_from = comparative_to - timedelta(days=span - 1)
            prior = await self.cash_flow(
                tenant_id,
                from_date=comparative_from,
                to_date=comparative_to,
                branch_id=branch_id,
                include_comparative=False,
            )
            prior_by_key = {line.key: line.amount for line in prior.lines}
            for line in lines:
                line.comparative_amount = prior_by_key.get(line.key, _ZERO)
            comparative_net_change = prior.net_change
        return CashFlowResponse(
            from_date=from_date,
            to_date=to_date,
            comparative_from=comparative_from,
            comparative_to=comparative_to,
            net_profit=pnl.net_profit,
            cash_opening=cash_opening,
            cash_closing=cash_closing,
            net_change=net_change,
            comparative_net_change=comparative_net_change,
            lines=lines,
        )
