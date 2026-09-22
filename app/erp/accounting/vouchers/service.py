"""Cash/bank vouchers: post, AR/AP allocation, contra transfers."""

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
    PERIOD_OVERRIDE,
    VOUCHER_CANCEL,
    VOUCHER_DELETE,
    VOUCHER_POST,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import document_fx_amounts, quantize_money
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.enums import (
    AccountSubtype,
    AccountSystemRole,
    AuditAction,
    DocumentType,
    InvoiceDocumentStatus,
    JournalType,
    OpenItemType,
    PartyType,
    PaymentAllocationSource,
    PaymentMethod,
    VoucherType,
)
from app.core.exceptions import (
    DocumentStaleError,
    PaymentAccountInvalidError,
    PaymentOverAllocatedError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.accounts.service import (
    AccountResolver,
    AccountService,
    PartyAccountResolver,
)
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.cash_guard import assert_cash_available
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.schemas import JournalLineInput
from app.erp.accounting.open_items.models import PaymentAllocation
from app.erp.accounting.open_items.repository import PaymentAllocationRepository
from app.erp.accounting.open_items.schemas import (
    PaymentAllocationInput,
    PaymentAllocationRecordResponse,
)
from app.erp.accounting.open_items.service import OpenItemsService
from app.erp.accounting.payment_allocations.document_labels import allocation_item_document_number
from app.erp.accounting.payment_allocations.helpers import (
    cash_allocation_types,
    open_item_amount_in_payment_currency,
    open_item_row_for_allocation,
    realized_fx_on_allocation,
    record_note_allocations_on_payment,
    require_single_invoice_target,
    reverse_note_netting_on_payment,
    split_payment_allocations,
    sum_cash_allocations,
)
from app.erp.accounting.service import DocumentSequenceService
from app.erp.accounting.vouchers.models import Voucher
from app.erp.accounting.vouchers.repository import VoucherRepository
from app.erp.accounting.vouchers.schemas import (
    VoucherCreate,
    VoucherLineInput,
    VoucherLineResponse,
    VoucherResponse,
    VoucherUpdate,
)
from app.erp.accounting.vouchers.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService

_ZERO = Decimal("0")
_CONTROL_SUBTYPES = frozenset(
    {AccountSubtype.ACCOUNTS_RECEIVABLE.value, AccountSubtype.ACCOUNTS_PAYABLE.value}
)
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": VOUCHER_POST,
    "cancel": VOUCHER_CANCEL,
    "delete": VOUCHER_DELETE,
}
_VOUCHER_META: dict[VoucherType, tuple[DocumentType, str, str, AccountSubtype | None]] = {
    VoucherType.CASH_RECEIPT: (
        DocumentType.CASH_RECEIPT_VOUCHER,
        "CRV",
        "cash_receipt_voucher",
        AccountSubtype.CASH,
    ),
    VoucherType.CASH_PAYMENT: (
        DocumentType.CASH_PAYMENT_VOUCHER,
        "CPV",
        "cash_payment_voucher",
        AccountSubtype.CASH,
    ),
    VoucherType.BANK_RECEIPT: (
        DocumentType.BANK_RECEIPT_VOUCHER,
        "BRV",
        "bank_receipt_voucher",
        AccountSubtype.BANK,
    ),
    VoucherType.BANK_PAYMENT: (
        DocumentType.BANK_PAYMENT_VOUCHER,
        "BPV",
        "bank_payment_voucher",
        AccountSubtype.BANK,
    ),
    VoucherType.CONTRA: (
        DocumentType.CONTRA_VOUCHER,
        "CON",
        "contra_voucher",
        None,
    ),
}
SOURCE_VOUCHER_ALLOCATION = "voucher_allocation"


class VoucherService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = VoucherRepository(session)
        self.allocations = PaymentAllocationRepository(session)
        self.posting = LedgerPostingService(session, actor_permissions=actor_permissions)
        self.org = OrganizationService(session)
        self.currencies = CurrencyService(session)
        self.fx = ExchangeRateService(session)
        self.sequences = DocumentSequenceService(session)
        self.idempotency = IdempotencyService(session)
        self.audit = AuditWriter(session)
        self.outbox = OutboxService(session)
        self.accounts = AccountService(session)
        self.resolver = AccountResolver(session)
        self.party_accounts = PartyAccountResolver(session)
        self.open_items = OpenItemsService(session)
        self._can_override = has_permission(actor_permissions, PERIOD_OVERRIDE)
        self._period_policy: PeriodLockPolicy | None = None

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        voucher_type: str | None = None,
        party_id: UUID | None = None,
        currency_id: UUID | None = None,
        payment_method: str | None = None,
        voucher_date_from: date | None = None,
        voucher_date_to: date | None = None,
    ) -> tuple[builtins.list[VoucherResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if voucher_type is not None:
            filters["voucher_type"] = voucher_type
        if currency_id is not None:
            filters["currency_id"] = currency_id
        if payment_method is not None:
            filters["payment_method"] = payment_method
        extra: builtins.list[Any] = []
        if party_id is not None:
            extra.append(Voucher.party_id == party_id)
        if voucher_date_from is not None:
            extra.append(Voucher.voucher_date >= voucher_date_from)
        if voucher_date_to is not None:
            extra.append(Voucher.voucher_date <= voucher_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [await self._to_response(tenant_id, row) for row in rows], total

    async def get(self, tenant_id: UUID, voucher_id: UUID) -> VoucherResponse:
        row = await self._require(tenant_id, voucher_id)
        await self._ensure_policy(tenant_id)
        return await self._to_response(tenant_id, row)

    async def create(
        self, tenant_id: UUID, payload: VoucherCreate, *, actor_user_id: UUID
    ) -> VoucherResponse:
        async with transaction(self.session):
            return await self._persist_create(tenant_id, payload, actor_user_id=actor_user_id)

    async def update(
        self,
        tenant_id: UUID,
        voucher_id: UUID,
        payload: VoucherUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> VoucherResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, voucher_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(InvoiceDocumentStatus(row.status))
            old_values = await self._snapshot(tenant_id, row)
            merged = self._merged_update(row, payload)
            values = await self._draft_values(tenant_id, merged)
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(values["voucher_date"], can_override=self._can_override)
            for name, value in values.items():
                setattr(row, name, value)
            if payload.lines is not None:
                await self.repo.replace_lines(
                    tenant_id, voucher_id, await self._line_rows(tenant_id, merged)
                )
            if payload.allocations is not None:
                await self._replace_draft_allocations(tenant_id, row, payload.allocations)
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            loaded = await self._require(tenant_id, voucher_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="voucher",
                entity_id=voucher_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return await self._to_response(tenant_id, loaded)

    async def delete(
        self,
        tenant_id: UUID,
        voucher_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> VoucherResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, voucher_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(InvoiceDocumentStatus(row.status))
            old_values = await self._snapshot(tenant_id, row)
            response = await self._to_response(tenant_id, row)
            await self.allocations.delete_live_for_payment(
                tenant_id, PaymentAllocationSource.VOUCHER.value, voucher_id
            )
            deleted = await self.repo.soft_delete(tenant_id, voucher_id)
            if deleted is None:
                raise ResourceNotFoundError("Voucher not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="voucher",
                entity_id=voucher_id,
                old_values=old_values,
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        voucher_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> VoucherResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return VoucherResponse.model_validate(replay)
            row = await self._require(tenant_id, voucher_id, for_update=True)
            if InvoiceDocumentStatus(row.status) == InvoiceDocumentStatus.POSTED:
                response = await self._to_response(tenant_id, row)
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
                return response
            self._assert_version(row, expected_version)
            target = next_status(InvoiceDocumentStatus(row.status), "post")
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(row.voucher_date, can_override=self._can_override)
            old_values = await self._snapshot(tenant_id, row)
            await self._apply_rate(tenant_id, row)
            await self._apply_draft_note_netting(tenant_id, row, actor_user_id=actor_user_id)
            await self._validate_for_post(tenant_id, row)
            lines = await self._post_journal_lines(tenant_id, row)
            voucher_type = VoucherType(row.voucher_type)
            if voucher_type not in {VoucherType.CONTRA} and not self._is_receipt(voucher_type):
                outflow = quantize_money(sum((line.debit for line in lines), _ZERO))
                settings = await self.org.get_money_movement_settings(tenant_id)
                await assert_cash_available(
                    self.session,
                    tenant_id,
                    account_id=row.payment_account_id,
                    outflow_base=outflow,
                    allow_negative_cash=settings.allow_negative_cash,
                )
            source_type = self._source_type(VoucherType(row.voucher_type))
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=source_type,
                source_id=row.id,
                entry_date=row.voucher_date,
                lines=lines,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                narration=row.narration or f"Voucher {row.document_number}",
                branch_id=row.branch_id,
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
                reference=row.document_number,
            )
            row.journal_entry_id = journal.id
            if VoucherType(row.voucher_type) != VoucherType.CONTRA:
                await self._apply_live_allocations(tenant_id, row, actor_user_id=actor_user_id)
            row.status = target.value
            row.is_posted = True
            row.posted_at = utcnow()
            row.posted_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            loaded = await self._require(tenant_id, voucher_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=ACCOUNTING_MODULE,
                entity_type="voucher",
                entity_id=voucher_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="accounting.voucher.posted",
                aggregate_type="voucher",
                aggregate_id=voucher_id,
                payload={"voucher_id": str(voucher_id)},
                dedupe_key=f"voucher-posted:{voucher_id}",
            )
            response = await self._to_response(tenant_id, loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        voucher_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> VoucherResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return VoucherResponse.model_validate(replay)
            row = await self._require(tenant_id, voucher_id, for_update=True)
            if InvoiceDocumentStatus(row.status) == InvoiceDocumentStatus.CANCELLED:
                response = await self._to_response(tenant_id, row)
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
                return response
            self._assert_version(row, expected_version)
            target = next_status(InvoiceDocumentStatus(row.status), "cancel")
            old_values = await self._snapshot(tenant_id, row)
            row.cancel_reason = reason
            if InvoiceDocumentStatus(row.status) == InvoiceDocumentStatus.POSTED:
                await self._cancel_posted(tenant_id, row, actor_user_id=actor_user_id)
            row.status = target.value
            row.cancelled_at = utcnow()
            row.cancelled_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            loaded = await self._require(tenant_id, voucher_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CANCEL,
                module=ACCOUNTING_MODULE,
                entity_type="voucher",
                entity_id=voucher_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="accounting.voucher.cancelled",
                aggregate_type="voucher",
                aggregate_id=voucher_id,
                payload={"voucher_id": str(voucher_id)},
                dedupe_key=f"voucher-cancelled:{voucher_id}",
            )
            response = await self._to_response(tenant_id, loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def list_allocations(
        self, tenant_id: UUID, voucher_id: UUID
    ) -> builtins.list[PaymentAllocationRecordResponse]:
        await self._require(tenant_id, voucher_id)
        rows = await self.allocations.list_all_for_payment(
            tenant_id, PaymentAllocationSource.VOUCHER.value, voucher_id
        )
        return [await self._allocation_record(tenant_id, row) for row in rows]

    async def _allocation_record(
        self, tenant_id: UUID, row: PaymentAllocation
    ) -> PaymentAllocationRecordResponse:
        item_document_number = await allocation_item_document_number(
            self.session,
            tenant_id,
            OpenItemType(row.item_type),
            row.item_id,
        )
        return PaymentAllocationRecordResponse(
            id=row.id,
            payment_type=row.payment_type,
            payment_id=row.payment_id,
            item_type=OpenItemType(row.item_type),
            item_id=row.item_id,
            item_document_number=item_document_number,
            amount=row.amount,
            journal_entry_id=row.journal_entry_id,
            reversed_at=row.reversed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _persist_create(
        self, tenant_id: UUID, payload: VoucherCreate, *, actor_user_id: UUID
    ) -> VoucherResponse:
        await self._validate_payload(tenant_id, payload)
        values = await self._draft_values(tenant_id, payload)
        policy = await self._ensure_policy(tenant_id)
        policy.assert_open(values["voucher_date"], can_override=self._can_override)
        doc_type, series, _, _ = _VOUCHER_META[payload.voucher_type]
        document_number = await self.sequences.allocate(
            tenant_id,
            document_type=doc_type,
            series=series,
            fiscal_year=await year_for(self.session, tenant_id, cast(date, values["voucher_date"])),
        )
        row = await self.repo.create(
            tenant_id,
            {
                **values,
                "document_number": document_number,
                "status": InvoiceDocumentStatus.DRAFT.value,
                "amount_unapplied": _ZERO,
                "created_by": actor_user_id,
                "updated_by": actor_user_id,
            },
        )
        await self.repo.replace_lines(tenant_id, row.id, await self._line_rows(tenant_id, payload))
        if payload.allocations:
            await self._replace_draft_allocations(tenant_id, row, payload.allocations)
        await self.session.flush()
        loaded = await self._require(tenant_id, row.id)
        await self.audit.write(
            tenant_id=tenant_id,
            user_id=actor_user_id,
            action=AuditAction.CREATE,
            module=ACCOUNTING_MODULE,
            entity_type="voucher",
            entity_id=loaded.id,
            new_values=await self._snapshot(tenant_id, loaded),
        )
        return await self._to_response(tenant_id, loaded)

    async def _draft_values(
        self, tenant_id: UUID, payload: VoucherCreate | VoucherUpdate | Voucher
    ) -> dict[str, object]:
        if isinstance(payload, Voucher):
            return {
                "voucher_type": payload.voucher_type,
                "voucher_date": payload.voucher_date,
                "payment_account_id": payload.payment_account_id,
                "counter_account_id": payload.counter_account_id,
                "total_amount": payload.total_amount,
                "currency_id": payload.currency_id,
                "party_type": payload.party_type,
                "party_id": payload.party_id,
                "payment_method": payload.payment_method,
                "reference": payload.reference,
                "branch_id": payload.branch_id,
                "cost_center_id": payload.cost_center_id,
                "narration": payload.narration,
            }
        voucher_type = payload.voucher_type if isinstance(payload, VoucherCreate) else None
        if voucher_type is None:
            raise ValidationError("voucher_type is required")
        voucher_date = payload.voucher_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        base = await self.currencies.get_base(tenant_id)
        currency_id = payload.currency_id or base.id
        rate = (
            await self.fx.resolve(
                tenant_id,
                from_currency_id=currency_id,
                to_currency_id=base.id,
                on_date=voucher_date,
            )
        ).rate
        foreign_amount, base_amount = document_fx_amounts(payload.total_amount, rate)
        await self._require_payment_account(
            tenant_id,
            payload.payment_account_id,
            voucher_type if isinstance(payload, VoucherCreate) else VoucherType(voucher_type),
        )
        return {
            "voucher_type": voucher_type.value
            if isinstance(voucher_type, VoucherType)
            else voucher_type,
            "voucher_date": voucher_date,
            "payment_account_id": payload.payment_account_id,
            "counter_account_id": payload.counter_account_id,
            "total_amount": quantize_money(payload.total_amount),
            "currency_id": currency_id,
            "base_currency_id": base.id,
            "exchange_rate": rate,
            "foreign_amount": foreign_amount,
            "base_amount": base_amount,
            "party_type": payload.party_type,
            "party_id": payload.party_id,
            "payment_method": (
                payload.payment_method.value
                if isinstance(payload.payment_method, PaymentMethod)
                else payload.payment_method
            ),
            "reference": payload.reference,
            "branch_id": payload.branch_id,
            "cost_center_id": payload.cost_center_id,
            "narration": payload.narration,
        }

    async def _line_rows(
        self, tenant_id: UUID, payload: VoucherCreate | VoucherUpdate | Voucher
    ) -> builtins.list[dict[str, object]]:
        lines = payload.lines if hasattr(payload, "lines") and payload.lines is not None else []
        if isinstance(payload, Voucher):
            lines = [
                VoucherLineInput(
                    account_id=line.account_id,
                    amount=line.amount,
                    party_type=line.party_type,
                    party_id=line.party_id,
                    tax_id=line.tax_id,
                    branch_id=line.branch_id,
                    cost_center_id=line.cost_center_id,
                    description=line.description,
                )
                for line in payload.lines
            ]
        rows: builtins.list[dict[str, object]] = []
        for index, line in enumerate(lines, start=1):
            account = await self.accounts.require_postable(tenant_id, line.account_id)
            if account.account_subtype in _CONTROL_SUBTYPES and (
                line.party_type is None or line.party_id is None
            ):
                raise ValidationError(
                    "AR/AP voucher lines require party_type and party_id",
                    details={"line_number": index, "account_id": str(line.account_id)},
                )
            rows.append(
                {
                    "line_number": index,
                    "account_id": line.account_id,
                    "amount": quantize_money(line.amount),
                    "party_type": line.party_type,
                    "party_id": line.party_id,
                    "tax_id": line.tax_id,
                    "branch_id": line.branch_id,
                    "cost_center_id": line.cost_center_id,
                    "description": line.description,
                }
            )
        return rows

    async def _validate_payload(self, tenant_id: UUID, payload: VoucherCreate) -> None:
        voucher_type = payload.voucher_type
        if voucher_type == VoucherType.CONTRA:
            raise ValidationError("Contra vouchers are not supported")
        if not payload.lines:
            raise ValidationError("Voucher requires at least one counter line")
        line_total = quantize_money(sum((line.amount for line in payload.lines), _ZERO))
        if line_total != quantize_money(payload.total_amount):
            raise ValidationError(
                "Line amounts must equal total_amount",
                details={"line_total": str(line_total), "total_amount": str(payload.total_amount)},
            )
        await self._validate_allocations(tenant_id, payload)

    async def _validate_for_post(self, tenant_id: UUID, row: Voucher) -> None:
        payload = VoucherCreate(
            voucher_type=VoucherType(row.voucher_type),
            voucher_date=row.voucher_date,
            payment_account_id=row.payment_account_id,
            counter_account_id=row.counter_account_id,
            total_amount=row.total_amount,
            currency_id=row.currency_id,
            party_type=row.party_type,
            party_id=row.party_id,
            payment_method=PaymentMethod(row.payment_method),
            reference=row.reference,
            branch_id=row.branch_id,
            cost_center_id=row.cost_center_id,
            narration=row.narration,
            lines=[
                VoucherLineInput(
                    account_id=line.account_id,
                    amount=line.amount,
                    party_type=line.party_type,
                    party_id=line.party_id,
                    tax_id=line.tax_id,
                    branch_id=line.branch_id,
                    cost_center_id=line.cost_center_id,
                    description=line.description,
                )
                for line in row.lines
            ],
            allocations=await self._draft_allocations(tenant_id, row.id),
        )
        await self._validate_payload(tenant_id, payload)

    async def _validate_allocations(
        self, tenant_id: UUID, payload: VoucherCreate | VoucherUpdate
    ) -> None:
        if isinstance(payload, VoucherUpdate) and payload.allocations is None:
            return
        voucher_type = (
            payload.voucher_type
            if isinstance(payload, VoucherCreate)
            else getattr(payload, "voucher_type", None)
        )
        if voucher_type == VoucherType.CONTRA:
            return
        lines = payload.lines or []
        ar_ap_total = _ZERO
        for line in lines:
            account = await self.accounts.require_postable(tenant_id, line.account_id)
            if account.account_subtype in _CONTROL_SUBTYPES:
                ar_ap_total = quantize_money(ar_ap_total + line.amount)
        if ar_ap_total == _ZERO:
            return
        allocations = payload.allocations or []
        if not allocations:
            raise ValidationError("AR/AP voucher lines require allocations")
        receivable = self._is_receipt(
            voucher_type if isinstance(voucher_type, VoucherType) else VoucherType(voucher_type)
        )
        cash, notes = split_payment_allocations(allocations, receivable=receivable)
        allocated = sum_cash_allocations(allocations, receivable=receivable)
        if allocated != ar_ap_total:
            raise ValidationError(
                "Allocations must equal AR/AP line amounts",
                details={"allocated": str(allocated), "ar_ap_total": str(ar_ap_total)},
            )
        if payload.party_id is None:
            raise ValidationError("Party is required when settling AR/AP lines")

    async def _post_journal_lines(
        self, tenant_id: UUID, row: Voucher
    ) -> builtins.list[JournalLineInput]:
        voucher_type = VoucherType(row.voucher_type)
        if voucher_type == VoucherType.CONTRA:
            destination_id = row.counter_account_id
            if destination_id is None:
                raise ValidationError("Contra vouchers require counter_account_id")
            return [
                JournalLineInput(
                    account_id=destination_id,
                    debit=row.total_amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    description=f"Contra {row.document_number}",
                ),
                JournalLineInput(
                    account_id=row.payment_account_id,
                    credit=row.total_amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    description=f"Contra {row.document_number}",
                ),
            ]
        receipt = self._is_receipt(voucher_type)
        advance_role = (
            AccountSystemRole.ADVANCE_FROM_CUSTOMER
            if receipt
            else AccountSystemRole.ADVANCE_TO_SUPPLIER
        )
        advance = await self.resolver.require(tenant_id, advance_role)
        fx_account = await self.resolver.require(tenant_id, AccountSystemRole.FX_GAIN_LOSS)
        lines: builtins.list[JournalLineInput] = []
        if receipt:
            lines.append(
                JournalLineInput(
                    account_id=row.payment_account_id,
                    debit=row.total_amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    description=f"Receipt {row.document_number}",
                )
            )
        else:
            lines.append(
                JournalLineInput(
                    account_id=row.payment_account_id,
                    credit=row.total_amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    description=f"Payment {row.document_number}",
                )
            )
        ar_ap_amount = _ZERO
        party_type = PartyType(row.party_type) if row.party_type else None
        for line in row.lines:
            account = await self.accounts.get(tenant_id, line.account_id)
            if account.account_subtype in _CONTROL_SUBTYPES:
                ar_ap_amount = quantize_money(ar_ap_amount + line.amount)
                if receipt:
                    lines.append(
                        JournalLineInput(
                            account_id=advance.id,
                            credit=line.amount,
                            currency_id=row.currency_id,
                            exchange_rate=row.exchange_rate,
                            party_type=party_type,
                            party_id=row.party_id,
                            description=line.description or f"Voucher {row.document_number}",
                        )
                    )
                else:
                    lines.append(
                        JournalLineInput(
                            account_id=advance.id,
                            debit=line.amount,
                            currency_id=row.currency_id,
                            exchange_rate=row.exchange_rate,
                            party_type=party_type,
                            party_id=row.party_id,
                            description=line.description or f"Voucher {row.document_number}",
                        )
                    )
            elif receipt:
                lines.append(
                    JournalLineInput(
                        account_id=line.account_id,
                        credit=line.amount,
                        currency_id=row.currency_id,
                        exchange_rate=row.exchange_rate,
                        party_type=PartyType(line.party_type) if line.party_type else None,
                        party_id=line.party_id,
                        tax_id=line.tax_id,
                        branch_id=line.branch_id or row.branch_id,
                        cost_center_id=line.cost_center_id or row.cost_center_id,
                        description=line.description,
                    )
                )
            else:
                lines.append(
                    JournalLineInput(
                        account_id=line.account_id,
                        debit=line.amount,
                        currency_id=row.currency_id,
                        exchange_rate=row.exchange_rate,
                        party_type=PartyType(line.party_type) if line.party_type else None,
                        party_id=line.party_id,
                        tax_id=line.tax_id,
                        branch_id=line.branch_id or row.branch_id,
                        cost_center_id=line.cost_center_id or row.cost_center_id,
                        description=line.description,
                    )
                )
        row.amount_unapplied = ar_ap_amount if ar_ap_amount > _ZERO else _ZERO
        self._append_fx(lines, fx_account.id, _ZERO, row)
        return lines

    async def _apply_live_allocations(
        self,
        tenant_id: UUID,
        row: Voucher,
        *,
        actor_user_id: UUID,
    ) -> None:
        live = await self.allocations.list_live_for_payment(
            tenant_id, PaymentAllocationSource.VOUCHER.value, row.id
        )
        if not live:
            return
        receivable = self._is_receipt(VoucherType(row.voucher_type))
        for allocation in live:
            if allocation.journal_entry_id is not None:
                continue
            note_type = OpenItemType.CREDIT_NOTE if receivable else OpenItemType.DEBIT_NOTE
            if allocation.item_type == note_type.value:
                continue
            item = PaymentAllocationInput(
                item_type=OpenItemType(allocation.item_type),
                item_id=allocation.item_id,
                amount=allocation.amount,
            )
            await self._allocate_posted_slice(
                tenant_id,
                row,
                item,
                actor_user_id=actor_user_id,
                existing_allocation=allocation,
                receivable=receivable,
            )
            open_row = await open_item_row_for_allocation(
                self.session,
                tenant_id,
                receivable=receivable,
                party_id=cast(UUID, row.party_id),
                item=item,
            )
            payment_slice = open_item_amount_in_payment_currency(row, open_row, item.amount)
            row.amount_unapplied = quantize_money(row.amount_unapplied - payment_slice)

    async def _allocate_posted_slice(
        self,
        tenant_id: UUID,
        row: Voucher,
        item: PaymentAllocationInput,
        *,
        actor_user_id: UUID,
        existing_allocation: PaymentAllocation | None,
        receivable: bool,
    ) -> None:
        open_row = await open_item_row_for_allocation(
            self.session,
            tenant_id,
            receivable=receivable,
            party_id=cast(UUID, row.party_id),
            item=item,
        )
        if item.amount > open_row.balance:
            raise PaymentOverAllocatedError(
                details={"item_id": str(item.item_id), "balance": str(open_row.balance)}
            )
        lines = await self._application_journal_lines(
            tenant_id,
            row,
            item=item,
            open_row=open_row,
            receivable=receivable,
        )
        allocation = existing_allocation
        if allocation is None:
            allocation = await self.allocations.create(
                tenant_id,
                payment_type=PaymentAllocationSource.VOUCHER.value,
                payment_id=row.id,
                item_type=item.item_type.value,
                item_id=item.item_id,
                amount=item.amount,
            )
        journal = await self.posting.post_for_document(
            tenant_id,
            source_type=SOURCE_VOUCHER_ALLOCATION,
            source_id=allocation.id,
            entry_date=row.voucher_date,
            lines=lines,
            currency_id=row.currency_id,
            exchange_rate=row.exchange_rate,
            narration=f"Apply voucher {row.document_number}",
            branch_id=row.branch_id,
            actor_id=actor_user_id,
            journal_type=JournalType.SYSTEM,
            reference=row.document_number,
        )
        allocation.journal_entry_id = journal.id
        await self._settle_allocations(
            tenant_id,
            row,
            sign=Decimal("1"),
            allocations=[allocation],
            receivable=receivable,
        )

    async def _application_journal_lines(
        self,
        tenant_id: UUID,
        row: Voucher,
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
        if receivable:
            ar = await self.party_accounts.resolve_receivable(tenant_id, cast(UUID, row.party_id))
            item_rate = open_row.exchange_rate or row.exchange_rate
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
        else:
            ap = await self.party_accounts.resolve_payable(tenant_id, cast(UUID, row.party_id))
            item_rate = open_row.exchange_rate or row.exchange_rate
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
        fx_total = realized_fx_on_allocation(row, open_row, item.amount)
        self._append_fx(lines, fx_account.id, fx_total, row)
        return lines

    async def _settle_allocations(
        self,
        tenant_id: UUID,
        row: Voucher,
        *,
        sign: Decimal,
        allocations: Sequence[PaymentAllocation] | None = None,
        receivable: bool,
    ) -> None:
        from app.erp.purchase_invoices.service import PurchaseInvoiceService
        from app.erp.sales_invoices.service import SalesInvoiceService

        sales = SalesInvoiceService(self.session, actor_permissions=self.actor_permissions)
        purchases = PurchaseInvoiceService(self.session, actor_permissions=self.actor_permissions)
        live = list(
            allocations
            if allocations is not None
            else await self.allocations.list_live_for_payment(
                tenant_id, PaymentAllocationSource.VOUCHER.value, row.id
            )
        )
        cash_types = cash_allocation_types(receivable=receivable)
        cash_inputs = [
            PaymentAllocationInput(
                item_type=OpenItemType(item.item_type),
                item_id=item.item_id,
                amount=item.amount,
            )
            for item in live
            if OpenItemType(item.item_type) in cash_types
        ]
        invoice_id_for_notes = require_single_invoice_target(cash_inputs, receivable=receivable)
        note_type = OpenItemType.CREDIT_NOTE if receivable else OpenItemType.DEBIT_NOTE
        for allocation in live:
            item_type = OpenItemType(allocation.item_type)
            amount = quantize_money(allocation.amount * sign)
            if item_type == OpenItemType.SALES_INVOICE:
                await sales.apply_payment(tenant_id, allocation.item_id, amount)
            elif item_type == OpenItemType.PURCHASE_INVOICE:
                await purchases.apply_payment(tenant_id, allocation.item_id, amount)
            elif item_type == note_type and sign < _ZERO:
                if invoice_id_for_notes is None:
                    continue
                await reverse_note_netting_on_payment(
                    self.session,
                    tenant_id,
                    receivable=receivable,
                    note_id=allocation.item_id,
                    invoice_id=invoice_id_for_notes,
                    amount=allocation.amount,
                )

    async def _cancel_posted(self, tenant_id: UUID, row: Voucher, *, actor_user_id: UUID) -> None:
        live = await self.allocations.list_live_for_payment(
            tenant_id, PaymentAllocationSource.VOUCHER.value, row.id
        )
        receivable = self._is_receipt(VoucherType(row.voucher_type))
        for allocation in live:
            if allocation.journal_entry_id is not None:
                await self.posting.reverse(
                    tenant_id,
                    allocation.journal_entry_id,
                    reversal_date=row.voucher_date,
                    reason=row.cancel_reason,
                    actor_id=actor_user_id,
                )
                allocation.reversed_at = utcnow()
        await self._settle_allocations(
            tenant_id,
            row,
            sign=Decimal("-1"),
            allocations=live,
            receivable=receivable,
        )
        if row.journal_entry_id is not None:
            reversal = await self.posting.reverse(
                tenant_id,
                row.journal_entry_id,
                reversal_date=row.voucher_date,
                reason=row.cancel_reason,
                actor_id=actor_user_id,
            )
            row.reversal_journal_entry_id = reversal.id
        row.amount_unapplied = _ZERO
        row.is_posted = False

    async def _replace_draft_allocations(
        self,
        tenant_id: UUID,
        row: Voucher,
        allocations: Sequence[PaymentAllocationInput],
    ) -> None:
        receivable = self._is_receipt(VoucherType(row.voucher_type))
        await self.allocations.delete_live_for_payment(
            tenant_id, PaymentAllocationSource.VOUCHER.value, row.id
        )
        cash, notes = split_payment_allocations(allocations, receivable=receivable)
        for item in cash:
            await self.allocations.create(
                tenant_id,
                payment_type=PaymentAllocationSource.VOUCHER.value,
                payment_id=row.id,
                item_type=item.item_type.value,
                item_id=item.item_id,
                amount=item.amount,
            )
        if notes:
            await record_note_allocations_on_payment(
                self.allocations,
                tenant_id,
                PaymentAllocationSource.VOUCHER.value,
                row.id,
                notes,
                receivable=receivable,
            )

    async def _draft_allocations(
        self, tenant_id: UUID, voucher_id: UUID
    ) -> builtins.list[PaymentAllocationInput]:
        rows = await self.allocations.list_live_for_payment(
            tenant_id, PaymentAllocationSource.VOUCHER.value, voucher_id
        )
        return [
            PaymentAllocationInput(
                item_type=OpenItemType(row.item_type),
                item_id=row.item_id,
                amount=row.amount,
            )
            for row in rows
        ]

    async def _require_payment_account(
        self, tenant_id: UUID, account_id: UUID, voucher_type: VoucherType
    ) -> None:
        account = await self.accounts.require_postable(tenant_id, account_id)
        allowed = frozenset({AccountSubtype.CASH.value, AccountSubtype.BANK.value})
        if account.account_subtype not in allowed:
            raise PaymentAccountInvalidError(
                details={"account_id": str(account_id), "account_subtype": account.account_subtype}
            )
        expected = _VOUCHER_META[voucher_type][3]
        if expected is not None and account.account_subtype != expected.value:
            raise PaymentAccountInvalidError(
                details={
                    "account_id": str(account_id),
                    "expected_subtype": expected.value,
                    "account_subtype": account.account_subtype,
                }
            )

    async def _apply_rate(self, tenant_id: UUID, row: Voucher) -> None:
        base = await self.currencies.get_base(tenant_id)
        row.base_currency_id = base.id
        row.exchange_rate = (
            await self.fx.resolve(
                tenant_id,
                from_currency_id=row.currency_id,
                to_currency_id=base.id,
                on_date=row.voucher_date,
            )
        ).rate
        row.foreign_amount, row.base_amount = document_fx_amounts(
            row.total_amount, row.exchange_rate
        )

    async def has_live_for_sales_invoice(self, tenant_id: UUID, sales_invoice_id: UUID) -> bool:
        return await self.allocations.has_live_for_item(
            tenant_id, OpenItemType.SALES_INVOICE.value, sales_invoice_id
        )

    async def has_live_for_purchase_invoice(
        self, tenant_id: UUID, purchase_invoice_id: UUID
    ) -> bool:
        return await self.allocations.has_live_for_item(
            tenant_id, OpenItemType.PURCHASE_INVOICE.value, purchase_invoice_id
        )

    def _available_actions(
        self, row: Voucher, status: InvoiceDocumentStatus, *, period_locked: bool
    ) -> list[str]:
        actions: list[str] = []
        for action in transition_actions(status):
            if action in {"post", "cancel"} and period_locked:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == InvoiceDocumentStatus.DRAFT and has_permission(
            self.actor_permissions, VOUCHER_DELETE
        ):
            actions.append("delete")
        return actions

    def _date_in_locked_period(self, voucher_date: date) -> bool:
        if self._period_policy is None:
            return False
        return self._period_policy.is_locked(voucher_date, can_override=self._can_override)

    async def _apply_draft_note_netting(
        self,
        tenant_id: UUID,
        row: Voucher,
        *,
        actor_user_id: UUID,
    ) -> None:
        voucher_type = VoucherType(row.voucher_type)
        if voucher_type == VoucherType.CONTRA:
            return
        receivable = self._is_receipt(voucher_type)
        live = await self.allocations.list_live_for_payment(
            tenant_id, PaymentAllocationSource.VOUCHER.value, row.id
        )
        items = [
            PaymentAllocationInput(
                item_type=OpenItemType(item.item_type),
                item_id=item.item_id,
                amount=item.amount,
            )
            for item in live
        ]
        cash, notes = split_payment_allocations(items, receivable=receivable)
        if not notes:
            return
        if row.party_id is None:
            raise ValidationError(
                "Credit notes on a receipt require a customer"
                if receivable
                else "Debit notes on a payment require a supplier"
            )
        if receivable:
            await self._apply_credit_notes_to_invoice(
                tenant_id,
                row.party_id,
                notes,
                invoice_id=require_single_invoice_target(cash, receivable=True),
                actor_user_id=actor_user_id,
            )
        else:
            await self._apply_debit_notes_to_invoice(
                tenant_id,
                row.party_id,
                notes,
                invoice_id=require_single_invoice_target(cash, receivable=False),
                actor_user_id=actor_user_id,
            )

    async def _apply_credit_notes_to_invoice(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        notes: Sequence[PaymentAllocationInput],
        *,
        invoice_id: UUID | None,
        actor_user_id: UUID,
    ) -> None:
        if invoice_id is None:
            raise ValidationError("Credit notes on a receipt require a sales invoice allocation")
        from app.erp.credit_notes.service import CreditNoteService

        notes_svc = CreditNoteService(self.session, actor_permissions=self.actor_permissions)
        for note in notes:
            open_row = await open_item_row_for_allocation(
                self.session,
                tenant_id,
                receivable=True,
                party_id=customer_id,
                item=note,
            )
            if note.amount > open_row.balance:
                raise PaymentOverAllocatedError(
                    details={"item_id": str(note.item_id), "balance": str(open_row.balance)}
                )
            await notes_svc.apply_to_invoice(
                tenant_id,
                note.item_id,
                invoice_id,
                note.amount,
                actor_user_id=actor_user_id,
            )

    async def _apply_debit_notes_to_invoice(
        self,
        tenant_id: UUID,
        supplier_id: UUID,
        notes: Sequence[PaymentAllocationInput],
        *,
        invoice_id: UUID | None,
        actor_user_id: UUID,
    ) -> None:
        if invoice_id is None:
            raise ValidationError("Debit notes on a payment require a purchase invoice allocation")
        from app.erp.debit_notes.service import DebitNoteService

        notes_svc = DebitNoteService(self.session, actor_permissions=self.actor_permissions)
        for note in notes:
            open_row = await open_item_row_for_allocation(
                self.session,
                tenant_id,
                receivable=False,
                party_id=supplier_id,
                item=note,
            )
            if note.amount > open_row.balance:
                raise PaymentOverAllocatedError(
                    details={"item_id": str(note.item_id), "balance": str(open_row.balance)}
                )
            await notes_svc.apply_to_invoice(
                tenant_id,
                note.item_id,
                invoice_id,
                note.amount,
                actor_user_id=actor_user_id,
            )

    async def _to_response(self, tenant_id: UUID, row: Voucher) -> VoucherResponse:
        status = InvoiceDocumentStatus(row.status)
        period_locked = self._date_in_locked_period(row.voucher_date)
        allocations = await self._draft_allocations(tenant_id, row.id)
        return VoucherResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            display_number=row.document_number,
            voucher_type=VoucherType(row.voucher_type),
            status=InvoiceDocumentStatus(row.status),
            version=row.version,
            is_posted=row.is_posted,
            voucher_date=row.voucher_date,
            document_date=row.voucher_date,
            payment_account_id=row.payment_account_id,
            counter_account_id=row.counter_account_id,
            total_amount=row.total_amount,
            amount_unapplied=row.amount_unapplied,
            currency_id=row.currency_id,
            base_currency_id=row.base_currency_id,
            exchange_rate=row.exchange_rate,
            foreign_amount=row.foreign_amount,
            base_amount=row.base_amount,
            party_type=row.party_type,
            party_id=row.party_id,
            payment_method=PaymentMethod(row.payment_method),
            reference=row.reference,
            branch_id=row.branch_id,
            cost_center_id=row.cost_center_id,
            narration=row.narration,
            journal_entry_id=row.journal_entry_id,
            reversal_journal_entry_id=row.reversal_journal_entry_id,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            lines=[VoucherLineResponse.model_validate(line) for line in row.lines],
            allocations=allocations,
            available_actions=self._available_actions(row, status, period_locked=period_locked),
        )

    async def _snapshot(self, tenant_id: UUID, row: Voucher) -> dict[str, object]:
        response = await self._to_response(tenant_id, row)
        return response.model_dump(mode="json")

    async def _require(
        self, tenant_id: UUID, voucher_id: UUID, *, for_update: bool = False
    ) -> Voucher:
        row = await self.repo.get(tenant_id, voucher_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Voucher not found")
        return row

    async def _ensure_policy(self, tenant_id: UUID) -> PeriodLockPolicy:
        if self._period_policy is None:
            _, self._period_policy = await self.org.get_inventory_controls(tenant_id)
        return self._period_policy

    def _assert_version(self, row: Voucher, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={"expected_version": expected_version, "actual_version": row.version}
            )

    def _merged_update(self, row: Voucher, payload: VoucherUpdate) -> VoucherCreate:
        values = payload.model_dump(exclude_unset=True)
        return VoucherCreate(
            voucher_type=VoucherType(row.voucher_type),
            voucher_date=values.get("voucher_date", row.voucher_date),
            payment_account_id=values.get("payment_account_id", row.payment_account_id),
            counter_account_id=values.get("counter_account_id", row.counter_account_id),
            total_amount=values.get("total_amount", row.total_amount),
            currency_id=values.get("currency_id", row.currency_id),
            party_type=values.get("party_type", row.party_type),
            party_id=values.get("party_id", row.party_id),
            payment_method=values.get("payment_method", PaymentMethod(row.payment_method)),
            reference=values.get("reference", row.reference),
            branch_id=values.get("branch_id", row.branch_id),
            cost_center_id=values.get("cost_center_id", row.cost_center_id),
            narration=values.get("narration", row.narration),
            lines=values.get(
                "lines",
                [
                    VoucherLineInput(
                        account_id=line.account_id,
                        amount=line.amount,
                        party_type=line.party_type,
                        party_id=line.party_id,
                        tax_id=line.tax_id,
                        branch_id=line.branch_id,
                        cost_center_id=line.cost_center_id,
                        description=line.description,
                    )
                    for line in row.lines
                ],
            ),
            allocations=values.get("allocations", []),
        )

    def _append_fx(
        self,
        lines: builtins.list[JournalLineInput],
        fx_account_id: UUID,
        fx_amount: Decimal,
        row: Voucher,
    ) -> None:
        if fx_amount == _ZERO:
            return
        if fx_amount > _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=fx_account_id,
                    credit=fx_amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    description="Realized FX",
                )
            )
        else:
            lines.append(
                JournalLineInput(
                    account_id=fx_account_id,
                    debit=abs(fx_amount),
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    description="Realized FX",
                )
            )

    def _is_receipt(self, voucher_type: VoucherType) -> bool:
        return voucher_type in {VoucherType.CASH_RECEIPT, VoucherType.BANK_RECEIPT}

    def _source_type(self, voucher_type: VoucherType) -> str:
        return _VOUCHER_META[voucher_type][2]
