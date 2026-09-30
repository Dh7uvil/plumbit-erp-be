"""Fiscal year-end closing: preview, commit, and reopen."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ACCOUNTING_MODULE, PERIOD_OVERRIDE
from app.auth.models import Tenant
from app.common.idempotency.service import IdempotencyService
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money
from app.core.enums import AccountSystemRole, AccountType, AuditAction, JournalType
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.accounts.service import AccountService
from app.erp.accounting.fiscal import FiscalYearConfig
from app.erp.accounting.ledger.posting import SOURCE_YEAR_END_CLOSING, LedgerPostingService
from app.erp.accounting.ledger.repository import JournalEntryRepository
from app.erp.accounting.ledger.schemas import JournalLineInput
from app.erp.accounting.year_end.ids import fiscal_year_source_id
from app.erp.accounting.year_end.schemas import (
    YearEndPreviewLine,
    YearEndPreviewResponse,
    YearEndStateResponse,
)
from app.erp.exchange_rates.service import CurrencyService

_ZERO = Decimal("0")
_PL_TYPES = frozenset({AccountType.INCOME.value, AccountType.EXPENSE.value})


class YearEndService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.accounts = AccountService(session)
        self.posting = LedgerPostingService(session, actor_permissions=actor_permissions)
        self.journals = JournalEntryRepository(session)
        self.currencies = CurrencyService(session)
        self.idempotency = IdempotencyService(session)
        self.audit = AuditWriter(session)
        self._can_override = has_permission(actor_permissions, PERIOD_OVERRIDE)

    async def get_state(self, tenant_id: UUID, fiscal_year: int) -> YearEndStateResponse:
        fiscal = await FiscalYearConfig.load(self.session, tenant_id)
        fy_start, fy_end = fiscal.bounds(fiscal_year)
        closing = await self._active_closing(tenant_id, fiscal_year)
        tenant = await self._require_tenant(tenant_id)
        return YearEndStateResponse(
            fiscal_year=fiscal_year,
            from_date=fy_start,
            to_date=fy_end,
            is_closed=closing is not None,
            journal_entry_id=closing.id if closing else None,
            document_number=closing.document_number if closing else None,
            committed_at=closing.posted_at if closing else None,
            lock_date=tenant.lock_date,
        )

    async def preview(self, tenant_id: UUID, fiscal_year: int) -> YearEndPreviewResponse:
        built = await self._build_closing(tenant_id, fiscal_year)
        return built.preview

    async def commit(
        self,
        tenant_id: UUID,
        fiscal_year: int,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> YearEndStateResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return YearEndStateResponse.model_validate(replay)
            existing = await self._active_closing(tenant_id, fiscal_year)
            if existing is not None:
                state = await self.get_state(tenant_id, fiscal_year)
                await self.idempotency.store(
                    tenant_id, idempotency_key, state.model_dump(mode="json")
                )
                return state
            built = await self._build_closing(tenant_id, fiscal_year)
            if not built.journal_lines:
                raise ValidationError("No P&L activity to close for this fiscal year")
            currency_id = (await self.currencies.get_base(tenant_id)).id
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_YEAR_END_CLOSING,
                source_id=fiscal_year_source_id(fiscal_year),
                entry_date=built.entry_date,
                lines=built.journal_lines,
                currency_id=currency_id,
                exchange_rate=Decimal("1"),
                narration=f"Year-end closing FY{fiscal_year}",
                branch_id=None,
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
            )
            tenant = await self._require_tenant(tenant_id)
            if tenant.lock_date is None or tenant.lock_date < built.entry_date:
                tenant.lock_date = built.entry_date
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=ACCOUNTING_MODULE,
                entity_type="year_end_closing",
                entity_id=journal.id,
                new_values={
                    "fiscal_year": fiscal_year,
                    "journal_entry_id": str(journal.id),
                },
            )
            state = await self.get_state(tenant_id, fiscal_year)
            await self.idempotency.store(tenant_id, idempotency_key, state.model_dump(mode="json"))
            return state

    async def reopen(
        self,
        tenant_id: UUID,
        fiscal_year: int,
        *,
        actor_user_id: UUID,
    ) -> YearEndStateResponse:
        if not self._can_override:
            raise ValidationError("Reopening a closed year requires period override permission")
        async with transaction(self.session):
            closing = await self._active_closing(tenant_id, fiscal_year)
            if closing is None:
                raise ValidationError("This fiscal year has not been closed")
            fiscal = await FiscalYearConfig.load(self.session, tenant_id)
            _, fy_end = fiscal.bounds(fiscal_year)
            await self.posting.reverse(
                tenant_id,
                closing.id,
                reversal_date=fy_end,
                reason=f"Reopen fiscal year {fiscal_year}",
                actor_id=actor_user_id,
            )
            tenant = await self._require_tenant(tenant_id)
            if tenant.lock_date == fy_end:
                tenant.lock_date = fy_end - timedelta(days=1)
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.REVERSE,
                module=ACCOUNTING_MODULE,
                entity_type="year_end_closing",
                entity_id=closing.id,
                old_values={"fiscal_year": fiscal_year},
            )
            return await self.get_state(tenant_id, fiscal_year)

    async def latest_closed_end(self, tenant_id: UUID, *, as_of: date) -> date | None:
        fiscal = await FiscalYearConfig.load(self.session, tenant_id)
        candidate: date | None = None
        for year in range(fiscal.year_for(as_of), fiscal.year_for(as_of) - 20, -1):
            closing = await self._active_closing(tenant_id, year)
            if closing is None:
                continue
            _, fy_end = fiscal.bounds(year)
            if fy_end <= as_of and (candidate is None or fy_end > candidate):
                candidate = fy_end
        return candidate

    async def _active_closing(self, tenant_id: UUID, fiscal_year: int):
        closing = await self.journals.get_posted_for_source(
            tenant_id, SOURCE_YEAR_END_CLOSING, fiscal_year_source_id(fiscal_year)
        )
        if closing is not None and closing.reversed_by_id is not None:
            return None
        return closing

    async def _build_closing(self, tenant_id: UUID, fiscal_year: int) -> _BuiltClosing:
        from app.erp.accounting.reports.service import ReportService

        fiscal = await FiscalYearConfig.load(self.session, tenant_id)
        fy_start, fy_end = fiscal.bounds(fiscal_year)
        period_map = await ReportService(self.session)._sum_by_account(
            tenant_id, start=fy_start, end=fy_end
        )
        retained = await self.accounts.resolver.require(
            tenant_id, AccountSystemRole.RETAINED_EARNINGS
        )
        accounts = await self.accounts.repo.list_all(tenant_id)
        preview_lines: list[YearEndPreviewLine] = []
        journal_lines: list[JournalLineInput] = []
        net_profit = _ZERO
        for account in accounts:
            if account.is_group or account.account_type not in _PL_TYPES:
                continue
            debit, credit = period_map.get(account.id, (_ZERO, _ZERO))
            if debit == _ZERO and credit == _ZERO:
                continue
            closing_debit = _ZERO
            closing_credit = _ZERO
            if account.account_type == AccountType.INCOME.value:
                amount = quantize_money(credit - debit)
                if amount > _ZERO:
                    closing_debit = amount
                    net_profit += amount
                elif amount < _ZERO:
                    closing_credit = -amount
                    net_profit += amount
            else:
                amount = quantize_money(debit - credit)
                if amount > _ZERO:
                    closing_credit = amount
                    net_profit -= amount
                elif amount < _ZERO:
                    closing_debit = -amount
                    net_profit -= amount
            if closing_debit == _ZERO and closing_credit == _ZERO:
                continue
            journal_lines.append(
                JournalLineInput(
                    account_id=account.id,
                    debit=closing_debit,
                    credit=closing_credit,
                    description=f"Close FY{fiscal_year}",
                )
            )
            preview_lines.append(
                YearEndPreviewLine(
                    account_id=account.id,
                    account_code=account.code,
                    account_name=account.name,
                    account_type=account.account_type,
                    debit=debit,
                    credit=credit,
                    closing_debit=closing_debit,
                    closing_credit=closing_credit,
                )
            )
        net_profit = quantize_money(net_profit)
        if net_profit > _ZERO:
            journal_lines.append(
                JournalLineInput(
                    account_id=retained.id,
                    credit=net_profit,
                    description=f"Net profit FY{fiscal_year}",
                )
            )
        elif net_profit < _ZERO:
            journal_lines.append(
                JournalLineInput(
                    account_id=retained.id,
                    debit=-net_profit,
                    description=f"Net loss FY{fiscal_year}",
                )
            )
        total_debit = quantize_money(sum((line.debit for line in journal_lines), _ZERO))
        total_credit = quantize_money(sum((line.credit for line in journal_lines), _ZERO))
        preview = YearEndPreviewResponse(
            fiscal_year=fiscal_year,
            from_date=fy_start,
            to_date=fy_end,
            entry_date=fy_end,
            retained_earnings_account_id=retained.id,
            net_profit=net_profit,
            total_debit=total_debit,
            total_credit=total_credit,
            lines=preview_lines,
        )
        return _BuiltClosing(preview=preview, journal_lines=journal_lines, entry_date=fy_end)

    async def _require_tenant(self, tenant_id: UUID) -> Tenant:
        tenant = await self.session.get(Tenant, tenant_id)
        if tenant is None:
            raise ResourceNotFoundError("Tenant not found")
        return tenant


class _BuiltClosing:
    def __init__(
        self,
        *,
        preview: YearEndPreviewResponse,
        journal_lines: list[JournalLineInput],
        entry_date: date,
    ) -> None:
        self.preview = preview
        self.journal_lines = journal_lines
        self.entry_date = entry_date
