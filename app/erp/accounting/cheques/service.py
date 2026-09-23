"""Cheque register: issue, deposit, clear, bounce with PDC clearing."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    ACCOUNTING_MODULE,
    CHEQUE_BOUNCE,
    CHEQUE_CANCEL,
    CHEQUE_CLEAR,
    CHEQUE_DELETE,
    CHEQUE_DEPOSIT,
    CHEQUE_ISSUE,
    PERIOD_OVERRIDE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import document_fx_amounts, quantize_money
from app.common.utils.datetime import utcnow
from app.core.enums import (
    AccountSystemRole,
    AuditAction,
    ChequeDirection,
    ChequeStatus,
    DocumentType,
    JournalType,
    OpenItemType,
    PartyType,
    PaymentAllocationSource,
)
from app.core.exceptions import DocumentStaleError, ResourceNotFoundError, ValidationError
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.accounts.service import (
    AccountResolver,
    PartyAccountResolver,
)
from app.erp.accounting.bank_accounts.service import BankAccountService
from app.erp.accounting.cheques.models import Cheque
from app.erp.accounting.cheques.repository import ChequeRepository
from app.erp.accounting.cheques.schemas import (
    ChequeAllocationResponse,
    ChequeCreate,
    ChequeResponse,
    ChequeUpdate,
)
from app.erp.accounting.cheques.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)
from app.erp.accounting.customer_payments.models import CustomerPayment
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.schemas import JournalLineInput
from app.erp.accounting.open_items.models import PaymentAllocation
from app.erp.accounting.open_items.repository import PaymentAllocationRepository
from app.erp.accounting.open_items.schemas import PaymentAllocationInput
from app.erp.accounting.payment_allocations.document_labels import allocation_item_document_number
from app.erp.accounting.payment_allocations.helpers import (
    allocation_base_amount,
    cash_allocation_types,
    open_item_row_for_allocation,
    realized_fx_on_allocation,
    record_note_allocations_on_payment,
    require_single_invoice_target,
    reverse_note_netting_on_payment,
    split_payment_allocations,
    sum_cash_allocations,
)
from app.erp.accounting.service import DocumentSequenceService
from app.erp.accounting.supplier_payments.models import SupplierPayment
from app.erp.accounting.vouchers.models import Voucher
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService

_ZERO = Decimal("0")
SOURCE_CHEQUE_ISSUE = "cheque_issue"
SOURCE_CHEQUE_CLEAR = "cheque_clear"
SOURCE_CHEQUE_ALLOCATION = "cheque_allocation"
_ACTION_PERMISSIONS: dict[str, str] = {
    "issue": CHEQUE_ISSUE,
    "deposit": CHEQUE_DEPOSIT,
    "clear": CHEQUE_CLEAR,
    "bounce": CHEQUE_BOUNCE,
    "cancel": CHEQUE_CANCEL,
    "delete": CHEQUE_DELETE,
}


class ChequeService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = ChequeRepository(session)
        self.bank_accounts = BankAccountService(session)
        self.sequences = DocumentSequenceService(session)
        self.currencies = CurrencyService(session)
        self.rates = ExchangeRateService(session)
        self.posting = LedgerPostingService(session)
        self.resolver = AccountResolver(session)
        self.party_accounts = PartyAccountResolver(session)
        self.allocations = PaymentAllocationRepository(session)
        self.audit = AuditWriter(session)
        self.idempotency = IdempotencyService(session)
        self.outbox = OutboxService(session)
        self.org = OrganizationService(session)
        self._period_policy: PeriodLockPolicy | None = None
        self._can_override = has_permission(actor_permissions, PERIOD_OVERRIDE)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        direction: str | None = None,
        bank_account_id: UUID | None = None,
        party_id: UUID | None = None,
        due_date_from: date | None = None,
        due_date_to: date | None = None,
    ) -> tuple[list[ChequeResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if direction is not None:
            filters["direction"] = direction
        if bank_account_id is not None:
            filters["bank_account_id"] = bank_account_id
        if party_id is not None:
            filters["party_id"] = party_id
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            due_date_from=due_date_from,
            due_date_to=due_date_to,
        )
        return [await self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, cheque_id: UUID) -> ChequeResponse:
        return await self._to_response(await self._require(tenant_id, cheque_id))

    async def create(
        self, tenant_id: UUID, payload: ChequeCreate, *, actor_user_id: UUID
    ) -> ChequeResponse:
        await self._validate_party(payload.party_type, payload.party_id)
        await self._validate_linked_documents(tenant_id, payload)
        bank = await self.bank_accounts.require(tenant_id, payload.bank_account_id)
        currency_id, base_currency_id, rate, foreign_amount, base_amount = await self._resolve_fx(
            tenant_id, payload.currency_id, payload.amount, payload.cheque_date
        )
        cash, notes = split_payment_allocations(
            payload.allocations, receivable=payload.direction == ChequeDirection.INBOUND
        )
        self._validate_allocations(
            payload.amount,
            cash,
            notes,
            receivable=payload.direction == ChequeDirection.INBOUND,
        )
        async with transaction(self.session):
            document_number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.CHEQUE,
                series="CHQ",
                fiscal_year=await year_for(self.session, tenant_id, payload.cheque_date),
            )
            row = await self.repo.create(
                tenant_id,
                {
                    "document_number": document_number,
                    "cheque_number": payload.cheque_number,
                    "direction": payload.direction.value,
                    "status": ChequeStatus.DRAFT.value,
                    "cheque_date": payload.cheque_date,
                    "due_date": payload.due_date,
                    "amount": payload.amount,
                    "amount_unapplied": payload.amount,
                    "currency_id": currency_id,
                    "base_currency_id": base_currency_id,
                    "exchange_rate": rate,
                    "foreign_amount": foreign_amount,
                    "base_amount": base_amount,
                    "party_type": payload.party_type.value if payload.party_type else None,
                    "party_id": payload.party_id,
                    "bank_account_id": bank.id,
                    "customer_payment_id": payload.customer_payment_id,
                    "supplier_payment_id": payload.supplier_payment_id,
                    "voucher_id": payload.voucher_id,
                    "narration": payload.narration,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self._replace_draft_allocations(tenant_id, row, payload.allocations)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ACCOUNTING_MODULE,
                entity_type="cheque",
                entity_id=row.id,
            )
            return await self._to_response(row)

    async def update(
        self,
        tenant_id: UUID,
        cheque_id: UUID,
        payload: ChequeUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ChequeResponse:
        async with transaction(self.session):
            row = await self._require_for_update(tenant_id, cheque_id)
            self._assert_version(row, expected_version)
            assert_editable(ChequeStatus(row.status))
            values = payload.model_dump(exclude={"version", "allocations"}, exclude_unset=True)
            if "party_type" in values and values["party_type"] is not None:
                values["party_type"] = values["party_type"].value
            if "amount" in values and values["amount"] is not None:
                _, _, rate, foreign_amount, base_amount = await self._resolve_fx(
                    tenant_id,
                    values.get("currency_id", row.currency_id),
                    values["amount"],
                    values.get("cheque_date", row.cheque_date),
                )
                values["exchange_rate"] = rate
                values["foreign_amount"] = foreign_amount
                values["base_amount"] = base_amount
            if "bank_account_id" in values and values["bank_account_id"] is not None:
                await self.bank_accounts.require(tenant_id, values["bank_account_id"])
            updated = await self.repo.update(
                tenant_id,
                cheque_id,
                {**values, "version": row.version + 1, "updated_by": actor_user_id},
            )
            if updated is None:
                raise ResourceNotFoundError("Cheque not found")
            if payload.allocations is not None:
                await self._replace_draft_allocations(tenant_id, updated, payload.allocations)
                receivable = ChequeDirection(updated.direction) == ChequeDirection.INBOUND
                updated.amount_unapplied = quantize_money(
                    updated.amount
                    - sum_cash_allocations(payload.allocations, receivable=receivable)
                )
            return await self._to_response(updated)

    async def delete(
        self,
        tenant_id: UUID,
        cheque_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ChequeResponse:
        async with transaction(self.session):
            row = await self._require_for_update(tenant_id, cheque_id)
            self._assert_version(row, expected_version)
            assert_editable(ChequeStatus(row.status))
            await self.allocations.delete_live_for_payment(
                tenant_id, PaymentAllocationSource.CHEQUE.value, cheque_id
            )
            deleted = await self.repo.soft_delete(tenant_id, cheque_id)
            if deleted is None:
                raise ResourceNotFoundError("Cheque not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="cheque",
                entity_id=cheque_id,
            )
            return await self._to_response(deleted)

    async def issue(
        self,
        tenant_id: UUID,
        cheque_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> ChequeResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return ChequeResponse.model_validate(replay)
            row = await self._require_for_update(tenant_id, cheque_id)
            self._assert_version(row, expected_version)
            target = next_status(ChequeStatus(row.status), "issue")
            await self._ensure_period_open(tenant_id, row.cheque_date)
            receivable = ChequeDirection(row.direction) == ChequeDirection.INBOUND
            lines = await self._issue_journal_lines(tenant_id, row, receivable=receivable)
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_CHEQUE_ISSUE,
                source_id=row.id,
                entry_date=row.cheque_date,
                lines=lines,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                narration=row.narration or f"Cheque {row.document_number}",
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
                reference=row.cheque_number,
            )
            row.journal_entry_id = journal.id
            await self._apply_live_allocations(
                tenant_id, row, receivable=receivable, actor_user_id=actor_user_id
            )
            row.status = target.value
            row.is_posted = True
            row.issued_at = utcnow()
            row.issued_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            loaded = await self._require(tenant_id, cheque_id)
            response = await self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=ACCOUNTING_MODULE,
                entity_type="cheque",
                entity_id=cheque_id,
                new_values={"status": target.value},
            )
            return response

    async def deposit(
        self,
        tenant_id: UUID,
        cheque_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ChequeResponse:
        async with transaction(self.session):
            row = await self._require_for_update(tenant_id, cheque_id)
            self._assert_version(row, expected_version)
            if ChequeDirection(row.direction) != ChequeDirection.INBOUND:
                raise ValidationError("Only inbound cheques can be deposited")
            target = next_status(ChequeStatus(row.status), "deposit")
            row.status = target.value
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="cheque",
                entity_id=cheque_id,
                new_values={"status": target.value},
            )
            return await self._to_response(row)

    async def clear(
        self,
        tenant_id: UUID,
        cheque_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> ChequeResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return ChequeResponse.model_validate(replay)
            row = await self._require_for_update(tenant_id, cheque_id)
            self._assert_version(row, expected_version)
            target = next_status(ChequeStatus(row.status), "clear")
            clear_date = row.due_date or row.cheque_date
            await self._ensure_period_open(tenant_id, clear_date)
            receivable = ChequeDirection(row.direction) == ChequeDirection.INBOUND
            lines = await self._clear_journal_lines(tenant_id, row, receivable=receivable)
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_CHEQUE_CLEAR,
                source_id=row.id,
                entry_date=clear_date,
                lines=lines,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                narration=f"Clear cheque {row.document_number}",
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
                reference=row.cheque_number,
            )
            row.clearing_journal_entry_id = journal.id
            row.status = target.value
            row.cleared_at = utcnow()
            row.cleared_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            loaded = await self._require(tenant_id, cheque_id)
            response = await self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=ACCOUNTING_MODULE,
                entity_type="cheque",
                entity_id=cheque_id,
                new_values={"status": target.value},
            )
            return response

    async def bounce(
        self,
        tenant_id: UUID,
        cheque_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> ChequeResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return ChequeResponse.model_validate(replay)
            row = await self._require_for_update(tenant_id, cheque_id)
            self._assert_version(row, expected_version)
            target = next_status(ChequeStatus(row.status), "bounce")
            bounce_date = utcnow().date()
            await self._ensure_period_open(tenant_id, bounce_date)
            receivable = ChequeDirection(row.direction) == ChequeDirection.INBOUND
            row.bounce_reason = reason
            if row.clearing_journal_entry_id is not None:
                clearing_reversal = await self.posting.reverse(
                    tenant_id,
                    row.clearing_journal_entry_id,
                    reversal_date=bounce_date,
                    reason=reason,
                    actor_id=actor_user_id,
                )
                row.clearing_reversal_journal_entry_id = clearing_reversal.id
            await self._reverse_allocations(
                tenant_id,
                row,
                receivable=receivable,
                actor_user_id=actor_user_id,
                reason=reason,
                reversal_date=bounce_date,
            )
            if row.journal_entry_id is not None:
                issue_reversal = await self.posting.reverse(
                    tenant_id,
                    row.journal_entry_id,
                    reversal_date=bounce_date,
                    reason=reason,
                    actor_id=actor_user_id,
                )
                row.reversal_journal_entry_id = issue_reversal.id
            row.status = target.value
            row.is_posted = False
            row.bounced_at = utcnow()
            row.bounced_by = actor_user_id
            row.amount_unapplied = row.amount
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            loaded = await self._require(tenant_id, cheque_id)
            response = await self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.REVERSE,
                module=ACCOUNTING_MODULE,
                entity_type="cheque",
                entity_id=cheque_id,
                new_values={"status": target.value, "reason": reason},
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        cheque_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None,
    ) -> ChequeResponse:
        async with transaction(self.session):
            row = await self._require_for_update(tenant_id, cheque_id)
            self._assert_version(row, expected_version)
            current = ChequeStatus(row.status)
            target = next_status(current, "cancel")
            if current == ChequeStatus.ISSUED:
                receivable = ChequeDirection(row.direction) == ChequeDirection.INBOUND
                cancel_date = utcnow().date()
                await self._reverse_allocations(
                    tenant_id,
                    row,
                    receivable=receivable,
                    actor_user_id=actor_user_id,
                    reason=reason,
                    reversal_date=cancel_date,
                )
                if row.journal_entry_id is not None:
                    reversal = await self.posting.reverse(
                        tenant_id,
                        row.journal_entry_id,
                        reversal_date=cancel_date,
                        reason=reason,
                        actor_id=actor_user_id,
                    )
                    row.reversal_journal_entry_id = reversal.id
                row.is_posted = False
            await self.allocations.delete_live_for_payment(
                tenant_id, PaymentAllocationSource.CHEQUE.value, cheque_id
            )
            row.status = target.value
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="cheque",
                entity_id=cheque_id,
                new_values={"status": target.value, "reason": reason},
            )
            return await self._to_response(row)

    async def _issue_journal_lines(
        self, tenant_id: UUID, row: Cheque, *, receivable: bool
    ) -> builtins.list[JournalLineInput]:
        clearing_role = (
            AccountSystemRole.CHEQUES_RECEIVABLE
            if receivable
            else AccountSystemRole.CHEQUES_PAYABLE
        )
        advance_role = (
            AccountSystemRole.ADVANCE_FROM_CUSTOMER
            if receivable
            else AccountSystemRole.ADVANCE_TO_SUPPLIER
        )
        clearing = await self.resolver.require(tenant_id, clearing_role)
        advance = await self.resolver.require(tenant_id, advance_role)
        party_type = PartyType(row.party_type) if row.party_type else None
        if receivable:
            return [
                JournalLineInput(
                    account_id=clearing.id,
                    debit=row.amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    party_type=party_type,
                    party_id=row.party_id,
                    description=f"Cheque {row.cheque_number}",
                ),
                JournalLineInput(
                    account_id=advance.id,
                    credit=row.amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    party_type=party_type,
                    party_id=row.party_id,
                    description=f"Cheque {row.document_number}",
                ),
            ]
        return [
            JournalLineInput(
                account_id=advance.id,
                debit=row.amount,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                party_type=party_type,
                party_id=row.party_id,
                description=f"Cheque {row.document_number}",
            ),
            JournalLineInput(
                account_id=clearing.id,
                credit=row.amount,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                party_type=party_type,
                party_id=row.party_id,
                description=f"Cheque {row.cheque_number}",
            ),
        ]

    async def _clear_journal_lines(
        self, tenant_id: UUID, row: Cheque, *, receivable: bool
    ) -> builtins.list[JournalLineInput]:
        bank = await self.bank_accounts.require(tenant_id, row.bank_account_id)
        clearing_role = (
            AccountSystemRole.CHEQUES_RECEIVABLE
            if receivable
            else AccountSystemRole.CHEQUES_PAYABLE
        )
        clearing = await self.resolver.require(tenant_id, clearing_role)
        if receivable:
            return [
                JournalLineInput(
                    account_id=bank.account_id,
                    debit=row.amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    description=f"Clear cheque {row.cheque_number}",
                ),
                JournalLineInput(
                    account_id=clearing.id,
                    credit=row.amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    description=f"Clear cheque {row.cheque_number}",
                ),
            ]
        return [
            JournalLineInput(
                account_id=clearing.id,
                debit=row.amount,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                description=f"Clear cheque {row.cheque_number}",
            ),
            JournalLineInput(
                account_id=bank.account_id,
                credit=row.amount,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                description=f"Clear cheque {row.cheque_number}",
            ),
        ]

    async def _apply_live_allocations(
        self,
        tenant_id: UUID,
        row: Cheque,
        *,
        receivable: bool,
        actor_user_id: UUID,
    ) -> None:
        if row.party_id is None:
            return
        live = await self.allocations.list_live_for_payment(
            tenant_id, PaymentAllocationSource.CHEQUE.value, row.id
        )
        for allocation in live:
            item = PaymentAllocationInput(
                item_type=OpenItemType(allocation.item_type),
                item_id=allocation.item_id,
                amount=allocation.amount,
            )
            open_row = await open_item_row_for_allocation(
                self.session,
                tenant_id,
                receivable=receivable,
                party_id=row.party_id,
                item=item,
            )
            lines = await self._application_journal_lines(
                tenant_id, row, item=item, open_row=open_row, receivable=receivable
            )
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_CHEQUE_ALLOCATION,
                source_id=allocation.id,
                entry_date=row.cheque_date,
                lines=lines,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                narration=f"Apply cheque {row.document_number}",
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
                reference=row.document_number,
            )
            if allocation.base_amount is None:
                allocation.base_amount = allocation_base_amount(row, open_row, item.amount)
            allocation.journal_entry_id = journal.id
            await self._settle_allocations(
                tenant_id, row, sign=Decimal("1"), allocations=[allocation], receivable=receivable
            )
        row.amount_unapplied = quantize_money(
            row.amount - sum((item.amount for item in live), _ZERO)
        )

    async def _application_journal_lines(
        self,
        tenant_id: UUID,
        row: Cheque,
        *,
        item: PaymentAllocationInput,
        open_row: Any,
        receivable: bool,
    ) -> builtins.list[JournalLineInput]:
        advance_role = (
            AccountSystemRole.ADVANCE_FROM_CUSTOMER
            if receivable
            else AccountSystemRole.ADVANCE_TO_SUPPLIER
        )
        advance = await self.resolver.require(tenant_id, advance_role)
        fx_account = await self.resolver.require(tenant_id, AccountSystemRole.FX_GAIN_LOSS)
        party_type = PartyType(row.party_type) if row.party_type else None
        item_rate = open_row.exchange_rate or row.exchange_rate
        if receivable:
            ar = await self.party_accounts.resolve_receivable(tenant_id, cast(UUID, row.party_id))
            lines = [
                JournalLineInput(
                    account_id=advance.id,
                    debit=item.amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    party_type=party_type,
                    party_id=row.party_id,
                    description=f"Apply {row.document_number}",
                ),
                JournalLineInput(
                    account_id=ar.id,
                    credit=item.amount,
                    currency_id=open_row.currency_id,
                    exchange_rate=item_rate,
                    party_type=party_type,
                    party_id=row.party_id,
                    description=open_row.document_number,
                ),
            ]
            fx_total = realized_fx_on_allocation(row, open_row, item.amount)
            self._append_fx(lines, fx_account.id, fx_total, row)
            return lines
        ap = await self.party_accounts.resolve_payable(tenant_id, cast(UUID, row.party_id))
        lines = [
            JournalLineInput(
                account_id=ap.id,
                debit=item.amount,
                currency_id=open_row.currency_id,
                exchange_rate=item_rate,
                party_type=party_type,
                party_id=row.party_id,
                description=open_row.document_number,
            ),
            JournalLineInput(
                account_id=advance.id,
                credit=item.amount,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                party_type=party_type,
                party_id=row.party_id,
                description=f"Apply {row.document_number}",
            ),
        ]
        fx_total = realized_fx_on_allocation(row, open_row, item.amount, payable=True)
        self._append_fx(lines, fx_account.id, fx_total, row)
        return lines

    def _append_fx(
        self,
        lines: list[JournalLineInput],
        fx_account_id: UUID,
        fx_total: Decimal,
        row: Cheque,
    ) -> None:
        amount = quantize_money(fx_total)
        if amount == _ZERO:
            return
        if amount > _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=fx_account_id,
                    credit=amount,
                    currency_id=row.base_currency_id,
                    exchange_rate=Decimal("1"),
                    description="Realized FX",
                )
            )
            return
        lines.append(
            JournalLineInput(
                account_id=fx_account_id,
                debit=abs(amount),
                currency_id=row.base_currency_id,
                exchange_rate=Decimal("1"),
                description="Realized FX",
            )
        )

    async def _settle_allocations(
        self,
        tenant_id: UUID,
        row: Cheque,
        *,
        sign: Decimal,
        allocations: Sequence[PaymentAllocation],
        receivable: bool,
    ) -> None:
        from app.erp.purchase_invoices.service import PurchaseInvoiceService
        from app.erp.sales_invoices.service import SalesInvoiceService

        sales = SalesInvoiceService(self.session, actor_permissions=self.actor_permissions)
        purchases = PurchaseInvoiceService(self.session, actor_permissions=self.actor_permissions)
        cash_types = cash_allocation_types(receivable=receivable)
        cash_inputs = [
            PaymentAllocationInput(
                item_type=OpenItemType(item.item_type),
                item_id=item.item_id,
                amount=item.amount,
            )
            for item in allocations
            if OpenItemType(item.item_type) in cash_types
        ]
        invoice_id_for_notes = require_single_invoice_target(cash_inputs, receivable=receivable)
        for allocation in allocations:
            item_type = OpenItemType(allocation.item_type)
            amount = quantize_money(allocation.amount * sign)
            if item_type == OpenItemType.SALES_INVOICE:
                await sales.apply_payment(tenant_id, allocation.item_id, amount)
            elif item_type == OpenItemType.PURCHASE_INVOICE:
                await purchases.apply_payment(tenant_id, allocation.item_id, amount)
            elif item_type == OpenItemType.CREDIT_NOTE and sign < _ZERO and receivable:
                if invoice_id_for_notes is None:
                    continue
                await reverse_note_netting_on_payment(
                    self.session,
                    tenant_id,
                    receivable=True,
                    note_id=allocation.item_id,
                    invoice_id=invoice_id_for_notes,
                    amount=allocation.amount,
                )
            elif item_type == OpenItemType.DEBIT_NOTE and sign < _ZERO and not receivable:
                if invoice_id_for_notes is None:
                    continue
                await reverse_note_netting_on_payment(
                    self.session,
                    tenant_id,
                    receivable=False,
                    note_id=allocation.item_id,
                    invoice_id=invoice_id_for_notes,
                    amount=allocation.amount,
                )

    async def _reverse_allocations(
        self,
        tenant_id: UUID,
        row: Cheque,
        *,
        receivable: bool,
        actor_user_id: UUID,
        reason: str | None,
        reversal_date: date,
    ) -> None:
        live = await self.allocations.list_live_for_payment(
            tenant_id, PaymentAllocationSource.CHEQUE.value, row.id
        )
        if not live:
            return
        await self._settle_allocations(
            tenant_id, row, sign=Decimal("-1"), allocations=live, receivable=receivable
        )
        for allocation in live:
            if allocation.journal_entry_id is not None:
                await self.posting.reverse(
                    tenant_id,
                    allocation.journal_entry_id,
                    reversal_date=reversal_date,
                    reason=reason,
                    actor_id=actor_user_id,
                )
            allocation.reversed_at = utcnow()
        row.amount_unapplied = row.amount

    async def _replace_draft_allocations(
        self,
        tenant_id: UUID,
        row: Cheque,
        allocations: Sequence[PaymentAllocationInput],
    ) -> None:
        receivable = ChequeDirection(row.direction) == ChequeDirection.INBOUND
        await self.allocations.delete_live_for_payment(
            tenant_id, PaymentAllocationSource.CHEQUE.value, row.id
        )
        cash, notes = split_payment_allocations(allocations, receivable=receivable)
        party_id = cast(UUID, row.party_id)
        for item in cash:
            open_row = await open_item_row_for_allocation(
                self.session,
                tenant_id,
                receivable=receivable,
                party_id=party_id,
                item=item,
            )
            await self.allocations.create(
                tenant_id,
                payment_type=PaymentAllocationSource.CHEQUE.value,
                payment_id=row.id,
                item_type=item.item_type.value,
                item_id=item.item_id,
                amount=item.amount,
                base_amount=allocation_base_amount(row, open_row, item.amount),
            )
        if notes:
            await record_note_allocations_on_payment(
                self.allocations,
                tenant_id,
                PaymentAllocationSource.CHEQUE.value,
                row.id,
                notes,
                receivable=receivable,
                session=self.session,
                party_id=party_id,
                payment=row,
            )

    async def _resolve_fx(
        self,
        tenant_id: UUID,
        currency_id: UUID | None,
        amount: Decimal,
        document_date: date,
    ) -> tuple[UUID, UUID, Decimal, Decimal, Decimal]:
        base = await self.currencies.get_base(tenant_id)
        resolved_currency = currency_id or base.id
        await self.currencies.require_id(tenant_id, resolved_currency)
        rate = await self.rates.resolve(
            tenant_id,
            from_currency_id=resolved_currency,
            to_currency_id=base.id,
            on_date=document_date,
        )
        foreign_amount, base_amount = document_fx_amounts(amount, rate.rate)
        return resolved_currency, base.id, rate.rate, foreign_amount, base_amount

    async def _ensure_period_open(self, tenant_id: UUID, document_date: date) -> None:
        if self._period_policy is None:
            _, self._period_policy = await self.org.get_inventory_controls(tenant_id)
        self._period_policy.assert_open(document_date, can_override=self._can_override)

    async def _validate_party(self, party_type: PartyType | None, party_id: UUID | None) -> None:
        if (party_type is None) != (party_id is None):
            raise ValidationError("party_type and party_id must be provided together")

    async def _validate_linked_documents(self, tenant_id: UUID, payload: ChequeCreate) -> None:
        if payload.customer_payment_id and payload.supplier_payment_id:
            raise ValidationError("Link either a customer or supplier payment, not both")
        if payload.customer_payment_id:
            if payload.direction != ChequeDirection.INBOUND:
                raise ValidationError("Customer payments link to inbound cheques only")
            payment = await self.session.get(CustomerPayment, payload.customer_payment_id)
            if payment is None or payment.tenant_id != tenant_id or payment.deleted_at is not None:
                raise ValidationError("Linked customer payment not found")
            if payload.party_id and payment.customer_id != payload.party_id:
                raise ValidationError("Cheque party must match linked customer payment")
        if payload.supplier_payment_id:
            if payload.direction != ChequeDirection.OUTBOUND:
                raise ValidationError("Supplier payments link to outbound cheques only")
            payment = await self.session.get(SupplierPayment, payload.supplier_payment_id)
            if payment is None or payment.tenant_id != tenant_id or payment.deleted_at is not None:
                raise ValidationError("Linked supplier payment not found")
            if payload.party_id and payment.supplier_id != payload.party_id:
                raise ValidationError("Cheque party must match linked supplier payment")
        if payload.voucher_id:
            voucher = await self.session.get(Voucher, payload.voucher_id)
            if voucher is None or voucher.tenant_id != tenant_id or voucher.deleted_at is not None:
                raise ValidationError("Linked voucher not found")

    def _validate_allocations(
        self,
        amount: Decimal,
        cash: Sequence[PaymentAllocationInput],
        notes: Sequence[PaymentAllocationInput],
        *,
        receivable: bool,
    ) -> None:
        total = sum_cash_allocations([*cash, *notes], receivable=receivable)
        if total > amount:
            raise ValidationError("Allocations exceed cheque amount")

    async def _require(self, tenant_id: UUID, cheque_id: UUID) -> Cheque:
        row = await self.repo.get(tenant_id, cheque_id)
        if row is None:
            raise ResourceNotFoundError("Cheque not found")
        return row

    async def _require_for_update(self, tenant_id: UUID, cheque_id: UUID) -> Cheque:
        row = await self.repo.get_for_update(tenant_id, cheque_id)
        if row is None:
            raise ResourceNotFoundError("Cheque not found")
        return row

    def _assert_version(self, row: Cheque, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                "Cheque was modified by another user",
                details={"current_version": row.version, "expected_version": expected_version},
            )

    async def _to_response(self, row: Cheque) -> ChequeResponse:
        actions = transition_actions(ChequeStatus(row.status), direction=row.direction)
        allowed = [
            action
            for action in actions
            if action not in _ACTION_PERMISSIONS
            or has_permission(self.actor_permissions, _ACTION_PERMISSIONS[action])
        ]
        allocation_rows = await self.allocations.list_all_for_payment(
            row.tenant_id, PaymentAllocationSource.CHEQUE.value, row.id
        )
        allocations: list[ChequeAllocationResponse] = []
        for allocation in allocation_rows:
            item_type = OpenItemType(allocation.item_type)
            allocations.append(
                ChequeAllocationResponse(
                    id=allocation.id,
                    item_type=allocation.item_type,
                    item_id=allocation.item_id,
                    item_document_number=await allocation_item_document_number(
                        self.session, row.tenant_id, item_type, allocation.item_id
                    ),
                    amount=allocation.amount,
                    journal_entry_id=allocation.journal_entry_id,
                    reversed_at=allocation.reversed_at,
                    created_at=allocation.created_at,
                )
            )
        response = ChequeResponse.model_validate(row)
        response.available_actions = allowed
        response.allocations = allocations
        return response
