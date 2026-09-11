"""Sole writer for journal_entries / journal_entry_lines."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import PERIOD_OVERRIDE
from app.auth.org_service import OrganizationService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.enums import (
    AccountSubtype,
    AuditAction,
    DocumentType,
    JournalEntryStatus,
    JournalType,
    PartyType,
)
from app.core.exceptions import (
    JournalLineInvalidError,
    JournalUnbalancedError,
    PartyRequiredForControlAccountError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.erp.accounting.accounts.service import AccountService
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
from app.erp.accounting.ledger.repository import JournalEntryRepository
from app.erp.accounting.ledger.schemas import JournalLineInput
from app.erp.accounting.service import DocumentSequenceService
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService

_ZERO = Decimal("0")
_SERIES = "JV"
_CONTROL_SUBTYPES = frozenset(
    {AccountSubtype.ACCOUNTS_RECEIVABLE.value, AccountSubtype.ACCOUNTS_PAYABLE.value}
)
SOURCE_OPENING_BALANCE = "OPENING_BALANCE"
SOURCE_JOURNAL_ENTRY = "journal_entry"


@dataclass(frozen=True, slots=True)
class PreparedLine:
    values: dict[str, object]
    debit_base: Decimal
    credit_base: Decimal


class LedgerPostingService:
    """The only code that writes posted journal rows."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = JournalEntryRepository(session)
        self.accounts = AccountService(session)
        self.currencies = CurrencyService(session)
        self.rates = ExchangeRateService(session)
        self.org = OrganizationService(session)
        self.sequences = DocumentSequenceService(session)
        self.outbox = OutboxService(session)
        self.audit = AuditWriter(session)
        self._can_override = has_permission(actor_permissions, PERIOD_OVERRIDE)

    async def is_posted_for(self, tenant_id: UUID, source_type: str, source_id: UUID) -> bool:
        row = await self.repo.get_posted_for_source(tenant_id, source_type, source_id)
        return row is not None

    async def post_entry(
        self, tenant_id: UUID, *, entry: JournalEntry, actor_id: UUID
    ) -> JournalEntry:
        if JournalEntryStatus(entry.status) != JournalEntryStatus.DRAFT:
            raise ValidationError("Only draft journal entries can be posted")
        _, policy = await self.org.get_inventory_controls(tenant_id)
        policy.assert_open(entry.entry_date, can_override=self._can_override)
        prepared = await self._prepare_lines(
            tenant_id,
            list(entry.lines),
            header_currency_id=entry.currency_id,
            header_rate=entry.exchange_rate,
            entry_date=entry.entry_date,
        )
        await self._replace_prepared(tenant_id, entry, prepared)
        await self._mark_posted(tenant_id, entry, actor_id=actor_id, totals=_totals(prepared))
        await self.outbox.enqueue(
            tenant_id,
            event_type="accounting.journal_entry.posted",
            aggregate_type="journal_entry",
            aggregate_id=entry.id,
            payload={"journal_entry_id": str(entry.id)},
            dedupe_key=f"journal-entry-posted:{entry.id}",
        )
        return entry

    async def post_for_document(
        self,
        tenant_id: UUID,
        *,
        source_type: str,
        source_id: UUID,
        entry_date: date,
        lines: Sequence[JournalLineInput],
        currency_id: UUID,
        exchange_rate: Decimal,
        narration: str | None,
        branch_id: UUID | None,
        actor_id: UUID,
        journal_type: JournalType = JournalType.SYSTEM,
        reference: str | None = None,
    ) -> JournalEntry:
        existing = await self.repo.get_posted_for_source(tenant_id, source_type, source_id)
        if existing is not None:
            return existing
        _, policy = await self.org.get_inventory_controls(tenant_id)
        policy.assert_open(entry_date, can_override=self._can_override)
        prepared = await self._prepare_lines(
            tenant_id,
            lines,
            header_currency_id=currency_id,
            header_rate=exchange_rate,
            entry_date=entry_date,
        )
        number = await self.sequences.allocate(
            tenant_id,
            document_type=DocumentType.JOURNAL_ENTRY,
            series=_SERIES,
            fiscal_year=await year_for(self.session, tenant_id, entry_date),
            prefix=_SERIES,
        )
        debit_base, credit_base = _totals(prepared)
        row = await self.repo.create(
            tenant_id,
            {
                "document_number": number,
                "entry_date": entry_date,
                "status": JournalEntryStatus.DRAFT.value,
                "version": 1,
                "is_posted": False,
                "journal_type": journal_type.value,
                "source_type": source_type,
                "source_id": source_id,
                "currency_id": currency_id,
                "exchange_rate": exchange_rate,
                "branch_id": branch_id,
                "narration": narration,
                "reference": reference,
                "created_by": actor_id,
                "updated_by": actor_id,
            },
        )
        await self._replace_prepared(tenant_id, row, prepared)
        await self._mark_posted(tenant_id, row, actor_id=actor_id, totals=(debit_base, credit_base))
        await self.outbox.enqueue(
            tenant_id,
            event_type="accounting.journal_entry.posted",
            aggregate_type="journal_entry",
            aggregate_id=row.id,
            payload={"journal_entry_id": str(row.id), "source_type": source_type},
            dedupe_key=f"journal-entry-posted:{row.id}",
        )
        loaded = await self.repo.get(tenant_id, row.id)
        if loaded is None:
            raise ResourceNotFoundError("Journal entry not found")
        return loaded

    async def reverse(
        self,
        tenant_id: UUID,
        journal_entry_id: UUID,
        *,
        reversal_date: date,
        reason: str | None,
        actor_id: UUID,
    ) -> JournalEntry:
        original = await self.repo.get(tenant_id, journal_entry_id, for_update=True)
        if original is None:
            raise ResourceNotFoundError("Journal entry not found")
        if JournalEntryStatus(original.status) != JournalEntryStatus.POSTED:
            raise ValidationError("Only posted journal entries can be reversed")
        if original.reversed_by_id is not None:
            existing = await self.repo.get(tenant_id, original.reversed_by_id)
            if existing is not None:
                return existing
        _, policy = await self.org.get_inventory_controls(tenant_id)
        policy.assert_open(reversal_date, can_override=self._can_override)
        mirrored = [
            JournalLineInput(
                account_id=line.account_id,
                debit=line.credit,
                credit=line.debit,
                currency_id=line.currency_id,
                exchange_rate=line.exchange_rate,
                party_type=PartyType(line.party_type) if line.party_type else None,
                party_id=line.party_id,
                due_date=line.due_date,
                external_reference=line.external_reference,
                tax_id=line.tax_id,
                branch_id=line.branch_id,
                description=line.description,
            )
            for line in original.lines
        ]
        reversal = await self.post_for_document(
            tenant_id,
            source_type=SOURCE_JOURNAL_ENTRY,
            source_id=original.id,
            entry_date=reversal_date,
            lines=mirrored,
            currency_id=original.currency_id,
            exchange_rate=original.exchange_rate,
            narration=reason or f"Reversal of {original.document_number}",
            branch_id=original.branch_id,
            actor_id=actor_id,
            journal_type=JournalType.REVERSAL,
            reference=original.document_number,
        )
        reversal.reversal_of_id = original.id
        original.reversed_by_id = reversal.id
        original.version += 1
        original.updated_by = actor_id
        await self.session.flush()
        await self.outbox.enqueue(
            tenant_id,
            event_type="accounting.journal_entry.reversed",
            aggregate_type="journal_entry",
            aggregate_id=original.id,
            payload={
                "journal_entry_id": str(original.id),
                "reversal_id": str(reversal.id),
            },
            dedupe_key=f"journal-entry-reversed:{original.id}",
        )
        await self.audit.write(
            tenant_id=tenant_id,
            user_id=actor_id,
            action=AuditAction.REVERSE,
            module="erp",
            entity_type="journal_entry",
            entity_id=original.id,
            new_values={"reversed_by_id": str(reversal.id)},
        )
        loaded = await self.repo.get(tenant_id, reversal.id)
        if loaded is None:
            raise ResourceNotFoundError("Journal entry not found")
        return loaded

    async def _prepare_lines(
        self,
        tenant_id: UUID,
        lines: Sequence[JournalLineInput | JournalEntryLine],
        *,
        header_currency_id: UUID,
        header_rate: Decimal,
        entry_date: date,
    ) -> list[PreparedLine]:
        if len(lines) < 2:
            raise JournalLineInvalidError(details={"reason": "at_least_two_lines"})
        prepared: list[PreparedLine] = []
        for index, line in enumerate(lines, start=1):
            prepared.append(
                await self._prepare_one(
                    tenant_id,
                    line,
                    line_number=index,
                    header_currency_id=header_currency_id,
                    header_rate=header_rate,
                    entry_date=entry_date,
                )
            )
        debit_base, credit_base = _totals(prepared)
        if debit_base != credit_base:
            raise JournalUnbalancedError(
                details={"total_debit_base": str(debit_base), "total_credit_base": str(credit_base)}
            )
        return prepared

    async def _prepare_one(
        self,
        tenant_id: UUID,
        line: JournalLineInput | JournalEntryLine,
        *,
        line_number: int,
        header_currency_id: UUID,
        header_rate: Decimal,
        entry_date: date,
    ) -> PreparedLine:
        if isinstance(line, JournalEntryLine):
            account_id = line.account_id
            debit = quantize_money(line.debit)
            credit = quantize_money(line.credit)
            currency_id = line.currency_id
            exchange_rate = line.exchange_rate
            party_type = line.party_type
            party_id = line.party_id
            due_date = line.due_date
            external_reference = line.external_reference
            tax_id = line.tax_id
            branch_id = line.branch_id
            description = line.description
        else:
            account_id = line.account_id
            debit = quantize_money(line.debit)
            credit = quantize_money(line.credit)
            currency_id = line.currency_id or header_currency_id
            exchange_rate = line.exchange_rate if line.exchange_rate is not None else header_rate
            party_type = line.party_type.value if line.party_type is not None else None
            party_id = line.party_id
            due_date = line.due_date
            external_reference = line.external_reference
            tax_id = line.tax_id
            branch_id = line.branch_id
            description = line.description
        debit_nonzero = debit != _ZERO
        credit_nonzero = credit != _ZERO
        if debit_nonzero == credit_nonzero:
            raise JournalLineInvalidError(details={"line_number": line_number})
        account = await self.accounts.require_postable(tenant_id, account_id)
        if account.account_subtype in _CONTROL_SUBTYPES and party_id is None:
            raise PartyRequiredForControlAccountError(
                details={"account_id": str(account_id), "line_number": line_number}
            )
        rate = await self._resolve_rate(
            tenant_id,
            currency_id=currency_id,
            provided_rate=exchange_rate,
            header_currency_id=header_currency_id,
            header_rate=header_rate,
            entry_date=entry_date,
        )
        debit_base = quantize_money(debit * rate)
        credit_base = quantize_money(credit * rate)
        return PreparedLine(
            values={
                "line_number": line_number,
                "account_id": account_id,
                "debit": debit,
                "credit": credit,
                "debit_base": debit_base,
                "credit_base": credit_base,
                "currency_id": currency_id,
                "exchange_rate": rate,
                "party_type": party_type,
                "party_id": party_id,
                "due_date": due_date,
                "external_reference": external_reference,
                "tax_id": tax_id,
                "branch_id": branch_id,
                "description": description,
            },
            debit_base=debit_base,
            credit_base=credit_base,
        )

    async def _resolve_rate(
        self,
        tenant_id: UUID,
        *,
        currency_id: UUID,
        provided_rate: Decimal,
        header_currency_id: UUID,
        header_rate: Decimal,
        entry_date: date,
    ) -> Decimal:
        base = await self.currencies.get_base(tenant_id)
        if currency_id == base.id:
            return Decimal("1")
        if currency_id == header_currency_id:
            return provided_rate if provided_rate else header_rate
        resolved = await self.rates.resolve(
            tenant_id, from_currency_id=currency_id, to_currency_id=base.id, on_date=entry_date
        )
        return resolved.rate

    async def _replace_prepared(
        self, tenant_id: UUID, entry: JournalEntry, prepared: Sequence[PreparedLine]
    ) -> None:
        await self.repo.replace_lines(
            tenant_id, entry.id, [item.values for item in prepared]
        )
        await self.session.refresh(entry, attribute_names=["lines"])

    async def _mark_posted(
        self,
        tenant_id: UUID,
        entry: JournalEntry,
        *,
        actor_id: UUID,
        totals: tuple[Decimal, Decimal],
    ) -> None:
        debit_base, credit_base = totals
        entry.status = JournalEntryStatus.POSTED.value
        entry.is_posted = True
        entry.posted_at = utcnow()
        entry.posted_by = actor_id
        entry.total_debit_base = debit_base
        entry.total_credit_base = credit_base
        entry.version += 1
        entry.updated_by = actor_id
        await self.session.flush()
        await self.audit.write(
            tenant_id=tenant_id,
            user_id=actor_id,
            action=AuditAction.POST,
            module="erp",
            entity_type="journal_entry",
            entity_id=entry.id,
            new_values={"status": entry.status, "document_number": entry.document_number},
        )


def _totals(prepared: Sequence[PreparedLine]) -> tuple[Decimal, Decimal]:
    debit = quantize_money(sum((item.debit_base for item in prepared), _ZERO))
    credit = quantize_money(sum((item.credit_base for item in prepared), _ZERO))
    return debit, credit


def assert_period_open(policy: PeriodLockPolicy, entry_date: date, *, can_override: bool) -> None:
    policy.assert_open(entry_date, can_override=can_override)


async def tenant_today(org: OrganizationService, tenant_id: UUID) -> date:
    return today_in_timezone(await org.get_timezone(tenant_id))
