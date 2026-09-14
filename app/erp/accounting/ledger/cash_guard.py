"""Reject cash/bank outflows that would take the account below zero."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils.currency import quantize_money
from app.core.enums import AccountType, JournalEntryStatus
from app.core.exceptions import InsufficientCashError, ResourceNotFoundError
from app.erp.accounting.accounts.models import Account
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine

_ZERO = Decimal("0")
_DEBIT_NORMAL = frozenset({AccountType.ASSET.value, AccountType.EXPENSE.value})


async def assert_cash_available(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    account_id: UUID,
    outflow_base: Decimal,
    allow_negative_cash: bool,
    as_of: date | None = None,
) -> None:
    """Reject when posting would overdraw a cash/bank account unless the tenant allows it."""

    if allow_negative_cash:
        return
    money = quantize_money(outflow_base)
    if money <= _ZERO:
        return
    account = await session.get(Account, account_id)
    if account is None or account.tenant_id != tenant_id or account.deleted_at is not None:
        raise ResourceNotFoundError("Payment account not found")
    statement = (
        select(
            func.coalesce(func.sum(JournalEntryLine.debit_base), 0),
            func.coalesce(func.sum(JournalEntryLine.credit_base), 0),
        )
        .join(
            JournalEntry,
            (JournalEntryLine.journal_entry_id == JournalEntry.id)
            & (JournalEntry.tenant_id == JournalEntryLine.tenant_id)
            & (JournalEntry.status == JournalEntryStatus.POSTED.value)
            & (JournalEntry.deleted_at.is_(None)),
        )
        .where(
            JournalEntryLine.tenant_id == tenant_id,
            JournalEntryLine.account_id == account_id,
        )
    )
    if as_of is not None:
        statement = statement.where(JournalEntry.entry_date <= as_of)
    debit, credit = (await session.execute(statement)).one()
    debit_amt = quantize_money(Decimal(debit))
    credit_amt = quantize_money(Decimal(credit))
    if account.account_type in _DEBIT_NORMAL:
        balance = quantize_money(debit_amt - credit_amt)
    else:
        balance = quantize_money(credit_amt - debit_amt)
    remaining = quantize_money(balance - money)
    if remaining < _ZERO:
        raise InsufficientCashError(
            details={
                "account_id": str(account_id),
                "account_code": account.code,
                "available": str(balance),
                "requested": str(money),
            }
        )
