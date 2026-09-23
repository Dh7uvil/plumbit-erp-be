"""Unrealized FX revaluation. Open items stay in document currency; only the GL moves."""

from __future__ import annotations

from builtins import list as _List
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ACCOUNTING_MODULE
from app.common.idempotency.service import IdempotencyService
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money
from app.common.utils.datetime import utcnow
from app.core.enums import (
    AccountSystemRole,
    AuditAction,
    FxExposureKind,
    FxRevaluationStatus,
    JournalType,
    PartyType,
)
from app.core.exceptions import (
    AccountNotPostableError,
    AccountRoleUnmappedError,
    DocumentStaleError,
    ExchangeRateMissingError,
    ResourceNotFoundError,
    ValidationError,
)
from app.db.session import transaction
from app.erp.accounting.accounts.service import AccountResolver, PartyAccountResolver
from app.erp.accounting.bank_accounts.models import BankAccount
from app.erp.accounting.fx_revaluation.models import FxRevaluationLine, FxRevaluationRun
from app.erp.accounting.fx_revaluation.repository import FxRevaluationRepository
from app.erp.accounting.fx_revaluation.schemas import (
    FxExposureLine,
    FxExposureResponse,
    FxRevaluationLineResponse,
    FxRevaluationRunRequest,
    FxRevaluationRunResponse,
)
from app.erp.accounting.ledger.models import JournalEntry, JournalEntryLine
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.schemas import JournalLineInput
from app.erp.accounting.open_items.schemas import OpenExposureItem
from app.erp.accounting.open_items.service import OpenItemsService
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService

_ZERO = Decimal("0")
SOURCE_FX_REVALUATION = "fx_revaluation"


def unrealized_gain(*, book_base: Decimal, revalued_base: Decimal, kind: str) -> Decimal:
    """Asset balances gain when revalued base rises. Liabilities gain when it falls."""

    if kind == FxExposureKind.AP.value:
        return quantize_money(book_base - revalued_base)
    return quantize_money(revalued_base - book_base)


@dataclass
class _Bucket:
    kind: str
    currency_id: UUID
    party_type: str | None
    party_id: UUID | None
    account_id: UUID
    foreign_balance: Decimal
    book_base: Decimal
    closing_rate: Decimal
    revalued_base: Decimal
    gain_base: Decimal

    def line(self, currency_code: str | None = None) -> FxExposureLine:
        return FxExposureLine(
            exposure_kind=FxExposureKind(self.kind),
            currency_id=self.currency_id,
            currency_code=currency_code,
            party_type=self.party_type,
            party_id=self.party_id,
            account_id=self.account_id,
            foreign_balance=self.foreign_balance,
            closing_rate=self.closing_rate,
            book_base=self.book_base,
            revalued_base=self.revalued_base,
            gain_base=self.gain_base,
            source_id=self.account_id,
        )


class FxRevaluationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = FxRevaluationRepository(session)
        self.open_items = OpenItemsService(session)
        self.currencies = CurrencyService(session)
        self.rates = ExchangeRateService(session)
        self.accounts = AccountResolver(session)
        self.parties = PartyAccountResolver(session)
        self.posting = LedgerPostingService(session, actor_permissions=actor_permissions)
        self.idempotency = IdempotencyService(session)
        self.audit = AuditWriter(session)

    async def list(
        self, tenant_id: UUID, *, page: PageParams
    ) -> tuple[_List[FxRevaluationRunResponse], int]:
        rows, total = await self.repo.list(tenant_id, page=page)
        return [await self._response(tenant_id, row, include_lines=False) for row in rows], total

    async def get(self, tenant_id: UUID, run_id: UUID) -> FxRevaluationRunResponse:
        return await self._response(tenant_id, await self._require(tenant_id, run_id))

    async def exposure(self, tenant_id: UUID, *, as_of: date) -> FxExposureResponse:
        base = await self.currencies.get_base(tenant_id)
        buckets, warnings = await self._buckets(tenant_id, as_of=as_of, base_currency_id=base.id)
        codes = await self.currencies.codes_by_ids(
            tenant_id, [bucket.currency_id for bucket in buckets]
        )
        lines = [bucket.line(codes.get(bucket.currency_id)) for bucket in buckets]
        total = quantize_money(sum((line.gain_base for line in lines), _ZERO))
        return FxExposureResponse(
            as_of=as_of,
            currency_code=base.code,
            total_gain_base=total,
            lines=lines,
            warnings=warnings,
        )

    async def run(
        self,
        tenant_id: UUID,
        payload: FxRevaluationRunRequest,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> FxRevaluationRunResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return FxRevaluationRunResponse.model_validate(replay)
            if await self.repo.open_run(tenant_id) is not None:
                raise ValidationError("Reverse the open FX revaluation before running another")
            preview = await self.exposure(tenant_id, as_of=payload.as_of)
            postable = [line for line in preview.lines if line.gain_base != _ZERO]
            if not postable:
                raise ValidationError("No unrealized foreign exchange difference to post")
            base = await self.currencies.get_base(tenant_id)
            try:
                fx_account = await self.accounts.require(tenant_id, AccountSystemRole.FX_GAIN_LOSS)
            except AccountRoleUnmappedError as exc:
                raise ValidationError(
                    "Map the FX gain/loss system account before revaluing"
                ) from exc
            row = await self.repo.create(
                tenant_id,
                {
                    "as_of_date": payload.as_of,
                    "status": FxRevaluationStatus.POSTED.value,
                    "version": 1,
                    "total_gain_base": preview.total_gain_base,
                    "notes": payload.notes,
                    "warnings": preview.warnings,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            for line in postable:
                self.session.add(
                    FxRevaluationLine(
                        tenant_id=tenant_id,
                        run_id=row.id,
                        exposure_kind=line.exposure_kind.value,
                        currency_id=line.currency_id,
                        party_type=line.party_type,
                        party_id=line.party_id,
                        account_id=line.account_id,
                        foreign_balance=line.foreign_balance,
                        closing_rate=line.closing_rate,
                        book_base=line.book_base,
                        revalued_base=line.revalued_base,
                        gain_base=line.gain_base,
                    )
                )
            await self.session.flush()
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_FX_REVALUATION,
                source_id=row.id,
                entry_date=payload.as_of,
                lines=self._journal_lines(postable, fx_account_id=fx_account.id),
                currency_id=base.id,
                exchange_rate=Decimal("1"),
                narration=(
                    payload.notes or f"Unrealized FX revaluation as of {payload.as_of.isoformat()}"
                ),
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
                reference=payload.as_of.isoformat(),
            )
            row.journal_entry_id = journal.id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=ACCOUNTING_MODULE,
                entity_type="fx_revaluation",
                entity_id=row.id,
                new_values={
                    "as_of": payload.as_of.isoformat(),
                    "journal_entry_id": str(journal.id),
                    "total_gain_base": str(preview.total_gain_base),
                },
            )
            response = await self._response(tenant_id, row)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def reverse(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        reversal_date: date,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> FxRevaluationRunResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return FxRevaluationRunResponse.model_validate(replay)
            row = await self._require(tenant_id, run_id, for_update=True)
            self._assert_version(row, expected_version)
            if row.status != FxRevaluationStatus.POSTED.value or row.journal_entry_id is None:
                raise ValidationError("Only a posted revaluation can be reversed")
            if reversal_date <= row.as_of_date:
                raise ValidationError("Reversal date must be after the revaluation date")
            reversal = await self.posting.reverse(
                tenant_id,
                row.journal_entry_id,
                reversal_date=reversal_date,
                reason=f"Reversal of unrealized FX revaluation {row.as_of_date.isoformat()}",
                actor_id=actor_user_id,
            )
            row.status = FxRevaluationStatus.REVERSED.value
            row.reversal_journal_entry_id = reversal.id
            row.reversed_at = utcnow()
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.REVERSE,
                module=ACCOUNTING_MODULE,
                entity_type="fx_revaluation",
                entity_id=row.id,
                new_values={"reversal_journal_entry_id": str(reversal.id)},
            )
            response = await self._response(tenant_id, row)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def _buckets(
        self, tenant_id: UUID, *, as_of: date, base_currency_id: UUID
    ) -> tuple[_List[_Bucket], _List[str]]:
        warnings: _List[str] = []
        grouped: dict[tuple[str, UUID | None, UUID], _BucketAccum] = {}
        items = await self.open_items.list_revaluation_items(tenant_id, as_of=as_of)
        accounts: dict[tuple[str, UUID], UUID] = {}
        for item in items:
            if item.currency_id == base_currency_id:
                continue
            if item.exchange_rate is None:
                warnings.append(f"Skipped {item.document_number}: no stored exchange rate")
                continue
            account_id = await self._control_account(tenant_id, item, accounts, warnings)
            if account_id is None:
                continue
            sign = Decimal("1") if self._increases(item) else Decimal("-1")
            foreign = quantize_money(sign * item.balance)
            book = quantize_money(foreign * item.exchange_rate)
            key = (item.exposure_kind, item.party_id, item.currency_id)
            bucket = grouped.get(key)
            if bucket is None:
                bucket = _BucketAccum(
                    kind=item.exposure_kind,
                    currency_id=item.currency_id,
                    party_type=item.party_type.value,
                    party_id=item.party_id,
                    account_id=account_id,
                )
                grouped[key] = bucket
            bucket.foreign_balance = quantize_money(bucket.foreign_balance + foreign)
            bucket.book_base = quantize_money(bucket.book_base + book)
        for bank in await self._foreign_banks(tenant_id, base_currency_id):
            foreign, book = await self._bank_balances(tenant_id, bank, as_of=as_of)
            if foreign == _ZERO and book == _ZERO:
                continue
            key = (FxExposureKind.BANK.value, bank.id, bank.currency_id)
            grouped[key] = _BucketAccum(
                kind=FxExposureKind.BANK.value,
                currency_id=bank.currency_id,
                party_type=None,
                party_id=None,
                account_id=bank.account_id,
                foreign_balance=foreign,
                book_base=book,
            )
        result: _List[_Bucket] = []
        rates: dict[UUID, Decimal] = {}
        for bucket in grouped.values():
            if bucket.foreign_balance == _ZERO and bucket.book_base == _ZERO:
                continue
            closing = rates.get(bucket.currency_id)
            if closing is None:
                try:
                    resolved = await self.rates.resolve(
                        tenant_id, from_currency_id=bucket.currency_id, on_date=as_of
                    )
                except ExchangeRateMissingError:
                    warnings.append(
                        "Skipped a balance because no closing exchange rate exists "
                        f"for currency {bucket.currency_id} on {as_of.isoformat()}"
                    )
                    continue
                closing = resolved.rate
                rates[bucket.currency_id] = closing
            revalued = quantize_money(bucket.foreign_balance * closing)
            gain = unrealized_gain(
                book_base=bucket.book_base, revalued_base=revalued, kind=bucket.kind
            )
            if gain == _ZERO:
                continue
            result.append(
                _Bucket(
                    kind=bucket.kind,
                    currency_id=bucket.currency_id,
                    party_type=bucket.party_type,
                    party_id=bucket.party_id,
                    account_id=bucket.account_id,
                    foreign_balance=bucket.foreign_balance,
                    book_base=bucket.book_base,
                    closing_rate=closing,
                    revalued_base=revalued,
                    gain_base=gain,
                )
            )
        return result, warnings

    async def _control_account(
        self,
        tenant_id: UUID,
        item: OpenExposureItem,
        cache: dict[tuple[str, UUID], UUID],
        warnings: _List[str],
    ) -> UUID | None:
        key = (item.exposure_kind, item.party_id)
        cached = cache.get(key)
        if cached is not None:
            return cached
        try:
            if item.exposure_kind == FxExposureKind.AR.value:
                account = await self.parties.resolve_receivable(tenant_id, item.party_id)
            else:
                account = await self.parties.resolve_payable(tenant_id, item.party_id)
        except (
            ResourceNotFoundError,
            ValidationError,
            AccountRoleUnmappedError,
            AccountNotPostableError,
        ):
            warnings.append(f"Skipped {item.document_number}: control account is not mapped")
            return None
        cache[key] = account.id
        return account.id

    def _increases(self, item: OpenExposureItem) -> bool:
        if item.exposure_kind == FxExposureKind.AR.value:
            return item.is_debit
        return not item.is_debit

    async def _foreign_banks(self, tenant_id: UUID, base_currency_id: UUID) -> _List[BankAccount]:
        statement = select(BankAccount).where(
            BankAccount.tenant_id == tenant_id,
            BankAccount.deleted_at.is_(None),
            BankAccount.is_active.is_(True),
            BankAccount.currency_id != base_currency_id,
        )
        return list((await self.session.execute(statement)).scalars().all())

    async def _bank_balances(
        self, tenant_id: UUID, bank: BankAccount, *, as_of: date
    ) -> tuple[Decimal, Decimal]:
        statement = (
            select(
                func.coalesce(func.sum(JournalEntryLine.debit - JournalEntryLine.credit), 0),
                func.coalesce(
                    func.sum(JournalEntryLine.debit_base - JournalEntryLine.credit_base), 0
                ),
            )
            .join(JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id)
            .where(
                JournalEntryLine.tenant_id == tenant_id,
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.status == "POSTED",
                JournalEntry.deleted_at.is_(None),
                JournalEntry.entry_date <= as_of,
                JournalEntryLine.account_id == bank.account_id,
                JournalEntryLine.currency_id == bank.currency_id,
            )
        )
        foreign, book = (await self.session.execute(statement)).one()
        return quantize_money(Decimal(foreign)), quantize_money(Decimal(book))

    def _journal_lines(
        self, lines: _List[FxExposureLine], *, fx_account_id: UUID
    ) -> _List[JournalLineInput]:
        journal: _List[JournalLineInput] = []
        for line in lines:
            amount = abs(line.gain_base)
            party_type = PartyType(line.party_type) if line.party_type else None
            control = JournalLineInput(
                account_id=line.account_id,
                debit=amount if line.gain_base > 0 else _ZERO,
                credit=amount if line.gain_base < 0 else _ZERO,
                party_type=party_type,
                party_id=line.party_id,
                description=f"Unrealized FX {line.exposure_kind.value}",
            )
            offset = JournalLineInput(
                account_id=fx_account_id,
                debit=amount if line.gain_base < 0 else _ZERO,
                credit=amount if line.gain_base > 0 else _ZERO,
                description=f"Unrealized FX {line.exposure_kind.value}",
            )
            journal.extend([control, offset])
        return journal

    async def _require(
        self, tenant_id: UUID, run_id: UUID, *, for_update: bool = False
    ) -> FxRevaluationRun:
        row = await self.repo.get(tenant_id, run_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("FX revaluation not found")
        return row

    def _assert_version(self, row: FxRevaluationRun, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={"expected_version": expected_version, "actual_version": row.version}
            )

    async def _response(
        self, tenant_id: UUID, row: FxRevaluationRun, *, include_lines: bool = True
    ) -> FxRevaluationRunResponse:
        await self.session.refresh(row)
        response = FxRevaluationRunResponse.model_validate(row)
        if include_lines:
            stored = await self.repo.lines_for(tenant_id, row.id)
            codes = await self.currencies.codes_by_ids(
                tenant_id, [line.currency_id for line in stored]
            )
            response.lines = []
            for line in stored:
                parsed = FxRevaluationLineResponse.model_validate(line)
                parsed.currency_code = codes.get(line.currency_id)
                parsed.source_id = line.account_id
                response.lines.append(parsed)
        response.available_actions = (
            ["reverse"] if row.status == FxRevaluationStatus.POSTED.value else []
        )
        return response


@dataclass
class _BucketAccum:
    kind: str
    currency_id: UUID
    party_type: str | None
    party_id: UUID | None
    account_id: UUID
    foreign_balance: Decimal = _ZERO
    book_base: Decimal = _ZERO
