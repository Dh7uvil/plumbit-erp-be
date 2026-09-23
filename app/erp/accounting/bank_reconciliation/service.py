"""Bank reconciliation use cases."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ACCOUNTING_MODULE
from app.common.imex.commercial import import_result
from app.common.imex.schemas import ImexMappingEntry, ImportResult, ImportRowError
from app.common.imex.service import mapped_rows, parse_optional_date, parse_optional_decimal
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money
from app.core.enums import AuditAction, BankStatementMatchStatus, BankStatementStatus
from app.core.exceptions import DocumentStaleError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.accounting.bank_accounts.service import BankAccountService
from app.erp.exchange_rates.service import ExchangeRateService
from app.erp.accounting.bank_reconciliation.models import BankStatement, BankStatementLine
from app.erp.accounting.bank_reconciliation.repository import BankStatementRepository
from app.erp.accounting.bank_reconciliation.schemas import (
    BankStatementCreate,
    BankStatementLineInput,
    BankStatementResponse,
    BankStatementUpdate,
    BookEntryCandidate,
    MatchSuggestion,
    ReconciliationStatement,
)
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine

_ZERO = Decimal("0")


def _to_response(row: BankStatement) -> BankStatementResponse:
    return BankStatementResponse.model_validate(row)


class BankReconciliationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BankStatementRepository(session)
        self.bank_accounts = BankAccountService(session)
        self.fx = ExchangeRateService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        bank_account_id: UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[BankStatementResponse], int]:
        filters: dict[str, object] = {}
        if bank_account_id is not None:
            filters["bank_account_id"] = bank_account_id
        if status is not None:
            filters["status"] = status
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [_to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, statement_id: UUID) -> BankStatementResponse:
        return _to_response(await self._require(tenant_id, statement_id))

    async def create(
        self, tenant_id: UUID, payload: BankStatementCreate, *, actor_user_id: UUID
    ) -> BankStatementResponse:
        if payload.period_start > payload.period_end:
            raise ValidationError("period_start must be on or before period_end")
        bank = await self.bank_accounts.require(tenant_id, payload.bank_account_id)
        async with transaction(self.session):
            row = BankStatement(
                tenant_id=tenant_id,
                bank_account_id=payload.bank_account_id,
                period_start=payload.period_start,
                period_end=payload.period_end,
                opening_balance=payload.opening_balance,
                closing_balance=payload.closing_balance,
                status=BankStatementStatus.IMPORTED.value
                if payload.lines
                else BankStatementStatus.DRAFT.value,
                import_reference=payload.import_reference,
                notes=payload.notes,
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
            self._replace_lines(row, payload.lines)
            await self._apply_base_balances(tenant_id, row, bank)
            self.session.add(row)
            await self.session.flush()
            loaded = await self._require(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ACCOUNTING_MODULE,
                entity_type="bank_statement",
                entity_id=row.id,
                new_values={"bank_account_id": str(bank.id), "line_count": len(payload.lines)},
            )
            return _to_response(loaded)

    async def update(
        self,
        tenant_id: UUID,
        statement_id: UUID,
        payload: BankStatementUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> BankStatementResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, statement_id)
            self._assert_version(row, expected_version)
            if row.status == BankStatementStatus.RECONCILED.value:
                raise ValidationError("Reconciled statements cannot be edited")
            values = payload.model_dump(exclude={"version"}, exclude_unset=True)
            if "period_start" in values or "period_end" in values:
                start = values.get("period_start", row.period_start)
                end = values.get("period_end", row.period_end)
                if start > end:
                    raise ValidationError("period_start must be on or before period_end")
            updated = await self.repo.update(
                tenant_id,
                statement_id,
                {**values, "version": row.version + 1, "updated_by": actor_user_id},
            )
            if updated is None:
                raise ResourceNotFoundError("Bank statement not found")
            loaded = await self._require(tenant_id, statement_id)
            bank = await self.bank_accounts.require(tenant_id, loaded.bank_account_id)
            await self._apply_base_balances(tenant_id, loaded, bank)
            await self.session.flush()
            return _to_response(loaded)

    async def delete(
        self, tenant_id: UUID, statement_id: UUID, *, actor_user_id: UUID
    ) -> BankStatementResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, statement_id)
            if row.status == BankStatementStatus.RECONCILED.value:
                raise ValidationError("Reconciled statements cannot be deleted")
            deleted = await self.repo.soft_delete(tenant_id, statement_id)
            if deleted is None:
                raise ResourceNotFoundError("Bank statement not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="bank_statement",
                entity_id=statement_id,
            )
            return _to_response(deleted)

    async def import_rows(
        self,
        tenant_id: UUID,
        *,
        bank_account_id: UUID,
        period_start: date,
        period_end: date,
        opening_balance: Decimal,
        closing_balance: Decimal,
        filename: str | None,
        content: bytes,
        mapping: Sequence[ImexMappingEntry],
        actor_user_id: UUID,
    ) -> ImportResult:
        bank = await self.bank_accounts.require(tenant_id, bank_account_id)
        rows = mapped_rows(filename=filename, content=content, mapping=mapping)
        lines: list[BankStatementLineInput] = []
        errors: list[ImportRowError] = []
        for index, row in enumerate(rows, start=1):
            line_date = parse_optional_date(row.get("line_date"))
            if line_date is None:
                errors.append(ImportRowError(row_number=index, message="line_date is required"))
                continue
            debit = parse_optional_decimal(row.get("debit")) or _ZERO
            credit = parse_optional_decimal(row.get("credit")) or _ZERO
            if debit == _ZERO and credit == _ZERO:
                errors.append(
                    ImportRowError(row_number=index, message="debit or credit is required")
                )
                continue
            lines.append(
                BankStatementLineInput(
                    line_date=line_date,
                    description=row.get("description") or None,
                    reference=row.get("reference") or None,
                    debit=debit,
                    credit=credit,
                )
            )
        if errors:
            return import_result([], errors)
        payload = BankStatementCreate(
            bank_account_id=bank.id,
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            import_reference=filename,
            lines=lines,
        )
        created = await self.create(tenant_id, payload, actor_user_id=actor_user_id)
        return import_result([created.id], [])

    async def book_entries(
        self, tenant_id: UUID, statement_id: UUID
    ) -> builtins.list[BookEntryCandidate]:
        row = await self._require(tenant_id, statement_id)
        bank = await self.bank_accounts.require(tenant_id, row.bank_account_id)
        matched_ids = await self.repo.matched_journal_line_ids(tenant_id)
        statement = (
            select(JournalEntryLine, JournalEntry)
            .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntryLine.account_id == bank.account_id,
                JournalEntry.status == "POSTED",
                JournalEntry.deleted_at.is_(None),
                JournalEntry.entry_date >= row.period_start,
                JournalEntry.entry_date <= row.period_end,
            )
            .order_by(JournalEntry.entry_date.asc(), JournalEntryLine.line_number.asc())
        )
        results: list[BookEntryCandidate] = []
        for line, header in (await self.session.execute(statement)).all():
            results.append(
                BookEntryCandidate(
                    journal_line_id=line.id,
                    journal_entry_id=header.id,
                    entry_date=header.entry_date,
                    document_number=header.document_number,
                    narration=header.narration,
                    reference=header.reference,
                    debit=line.debit,
                    credit=line.credit,
                    is_matched=line.id in matched_ids,
                )
            )
        return results

    async def suggest_matches(
        self, tenant_id: UUID, statement_id: UUID
    ) -> builtins.list[MatchSuggestion]:
        row = await self._require(tenant_id, statement_id)
        book_entries = await self.book_entries(tenant_id, statement_id)
        unmatched_book = [entry for entry in book_entries if not entry.is_matched]
        suggestions: list[MatchSuggestion] = []
        for stmt_line in row.lines:
            if stmt_line.match_status != BankStatementMatchStatus.UNMATCHED.value:
                continue
            stmt_amount = stmt_line.debit if stmt_line.debit > _ZERO else stmt_line.credit
            for book in unmatched_book:
                book_amount = book.debit if book.debit > _ZERO else book.credit
                score = 0
                reasons: list[str] = []
                if stmt_amount == book_amount:
                    score += 50
                    reasons.append("amount")
                if stmt_line.line_date == book.entry_date:
                    score += 30
                    reasons.append("date")
                if (
                    stmt_line.reference
                    and book.reference
                    and stmt_line.reference.strip().lower() == book.reference.strip().lower()
                ):
                    score += 20
                    reasons.append("reference")
                if score >= 50:
                    suggestions.append(
                        MatchSuggestion(
                            statement_line_id=stmt_line.id,
                            journal_line_id=book.journal_line_id,
                            score=score,
                            reason=", ".join(reasons),
                        )
                    )
        suggestions.sort(key=lambda item: item.score, reverse=True)
        return suggestions

    async def match(
        self,
        tenant_id: UUID,
        statement_id: UUID,
        *,
        statement_line_id: UUID,
        journal_line_id: UUID,
        actor_user_id: UUID,
        expected_version: int,
    ) -> BankStatementResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, statement_id)
            self._assert_version(row, expected_version)
            stmt_line = await self.repo.get_line(tenant_id, statement_line_id)
            if stmt_line is None or stmt_line.bank_statement_id != statement_id:
                raise ResourceNotFoundError("Statement line not found")
            if stmt_line.match_status == BankStatementMatchStatus.MATCHED.value:
                raise ValidationError("Statement line is already matched")
            matched_ids = await self.repo.matched_journal_line_ids(tenant_id)
            if journal_line_id in matched_ids:
                raise ValidationError("Journal line is already matched")
            bank = await self.bank_accounts.require(tenant_id, row.bank_account_id)
            journal_line = (
                await self.session.execute(
                    select(JournalEntryLine).where(
                        JournalEntryLine.tenant_id == tenant_id,
                        JournalEntryLine.id == journal_line_id,
                        JournalEntryLine.account_id == bank.account_id,
                    )
                )
            ).scalar_one_or_none()
            if journal_line is None:
                raise ValidationError("Journal line does not belong to this bank account")
            stmt_line.match_status = BankStatementMatchStatus.MATCHED.value
            stmt_line.matched_journal_line_id = journal_line_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="bank_statement",
                entity_id=statement_id,
                new_values={
                    "match": str(statement_line_id),
                    "journal_line_id": str(journal_line_id),
                },
            )
            return _to_response(await self._require(tenant_id, statement_id))

    async def unmatch(
        self,
        tenant_id: UUID,
        statement_id: UUID,
        *,
        statement_line_id: UUID,
        actor_user_id: UUID,
        expected_version: int,
    ) -> BankStatementResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, statement_id)
            self._assert_version(row, expected_version)
            if row.status == BankStatementStatus.RECONCILED.value:
                row.status = BankStatementStatus.IMPORTED.value
            stmt_line = await self.repo.get_line(tenant_id, statement_line_id)
            if stmt_line is None or stmt_line.bank_statement_id != statement_id:
                raise ResourceNotFoundError("Statement line not found")
            if stmt_line.match_status == BankStatementMatchStatus.MATCHED.value:
                stmt_line.match_status = BankStatementMatchStatus.UNMATCHED.value
                stmt_line.matched_journal_line_id = None
            elif stmt_line.match_status == BankStatementMatchStatus.EXCLUDED.value:
                stmt_line.match_status = BankStatementMatchStatus.UNMATCHED.value
            else:
                raise ValidationError("Only matched or excluded lines can be unmatched")
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="bank_statement",
                entity_id=statement_id,
                new_values={"unmatch": str(statement_line_id)},
            )
            return _to_response(await self._require(tenant_id, statement_id))

    async def exclude_line(
        self,
        tenant_id: UUID,
        statement_id: UUID,
        *,
        statement_line_id: UUID,
        actor_user_id: UUID,
        expected_version: int,
    ) -> BankStatementResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, statement_id)
            self._assert_version(row, expected_version)
            if row.status == BankStatementStatus.RECONCILED.value:
                raise ValidationError("Reconciled statements cannot be changed")
            stmt_line = await self.repo.get_line(tenant_id, statement_line_id)
            if stmt_line is None or stmt_line.bank_statement_id != statement_id:
                raise ResourceNotFoundError("Statement line not found")
            if stmt_line.match_status != BankStatementMatchStatus.UNMATCHED.value:
                raise ValidationError("Only unmatched lines can be excluded")
            stmt_line.match_status = BankStatementMatchStatus.EXCLUDED.value
            stmt_line.matched_journal_line_id = None
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="bank_statement",
                entity_id=statement_id,
                new_values={"exclude": str(statement_line_id)},
            )
            return _to_response(await self._require(tenant_id, statement_id))

    async def reconcile(
        self, tenant_id: UUID, statement_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> BankStatementResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, statement_id)
            self._assert_version(row, expected_version)
            summary = await self.reconciliation_statement(tenant_id, statement_id)
            if summary.unmatched_statement_total != _ZERO:
                raise ValidationError(
                    "All statement lines must be matched or excluded before reconciling"
                )
            row.status = BankStatementStatus.RECONCILED.value
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="bank_statement",
                entity_id=statement_id,
                new_values={"status": BankStatementStatus.RECONCILED.value},
            )
            return _to_response(await self._require(tenant_id, statement_id))

    async def reconciliation_statement(
        self, tenant_id: UUID, statement_id: UUID
    ) -> ReconciliationStatement:
        row = await self._require(tenant_id, statement_id)
        bank = await self.bank_accounts.require(tenant_id, row.bank_account_id)
        book_entries = await self.book_entries(tenant_id, statement_id)
        book_balance = quantize_money(
            sum(
                (entry.debit - entry.credit for entry in book_entries),
                start=_ZERO,
            )
        )
        unmatched_stmt = quantize_money(
            sum(
                (
                    (line.debit - line.credit)
                    for line in row.lines
                    if line.match_status
                    not in {
                        BankStatementMatchStatus.MATCHED.value,
                        BankStatementMatchStatus.EXCLUDED.value,
                    }
                ),
                start=_ZERO,
            )
        )
        unmatched_book = quantize_money(
            sum(
                ((entry.debit - entry.credit) for entry in book_entries if not entry.is_matched),
                start=_ZERO,
            )
        )
        reconciled = quantize_money(row.closing_balance - unmatched_stmt + unmatched_book)
        return ReconciliationStatement(
            bank_account_id=row.bank_account_id,
            period_start=row.period_start,
            period_end=row.period_end,
            book_balance=book_balance,
            statement_balance=row.closing_balance,
            unmatched_statement_total=unmatched_stmt,
            unmatched_book_total=unmatched_book,
            reconciled_balance=reconciled,
            currency_id=bank.currency_id,
        )

    def _replace_lines(self, row: BankStatement, lines: Sequence[BankStatementLineInput]) -> None:
        row.lines.clear()
        for index, line in enumerate(lines, start=1):
            row.lines.append(
                BankStatementLine(
                    tenant_id=row.tenant_id,
                    line_number=index,
                    line_date=line.line_date,
                    description=line.description,
                    reference=line.reference,
                    debit=line.debit,
                    credit=line.credit,
                    match_status=BankStatementMatchStatus.UNMATCHED.value,
                )
            )

    async def _apply_base_balances(
        self, tenant_id: UUID, row: BankStatement, bank: Any
    ) -> None:
        resolved = await self.fx.resolve(
            tenant_id,
            from_currency_id=bank.currency_id,
            on_date=row.period_end,
        )
        rate = resolved.rate
        row.base_opening_balance = quantize_money(row.opening_balance * rate)
        row.base_closing_balance = quantize_money(row.closing_balance * rate)

    async def _require(self, tenant_id: UUID, statement_id: UUID) -> BankStatement:
        row = await self.repo.get(tenant_id, statement_id)
        if row is None:
            raise ResourceNotFoundError("Bank statement not found")
        return row

    def _assert_version(self, row: BankStatement, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                "Bank statement was modified by another user",
                details={"current_version": row.version, "expected_version": expected_version},
            )
