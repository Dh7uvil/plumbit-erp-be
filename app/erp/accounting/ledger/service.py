"""Manual journal compose, draft saves, post, cancel, and reverse."""

from __future__ import annotations

import builtins
from datetime import date
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    ACCOUNTING_MODULE,
    JOURNAL_ENTRY_DELETE,
    JOURNAL_ENTRY_POST,
    JOURNAL_ENTRY_REVERSE,
    JOURNAL_ENTRY_UPDATE,
    PERIOD_OVERRIDE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.period_lock import PeriodLockPolicy
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.services.audit import AuditWriter
from app.common.utils.datetime import today_in_timezone
from app.core.enums import AuditAction, DocumentType, JournalEntryStatus, JournalType, PartyType
from app.core.exceptions import (
    DocumentStaleError,
    ResourceNotFoundError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.models import JournalEntry
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.repository import JournalEntryRepository
from app.erp.accounting.ledger.schemas import (
    JournalEntryCreate,
    JournalEntryResponse,
    JournalEntryUpdate,
    JournalLineInput,
    JournalLineResponse,
)
from app.erp.accounting.ledger.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)
from app.erp.accounting.service import DocumentSequenceService
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService

_SERIES = "JV"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": JOURNAL_ENTRY_POST,
    "cancel": JOURNAL_ENTRY_UPDATE,
    "reverse": JOURNAL_ENTRY_REVERSE,
}


class JournalEntryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = JournalEntryRepository(session)
        self.posting = LedgerPostingService(session, actor_permissions=actor_permissions)
        self.org = OrganizationService(session)
        self.currencies = CurrencyService(session)
        self.rates = ExchangeRateService(session)
        self.sequences = DocumentSequenceService(session)
        self.idempotency = IdempotencyService(session)
        self.audit = AuditWriter(session)
        self._can_override = has_permission(actor_permissions, PERIOD_OVERRIDE)
        self._period_policy: PeriodLockPolicy | None = None

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        journal_type: str | None = None,
        account_id: UUID | None = None,
        party_id: UUID | None = None,
        branch_id: UUID | None = None,
        entry_date_from: date | None = None,
        entry_date_to: date | None = None,
    ) -> tuple[builtins.list[JournalEntryResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if journal_type is not None:
            filters["journal_type"] = journal_type
        if branch_id is not None:
            filters["branch_id"] = branch_id
        extra: list[Any] = []
        if account_id is not None:
            extra.append(self.repo.has_account_clause(account_id))
        if party_id is not None:
            extra.append(self.repo.has_party_clause(party_id))
        if entry_date_from is not None:
            extra.append(JournalEntry.entry_date >= entry_date_from)
        if entry_date_to is not None:
            extra.append(JournalEntry.entry_date <= entry_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, journal_id: UUID) -> JournalEntryResponse:
        await self._ensure_policy(tenant_id)
        row = await self._require(tenant_id, journal_id)
        response = self._to_response(row)
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def create(
        self, tenant_id: UUID, payload: JournalEntryCreate, *, actor_user_id: UUID
    ) -> JournalEntryResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            entry_date = cast(date, header["entry_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(entry_date, can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.JOURNAL_ENTRY,
                series=_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, entry_date),
                prefix=_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": JournalEntryStatus.DRAFT.value,
                    "version": 1,
                    "is_posted": False,
                    "journal_type": JournalType.MANUAL.value,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            loaded = await self._require(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ACCOUNTING_MODULE,
                entity_type="journal_entry",
                entity_id=row.id,
                new_values=_journal_snapshot(loaded),
            )
            return self._to_response(loaded)

    async def update(
        self,
        tenant_id: UUID,
        journal_id: UUID,
        payload: JournalEntryUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> JournalEntryResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, journal_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(JournalEntryStatus(row.status))
            old_values = _journal_snapshot(row)
            values = payload.model_dump(exclude_unset=True, exclude={"lines", "version"})
            if payload.lines is not None or values:
                header, line_rows = await self._build_draft(
                    tenant_id,
                    JournalEntryCreate(
                        entry_date=payload.entry_date or row.entry_date,
                        currency_id=payload.currency_id or row.currency_id,
                        exchange_rate=payload.exchange_rate or row.exchange_rate,
                        branch_id=payload.branch_id if "branch_id" in values else row.branch_id,
                        narration=payload.narration if "narration" in values else row.narration,
                        reference=payload.reference if "reference" in values else row.reference,
                        lines=payload.lines
                        or [
                            JournalLineInput(
                                account_id=line.account_id,
                                debit=line.debit,
                                credit=line.credit,
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
                            for line in row.lines
                        ],
                    ),
                )
                policy = await self._ensure_policy(tenant_id)
                policy.assert_open(header["entry_date"], can_override=self._can_override)
                for key, value in header.items():
                    setattr(row, key, value)
                if payload.lines is not None:
                    await self.repo.replace_lines(tenant_id, row.id, line_rows)
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            loaded = await self._require(tenant_id, journal_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="journal_entry",
                entity_id=journal_id,
                old_values=old_values,
                new_values=_journal_snapshot(loaded),
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        journal_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> JournalEntryResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, journal_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(JournalEntryStatus(row.status))
            response = self._to_response(row)
            await self.repo.soft_delete(tenant_id, journal_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="journal_entry",
                entity_id=journal_id,
                old_values=_journal_snapshot(row),
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        journal_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> JournalEntryResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return JournalEntryResponse.model_validate(replay)
            row = await self._require(tenant_id, journal_id, for_update=True)
            if JournalEntryStatus(row.status) == JournalEntryStatus.POSTED:
                await self._ensure_policy(tenant_id)
                response = self._to_response(row)
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
                return response
            self._assert_version(row, expected_version)
            next_status(JournalEntryStatus(row.status), "post")
            posted = await self.posting.post_entry(
                tenant_id, entry=row, actor_id=actor_user_id
            )
            loaded = await self._require(tenant_id, posted.id)
            await self._ensure_policy(tenant_id)
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        journal_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> JournalEntryResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, journal_id, for_update=True)
            self._assert_version(row, expected_version)
            target = next_status(JournalEntryStatus(row.status), "cancel")
            row.status = target.value
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            loaded = await self._require(tenant_id, journal_id)
            await self._ensure_policy(tenant_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CANCEL,
                module=ACCOUNTING_MODULE,
                entity_type="journal_entry",
                entity_id=journal_id,
                new_values={"status": loaded.status, "reason": reason},
            )
            return self._to_response(loaded)

    async def reverse(
        self,
        tenant_id: UUID,
        journal_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reversal_date: date | None,
        reason: str | None,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> JournalEntryResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return JournalEntryResponse.model_validate(replay)
            row = await self._require(tenant_id, journal_id, for_update=True)
            self._assert_version(row, expected_version)
            when = reversal_date or today_in_timezone(await self.org.get_timezone(tenant_id))
            reversal = await self.posting.reverse(
                tenant_id,
                journal_id,
                reversal_date=when,
                reason=reason,
                actor_id=actor_user_id,
            )
            await self._ensure_policy(tenant_id)
            response = self._to_response(reversal)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def _build_draft(
        self, tenant_id: UUID, payload: JournalEntryCreate
    ) -> tuple[dict[str, Any], builtins.list[dict[str, Any]]]:
        entry_date = payload.entry_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        currency_id = payload.currency_id
        if currency_id is None:
            currency_id = (await self.currencies.get_base(tenant_id)).id
        else:
            await self.currencies.require_id(tenant_id, currency_id)
        rate = payload.exchange_rate
        if rate is None:
            resolved = await self.rates.resolve(
                tenant_id, from_currency_id=currency_id, on_date=entry_date
            )
            rate = resolved.rate
        line_rows: builtins.list[dict[str, Any]] = []
        for index, line in enumerate(payload.lines, start=1):
            line_currency = line.currency_id or currency_id
            line_rate = line.exchange_rate if line.exchange_rate is not None else rate
            line_rows.append(
                {
                    "line_number": index,
                    "account_id": line.account_id,
                    "debit": line.debit,
                    "credit": line.credit,
                    "debit_base": line.debit * line_rate,
                    "credit_base": line.credit * line_rate,
                    "currency_id": line_currency,
                    "exchange_rate": line_rate,
                    "party_type": line.party_type.value if line.party_type else None,
                    "party_id": line.party_id,
                    "due_date": line.due_date,
                    "external_reference": line.external_reference,
                    "tax_id": line.tax_id,
                    "branch_id": line.branch_id or payload.branch_id,
                    "description": line.description,
                }
            )
        header: dict[str, Any] = {
            "entry_date": entry_date,
            "currency_id": currency_id,
            "exchange_rate": rate,
            "branch_id": payload.branch_id,
            "narration": payload.narration,
            "reference": payload.reference,
        }
        return header, line_rows

    def _to_response(self, row: JournalEntry) -> JournalEntryResponse:
        status = JournalEntryStatus(row.status)
        date_locked = self._date_in_locked_period(row.entry_date)
        post_blocked = self._post_blocked(row.entry_date)
        return JournalEntryResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            entry_date=row.entry_date,
            status=status,
            version=row.version,
            is_posted=row.is_posted,
            journal_type=JournalType(row.journal_type),
            source_type=row.source_type,
            source_id=row.source_id,
            reversal_of_id=row.reversal_of_id,
            reversed_by_id=row.reversed_by_id,
            currency_id=row.currency_id,
            exchange_rate=row.exchange_rate,
            branch_id=row.branch_id,
            narration=row.narration,
            reference=row.reference,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            total_debit_base=row.total_debit_base,
            total_credit_base=row.total_credit_base,
            available_actions=self._available_actions(status, period_locked=post_blocked),
            period_locked=date_locked,
            related_documents=[],
            lines=[JournalLineResponse.model_validate(line) for line in row.lines],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _available_actions(
        self, status: JournalEntryStatus, *, period_locked: bool
    ) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            if action in {"post", "reverse"} and period_locked:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == JournalEntryStatus.DRAFT and has_permission(
            self.actor_permissions, JOURNAL_ENTRY_DELETE
        ):
            actions.append("delete")
        return actions

    async def _ensure_policy(self, tenant_id: UUID) -> PeriodLockPolicy:
        if self._period_policy is None:
            _, self._period_policy = await self.org.get_inventory_controls(tenant_id)
        return self._period_policy

    def _date_in_locked_period(self, document_date: date) -> bool:
        if self._period_policy is None:
            return False
        return self._period_policy.is_locked(document_date, can_override=False)

    def _post_blocked(self, document_date: date) -> bool:
        if self._period_policy is None:
            return False
        return self._period_policy.is_locked(document_date, can_override=self._can_override)

    def _assert_version(self, row: JournalEntry, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _require(
        self, tenant_id: UUID, journal_id: UUID, *, for_update: bool = False
    ) -> JournalEntry:
        row = await self.repo.get(tenant_id, journal_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Journal entry not found")
        return row

    async def _related_documents(
        self, tenant_id: UUID, row: JournalEntry
    ) -> builtins.list[RelatedDocumentRef]:
        related: builtins.list[RelatedDocumentRef] = []
        if row.source_type and row.source_id is not None:
            related.append(
                RelatedDocumentRef(
                    document_type=row.source_type,
                    document_id=row.source_id,
                    document_number=row.reference or row.document_number,
                    status=row.status,
                    relationship="source",
                    document_date=row.entry_date,
                )
            )
        if row.reversal_of_id is not None:
            original = await self.repo.get(tenant_id, row.reversal_of_id)
            if original is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.JOURNAL_ENTRY.value,
                        document_id=original.id,
                        document_number=original.document_number,
                        status=original.status,
                        relationship="reversal_of",
                        document_date=original.entry_date,
                    )
                )
        if row.reversed_by_id is not None:
            reversal = await self.repo.get(tenant_id, row.reversed_by_id)
            if reversal is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.JOURNAL_ENTRY.value,
                        document_id=reversal.id,
                        document_number=reversal.document_number,
                        status=reversal.status,
                        relationship="reversed_by",
                        document_date=reversal.entry_date,
                    )
                )
        return related


def _journal_snapshot(row: JournalEntry) -> dict[str, object]:
    return {
        "document_number": row.document_number,
        "status": row.status,
        "version": row.version,
        "entry_date": row.entry_date,
        "reference": row.reference,
        "line_count": len(row.lines),
    }
