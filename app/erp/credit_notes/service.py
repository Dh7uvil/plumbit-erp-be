"""Credit note compose, post, and void-by-reversal. Does not move stock."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.catalog import (
    CREDIT_NOTE_CANCEL,
    CREDIT_NOTE_DELETE,
    CREDIT_NOTE_POST,
    ERP_MODULE,
    PERIOD_OVERRIDE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money, quantize_quantity
from app.common.utils.datetime import today_in_timezone, utcnow
from app.common.utils.document_totals import (
    compute_header_totals,
    compute_line_amounts,
    place_of_supply_from_address,
    resolve_line_tax_category,
)
from app.core.enums import (
    AccountSystemRole,
    AuditAction,
    CreditNoteReason,
    DiscountType,
    DocumentType,
    InvoiceDocumentStatus,
    JournalType,
    PartyType,
    PlaceOfSupply,
    StockDocumentStatus,
    TaxCategory,
    TaxTreatment,
)
from app.core.exceptions import (
    DocumentStaleError,
    InvoiceCannotVoidError,
    InvoiceQtyExceededError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.crm.customers.service import CustomerService
from app.db.session import transaction
from app.erp.accounting.accounts.service import AccountResolver, AccountService
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.schemas import JournalEntryResponse, JournalLineInput
from app.erp.accounting.ledger.service import JournalEntryService
from app.erp.accounting.service import DocumentSequenceService, TaxService
from app.erp.credit_notes.models import CreditNote, CreditNoteLine
from app.erp.credit_notes.repository import CreditNoteRepository
from app.erp.credit_notes.schemas import (
    CreditNoteCreate,
    CreditNoteCreateFromSalesInvoice,
    CreditNoteCreateFromSalesReturn,
    CreditNoteLineInput,
    CreditNoteLineResponse,
    CreditNoteResponse,
    CreditNoteUpdate,
)
from app.erp.credit_notes.workflow import assert_editable, next_status, transition_actions
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService
from app.erp.sales_invoices.models import SalesInvoice, SalesInvoiceLine
from app.erp.sales_invoices.service import SalesInvoiceService
from app.inventory_management.products.service import ProductService
from app.inventory_management.sales_returns.service import SalesReturnService
from app.inventory_management.units.service import UnitService

_ZERO = Decimal("0")
_SERIES = "CN"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": CREDIT_NOTE_POST,
    "cancel": CREDIT_NOTE_CANCEL,
}
SOURCE_CREDIT_NOTE = "credit_note"


class CreditNoteService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = CreditNoteRepository(session)
        self.org = OrganizationService(session)
        self.customers = CustomerService(session)
        self.products = ProductService(session)
        self.units = UnitService(session)
        self.taxes = TaxService(session)
        self.currencies = CurrencyService(session)
        self.fx = ExchangeRateService(session)
        self.sequences = DocumentSequenceService(session)
        self.accounts = AccountService(session)
        self.resolver = AccountResolver(session)
        self.posting = LedgerPostingService(session, actor_permissions=actor_permissions)
        self.journals = JournalEntryService(session, actor_permissions=actor_permissions)
        self.sales_invoices = SalesInvoiceService(session, actor_permissions=actor_permissions)
        self.sales_returns = SalesReturnService(session, actor_permissions=actor_permissions)
        self.idempotency = IdempotencyService(session)
        self.outbox = OutboxService(session)
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
        customer_id: UUID | None = None,
        sales_invoice_id: UUID | None = None,
        sales_return_id: UUID | None = None,
        currency_id: UUID | None = None,
        credit_note_date_from: date | None = None,
        credit_note_date_to: date | None = None,
    ) -> tuple[list[CreditNoteResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if customer_id is not None:
            filters["customer_id"] = customer_id
        if sales_invoice_id is not None:
            filters["sales_invoice_id"] = sales_invoice_id
        if sales_return_id is not None:
            filters["sales_return_id"] = sales_return_id
        if currency_id is not None:
            filters["currency_id"] = currency_id
        extra: list[Any] = []
        if credit_note_date_from is not None:
            extra.append(CreditNote.credit_note_date >= credit_note_date_from)
        if credit_note_date_to is not None:
            extra.append(CreditNote.credit_note_date <= credit_note_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, credit_note_id: UUID) -> CreditNoteResponse:
        row = await self._require(tenant_id, credit_note_id)
        await self._ensure_policy(tenant_id)
        response = self._to_response(row)
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def create(
        self, tenant_id: UUID, payload: CreditNoteCreate, *, actor_user_id: UUID
    ) -> CreditNoteResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            note_date = cast(date, header["credit_note_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(note_date, can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.CREDIT_NOTE,
                series=_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, note_date),
                prefix=_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": InvoiceDocumentStatus.DRAFT.value,
                    "version": 1,
                    "is_posted": False,
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
                module=ERP_MODULE,
                entity_type="credit_note",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def create_from_sales_invoice(
        self,
        tenant_id: UUID,
        payload: CreditNoteCreateFromSalesInvoice,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> CreditNoteResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return CreditNoteResponse.model_validate(replay)
            invoice = await self.sales_invoices._require(tenant_id, payload.sales_invoice_id)
            if InvoiceDocumentStatus(invoice.status) != InvoiceDocumentStatus.POSTED:
                raise ValidationError(
                    "Credit notes can only be created from a posted sales invoice"
                )
            lines: list[CreditNoteLineInput] = []
            first_credit = all(line.qty_credited == _ZERO for line in invoice.lines)
            for line in invoice.lines:
                outstanding = quantize_quantity(line.quantity - line.qty_credited)
                if outstanding <= _ZERO:
                    continue
                lines.append(
                    CreditNoteLineInput(
                        product_id=line.product_id,
                        description=line.description,
                        quantity=outstanding,
                        unit_id=line.unit_id,
                        rate=line.rate,
                        sales_invoice_line_id=line.id,
                        discount_type=(
                            DiscountType(line.discount_type) if line.discount_type else None
                        ),
                        discount_value=line.discount_value,
                        tax_id=line.tax_id,
                        income_account_id=line.income_account_id,
                    )
                )
            if not lines:
                raise ValidationError("This sales invoice has no remaining quantity to credit")
            create_payload = CreditNoteCreate(
                customer_id=invoice.customer_id,
                sales_invoice_id=invoice.id,
                reason_code=payload.reason_code,
                branch_id=invoice.branch_id,
                credit_note_date=payload.credit_note_date,
                currency_id=invoice.currency_id,
                notes=payload.notes or invoice.notes,
                discount_type=(
                    DiscountType(invoice.discount_type)
                    if first_credit and invoice.discount_type
                    else None
                ),
                discount_value=invoice.discount_value if first_credit else None,
                shipping_amount=invoice.shipping_amount if first_credit else _ZERO,
                adjustment_amount=invoice.adjustment_amount if first_credit else _ZERO,
                round_off_amount=invoice.round_off_amount if first_credit else _ZERO,
                place_of_supply=PlaceOfSupply(invoice.place_of_supply),
                lines=lines,
            )
            response = await self._persist_composed(
                tenant_id, create_payload, actor_user_id=actor_user_id
            )
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def create_from_sales_return(
        self,
        tenant_id: UUID,
        payload: CreditNoteCreateFromSalesReturn,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> CreditNoteResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return CreditNoteResponse.model_validate(replay)
            sales_return = await self.sales_returns._require(tenant_id, payload.sales_return_id)
            if StockDocumentStatus(sales_return.status) != StockDocumentStatus.POSTED:
                raise ValidationError("Credit notes can only be created from a posted sales return")
            invoice = await self._posted_invoice_for_delivery_note(
                tenant_id, sales_return.delivery_note_id
            )
            si_by_dn_line: dict[UUID, SalesInvoiceLine] = {}
            if invoice is not None:
                for line in invoice.lines:
                    if line.delivery_note_line_id is not None:
                        si_by_dn_line[line.delivery_note_line_id] = line
            lines: list[CreditNoteLineInput] = []
            for line in sales_return.lines:
                si_line = si_by_dn_line.get(line.delivery_note_line_id)
                rate = si_line.rate if si_line is not None else (line.rate or None)
                if rate is not None and rate == _ZERO and si_line is None:
                    rate = None
                lines.append(
                    CreditNoteLineInput(
                        product_id=line.product_id or (si_line.product_id if si_line else None),
                        description=si_line.description if si_line is not None else None,
                        quantity=line.quantity,
                        unit_id=line.unit_id or (si_line.unit_id if si_line else None),
                        rate=rate,
                        sales_invoice_line_id=si_line.id if si_line is not None else None,
                        sales_return_line_id=line.id,
                        discount_type=(
                            DiscountType(si_line.discount_type)
                            if si_line is not None and si_line.discount_type
                            else None
                        ),
                        discount_value=si_line.discount_value if si_line is not None else None,
                        tax_id=si_line.tax_id if si_line is not None else None,
                        income_account_id=(
                            si_line.income_account_id if si_line is not None else None
                        ),
                    )
                )
            if not lines:
                raise ValidationError("This sales return has no lines to credit")
            create_payload = CreditNoteCreate(
                customer_id=(
                    invoice.customer_id if invoice is not None else sales_return.customer_id
                ),
                sales_invoice_id=invoice.id if invoice is not None else None,
                sales_return_id=sales_return.id,
                reason_code=payload.reason_code,
                credit_note_date=payload.credit_note_date,
                currency_id=invoice.currency_id if invoice is not None else None,
                notes=payload.notes or sales_return.notes,
                place_of_supply=(
                    PlaceOfSupply(invoice.place_of_supply) if invoice is not None else None
                ),
                lines=lines,
            )
            response = await self._persist_composed(
                tenant_id, create_payload, actor_user_id=actor_user_id
            )
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def update(
        self,
        tenant_id: UUID,
        credit_note_id: UUID,
        payload: CreditNoteUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> CreditNoteResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, credit_note_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(InvoiceDocumentStatus(row.status))
            old_values = await self._snapshot(tenant_id, row)
            create_payload = await self._update_to_create(row, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            note_date = cast(date, header["credit_note_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(note_date, can_override=self._can_override)
            for name, value in header.items():
                setattr(row, name, value)
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, credit_note_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ERP_MODULE,
                entity_type="credit_note",
                entity_id=credit_note_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        credit_note_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> CreditNoteResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, credit_note_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(InvoiceDocumentStatus(row.status))
            old_values = await self._snapshot(tenant_id, row)
            response = self._to_response(row)
            deleted = await self.repo.soft_delete(tenant_id, credit_note_id)
            if deleted is None:
                raise ResourceNotFoundError("Credit note not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="credit_note",
                entity_id=credit_note_id,
                old_values=old_values,
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        credit_note_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> CreditNoteResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return CreditNoteResponse.model_validate(replay)
            row = await self._require(tenant_id, credit_note_id, for_update=True)
            if InvoiceDocumentStatus(row.status) == InvoiceDocumentStatus.POSTED:
                response = self._to_response(row)
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
                return response
            self._assert_version(row, expected_version)
            target = next_status(InvoiceDocumentStatus(row.status), "post")
            if not row.lines:
                raise ValidationError("At least one line is required to post")
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(row.credit_note_date, can_override=self._can_override)
            old_values = await self._snapshot(tenant_id, row)
            await self._assert_qty_headroom(tenant_id, row)
            await self._recompute_posted_totals(tenant_id, row)
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_CREDIT_NOTE,
                source_id=row.id,
                entry_date=row.credit_note_date,
                lines=await self._journal_lines(tenant_id, row),
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                narration=f"Credit note {row.document_number}",
                branch_id=row.branch_id,
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
                reference=row.document_number,
            )
            row.journal_entry_id = journal.id
            await self._apply_invoice_credits(tenant_id, row, sign=Decimal("1"))
            row.amount_applied = quantize_money(row.grand_total)
            row.amount_unapplied = quantize_money(_ZERO)
            row.status = target.value
            row.is_posted = True
            row.posted_at = utcnow()
            row.posted_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, credit_note_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=ERP_MODULE,
                entity_type="credit_note",
                entity_id=credit_note_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="erp.credit_note.posted",
                aggregate_type="credit_note",
                aggregate_id=credit_note_id,
                payload={"credit_note_id": str(credit_note_id)},
                dedupe_key=f"credit-note-posted:{credit_note_id}",
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        credit_note_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        endpoint: str | None = None,
    ) -> CreditNoteResponse:
        async with transaction(self.session):
            if idempotency_key and request_hash and endpoint:
                replay = await self.idempotency.begin(
                    tenant_id, idempotency_key, request_hash, endpoint=endpoint
                )
                if replay is not None:
                    return CreditNoteResponse.model_validate(replay)
            row = await self._require(tenant_id, credit_note_id, for_update=True)
            self._assert_version(row, expected_version)
            current = InvoiceDocumentStatus(row.status)
            old_values = await self._snapshot(tenant_id, row)
            if current == InvoiceDocumentStatus.POSTED:
                await self._cancel_posted(tenant_id, row, actor_user_id=actor_user_id)
            target = next_status(current, "cancel")
            row.status = target.value
            row.cancelled_at = utcnow()
            row.cancelled_by = actor_user_id
            row.cancel_reason = reason
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self._ensure_policy(tenant_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CANCEL,
                module=ERP_MODULE,
                entity_type="credit_note",
                entity_id=credit_note_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            if current == InvoiceDocumentStatus.POSTED:
                await self.outbox.enqueue(
                    tenant_id,
                    event_type="erp.credit_note.cancelled",
                    aggregate_type="credit_note",
                    aggregate_id=credit_note_id,
                    payload={"credit_note_id": str(credit_note_id)},
                    dedupe_key=f"credit-note-cancelled:{credit_note_id}",
                )
            response = self._to_response(row)
            if idempotency_key and request_hash and endpoint:
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
            return response

    async def journal(self, tenant_id: UUID, credit_note_id: UUID) -> JournalEntryResponse:
        row = await self._require(tenant_id, credit_note_id)
        if row.journal_entry_id is None:
            raise ResourceNotFoundError("Credit note has no journal entry")
        return await self.journals.get(tenant_id, row.journal_entry_id)

    async def has_live_for_sales_invoice(self, tenant_id: UUID, sales_invoice_id: UUID) -> bool:
        return await self.repo.has_live_for_sales_invoice(tenant_id, sales_invoice_id)

    async def _persist_composed(
        self, tenant_id: UUID, payload: CreditNoteCreate, *, actor_user_id: UUID
    ) -> CreditNoteResponse:
        header, line_rows = await self._build_draft(tenant_id, payload)
        note_date = cast(date, header["credit_note_date"])
        policy = await self._ensure_policy(tenant_id)
        policy.assert_open(note_date, can_override=self._can_override)
        number = await self.sequences.allocate(
            tenant_id,
            document_type=DocumentType.CREDIT_NOTE,
            series=_SERIES,
            fiscal_year=await year_for(self.session, tenant_id, note_date),
            prefix=_SERIES,
        )
        row = await self.repo.create(
            tenant_id,
            {
                **header,
                "document_number": number,
                "status": InvoiceDocumentStatus.DRAFT.value,
                "version": 1,
                "is_posted": False,
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
            module=ERP_MODULE,
            entity_type="credit_note",
            entity_id=row.id,
            new_values=await self._snapshot(tenant_id, loaded),
        )
        return self._to_response(loaded)

    async def _cancel_posted(
        self, tenant_id: UUID, row: CreditNote, *, actor_user_id: UUID
    ) -> None:
        policy = await self._ensure_policy(tenant_id)
        if policy.is_locked(row.credit_note_date, can_override=self._can_override):
            raise InvoiceCannotVoidError("The period is locked")
        if row.journal_entry_id is not None:
            reversal = await self.posting.reverse(
                tenant_id,
                row.journal_entry_id,
                reversal_date=row.credit_note_date,
                reason=row.cancel_reason,
                actor_id=actor_user_id,
            )
            row.reversal_journal_entry_id = reversal.id
        await self._apply_invoice_credits(tenant_id, row, sign=Decimal("-1"))
        row.amount_applied = quantize_money(_ZERO)
        row.amount_unapplied = quantize_money(_ZERO)
        row.is_posted = False

    async def _assert_qty_headroom(self, tenant_id: UUID, row: CreditNote) -> None:
        if row.sales_invoice_id is None:
            return
        invoice = await self.sales_invoices._require(
            tenant_id, row.sales_invoice_id, for_update=True
        )
        remaining = {
            line.id: quantize_quantity(line.quantity - line.qty_credited) for line in invoice.lines
        }
        for line in row.lines:
            if line.sales_invoice_line_id is None:
                continue
            left = remaining.get(line.sales_invoice_line_id, _ZERO)
            if line.quantity > left:
                raise InvoiceQtyExceededError(
                    details={
                        "sales_invoice_line_id": str(line.sales_invoice_line_id),
                        "quantity": str(line.quantity),
                        "outstanding": str(left),
                    }
                )
            remaining[line.sales_invoice_line_id] = quantize_quantity(left - line.quantity)

    async def _apply_invoice_credits(
        self, tenant_id: UUID, row: CreditNote, *, sign: Decimal
    ) -> None:
        if row.sales_invoice_id is None:
            return
        invoice = await self.sales_invoices._require(
            tenant_id, row.sales_invoice_id, for_update=True
        )
        by_id = {line.id: line for line in invoice.lines}
        for line in row.lines:
            if line.sales_invoice_line_id is None:
                continue
            si_line = by_id.get(line.sales_invoice_line_id)
            if si_line is None:
                raise ValidationError("Sales invoice line not found on the linked invoice")
            si_line.qty_credited = quantize_quantity(si_line.qty_credited + line.quantity * sign)
            if si_line.qty_credited < _ZERO:
                raise ValidationError("Credited quantity cannot be negative")
        await self.sales_invoices.apply_credit(
            tenant_id, invoice.id, quantize_money(row.grand_total * sign)
        )

    async def _recompute_posted_totals(self, tenant_id: UUID, row: CreditNote) -> None:
        payload = await self._row_to_create(row)
        header, line_rows = await self._build_draft(tenant_id, payload)
        for name, value in header.items():
            setattr(row, name, value)
        by_number = {item["line_number"]: item for item in line_rows}
        for line in row.lines:
            values = by_number[line.line_number]
            for name, value in values.items():
                if name == "line_number":
                    continue
                setattr(line, name, value)
        await self.session.flush()

    async def _journal_lines(self, tenant_id: UUID, row: CreditNote) -> list[JournalLineInput]:
        ar = await self.accounts.party_resolver.resolve_receivable(tenant_id, row.customer_id)
        vat = await self.resolver.require(tenant_id, AccountSystemRole.VAT_OUTPUT)
        round_off = await self.resolver.require(tenant_id, AccountSystemRole.ROUND_OFF)
        default_income = await self.resolver.require(tenant_id, AccountSystemRole.SALES_REVENUE)
        invoice_lines: dict[UUID, SalesInvoiceLine] = {}
        if row.sales_invoice_id is not None:
            invoice = await self.sales_invoices._require(tenant_id, row.sales_invoice_id)
            invoice_lines = {line.id: line for line in invoice.lines}
        lines: list[JournalLineInput] = []
        remaining_discount = row.discount_amount
        last_index = len(row.lines) - 1
        for index, line in enumerate(row.lines):
            if index == last_index:
                share = remaining_discount
            else:
                share = self._header_discount_share(row, line)
                remaining_discount = quantize_money(remaining_discount - share)
            net_revenue = quantize_money(line.amount - share)
            income_id = await self._resolve_income_account_id(
                tenant_id, line, invoice_lines=invoice_lines, default_income_id=default_income.id
            )
            line.income_account_id = income_id
            if net_revenue != _ZERO:
                lines.append(
                    JournalLineInput(
                        account_id=income_id,
                        debit=net_revenue if net_revenue > _ZERO else _ZERO,
                        credit=-net_revenue if net_revenue < _ZERO else _ZERO,
                        description=line.description,
                    )
                )
        if row.tax_amount > _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=vat.id,
                    debit=row.tax_amount,
                    description="VAT output",
                )
            )
        if row.grand_total != _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=ar.id,
                    credit=row.grand_total if row.grand_total > _ZERO else _ZERO,
                    debit=-row.grand_total if row.grand_total < _ZERO else _ZERO,
                    party_type=PartyType.CUSTOMER,
                    party_id=row.customer_id,
                    due_date=row.due_date,
                    external_reference=row.document_number,
                    description=f"AR {row.document_number}",
                )
            )
        residual = _round_off_residual(lines, round_off.id)
        if residual is not None:
            lines.append(residual)
        return lines

    async def _resolve_income_account_id(
        self,
        tenant_id: UUID,
        line: CreditNoteLine,
        *,
        invoice_lines: dict[UUID, SalesInvoiceLine],
        default_income_id: UUID,
    ) -> UUID:
        if line.income_account_id is not None:
            return line.income_account_id
        if line.sales_invoice_line_id is not None:
            si_line = invoice_lines.get(line.sales_invoice_line_id)
            if si_line is not None and si_line.income_account_id is not None:
                return si_line.income_account_id
        if line.product_id is not None:
            income = await self.accounts.resolve_income_account(tenant_id, line.product_id)
            return income.id
        return default_income_id

    def _header_discount_share(self, row: CreditNote, line: CreditNoteLine) -> Decimal:
        if row.subtotal <= _ZERO or row.discount_amount == _ZERO:
            return quantize_money(_ZERO)
        return quantize_money(row.discount_amount * line.amount / row.subtotal)

    async def _posted_invoice_for_delivery_note(
        self, tenant_id: UUID, delivery_note_id: UUID
    ) -> SalesInvoice | None:
        statement = (
            select(SalesInvoice)
            .where(
                SalesInvoice.tenant_id == tenant_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                SalesInvoice.id.in_(
                    select(SalesInvoiceLine.sales_invoice_id).where(
                        SalesInvoiceLine.tenant_id == tenant_id,
                        SalesInvoiceLine.delivery_note_id == delivery_note_id,
                    )
                ),
            )
            .options(selectinload(SalesInvoice.lines))
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def _build_draft(
        self, tenant_id: UUID, payload: CreditNoteCreate
    ) -> tuple[dict[str, object], builtins.list[dict[str, object]]]:
        customer = await self.customers.get(tenant_id, payload.customer_id)
        if payload.branch_id is not None:
            await self.org.require_branch(tenant_id, payload.branch_id)
        invoice: SalesInvoice | None = None
        if payload.sales_invoice_id is not None:
            invoice = await self.sales_invoices._require(tenant_id, payload.sales_invoice_id)
            if InvoiceDocumentStatus(invoice.status) != InvoiceDocumentStatus.POSTED:
                raise ValidationError("Linked sales invoice must be posted")
            if invoice.customer_id != customer.id:
                raise ValidationError("Credit note customer must match the sales invoice")
        if payload.sales_return_id is not None:
            sales_return = await self.sales_returns._require(tenant_id, payload.sales_return_id)
            if StockDocumentStatus(sales_return.status) != StockDocumentStatus.POSTED:
                raise ValidationError("Linked sales return must be posted")
            if sales_return.customer_id != customer.id:
                raise ValidationError("Credit note customer must match the sales return")

        currency_id = payload.currency_id or (
            invoice.currency_id if invoice else customer.currency_id
        )
        await self.currencies.require_id(tenant_id, currency_id)
        base = await self.currencies.get_base(tenant_id)
        note_date = payload.credit_note_date or await self._today(tenant_id)
        resolved = await self.fx.resolve(
            tenant_id,
            from_currency_id=currency_id,
            to_currency_id=base.id,
            on_date=note_date,
        )
        place = payload.place_of_supply or (
            PlaceOfSupply(invoice.place_of_supply)
            if invoice is not None
            else place_of_supply_from_address(customer.shipping_address)
        )
        tax_treatment = (
            TaxTreatment(invoice.tax_treatment)
            if invoice is not None
            else TaxTreatment(customer.tax_treatment)
        )
        is_export = (
            invoice.is_export
            if invoice is not None
            else (
                tax_treatment in {TaxTreatment.EXPORT, TaxTreatment.GCC}
                or place == PlaceOfSupply.OUTSIDE_UAE
            )
        )
        line_rows, line_nets, line_taxes = await self._build_lines(
            tenant_id,
            payload.lines,
            tax_treatment=tax_treatment,
            place_of_supply=place,
        )
        round_off = quantize_money(payload.round_off_amount)
        subtotal, doc_discount, tax_total, grand = compute_header_totals(
            line_nets=line_nets,
            line_taxes=line_taxes,
            discount_type=payload.discount_type,
            discount_value=payload.discount_value,
            shipping_amount=quantize_money(payload.shipping_amount),
            adjustment_amount=quantize_money(payload.adjustment_amount),
        )
        grand = quantize_money(grand + round_off)
        header: dict[str, object] = {
            "credit_note_date": note_date,
            "customer_id": customer.id,
            "sales_invoice_id": payload.sales_invoice_id,
            "sales_return_id": payload.sales_return_id,
            "reason_code": payload.reason_code.value,
            "branch_id": payload.branch_id or (invoice.branch_id if invoice is not None else None),
            "due_date": invoice.due_date if invoice is not None else None,
            "tax_treatment": tax_treatment.value,
            "place_of_supply": place.value,
            "is_export": is_export,
            "currency_id": currency_id,
            "base_currency_id": base.id,
            "exchange_rate": resolved.rate,
            "discount_type": payload.discount_type.value if payload.discount_type else None,
            "discount_value": payload.discount_value,
            "discount_amount": doc_discount,
            "shipping_amount": quantize_money(payload.shipping_amount),
            "adjustment_amount": quantize_money(payload.adjustment_amount),
            "round_off_amount": round_off,
            "subtotal": subtotal,
            "tax_amount": tax_total,
            "grand_total": grand,
            "foreign_amount": grand,
            "base_amount": quantize_money(grand * resolved.rate),
            "notes": payload.notes,
            "amount_applied": _ZERO,
            "amount_unapplied": _ZERO,
        }
        return header, line_rows

    async def _build_lines(
        self,
        tenant_id: UUID,
        lines: Sequence[CreditNoteLineInput],
        *,
        tax_treatment: TaxTreatment,
        place_of_supply: PlaceOfSupply,
    ) -> tuple[builtins.list[dict[str, object]], builtins.list[Decimal], builtins.list[Decimal]]:
        built: builtins.list[dict[str, object]] = []
        nets: builtins.list[Decimal] = []
        taxes: builtins.list[Decimal] = []
        default_tax = await self.taxes.get_default(tenant_id)
        for index, line in enumerate(lines, start=1):
            product = None
            if line.product_id is not None:
                product = await self.products.get(tenant_id, line.product_id)
            description = (
                line.description
                or (product.sales_description if product else None)
                or (product.name if product else None)
            )
            if not description:
                raise ValidationError("Line description is required")
            unit_id = line.unit_id or (product.unit_id if product else None)
            if unit_id is not None:
                await self.units.require_id(tenant_id, unit_id)
            if line.rate is not None:
                rate = quantize_money(line.rate)
            elif product is not None:
                rate = quantize_money(product.selling_rate)
            else:
                raise ValidationError("Custom lines require a rate")
            if line.income_account_id is not None:
                await self.accounts.require_postable(tenant_id, line.income_account_id)
            item_category: TaxCategory | None = None
            chosen_tax = default_tax
            source_tax_id = line.tax_id or (product.tax_id if product else None)
            if source_tax_id is not None:
                chosen_tax = await self.taxes.get(tenant_id, source_tax_id)
                item_category = chosen_tax.tax_category
            resolved_category = resolve_line_tax_category(
                item_category=item_category,
                tax_treatment=tax_treatment,
                place_of_supply=place_of_supply,
            )
            if resolved_category != (item_category or TaxCategory.STANDARD):
                chosen_tax = await self.taxes.get_by_category(tenant_id, resolved_category)
            qty, line_discount, tax_amount, net = compute_line_amounts(
                quantity=line.quantity,
                rate=rate,
                discount_type=line.discount_type,
                discount_value=line.discount_value,
                tax_rate=chosen_tax.rate,
            )
            built.append(
                {
                    "line_number": index,
                    "product_id": product.id if product else None,
                    "description": description,
                    "quantity": qty,
                    "unit_id": unit_id,
                    "rate": rate,
                    "sales_invoice_line_id": line.sales_invoice_line_id,
                    "sales_return_line_id": line.sales_return_line_id,
                    "discount_type": line.discount_type.value if line.discount_type else None,
                    "discount_value": line.discount_value,
                    "discount_amount": line_discount,
                    "tax_id": chosen_tax.id,
                    "tax_rate": chosen_tax.rate,
                    "tax_amount": tax_amount,
                    "amount": net,
                    "income_account_id": line.income_account_id,
                }
            )
            nets.append(net)
            taxes.append(tax_amount)
        return built, nets, taxes

    async def _update_to_create(
        self, existing: CreditNote, payload: CreditNoteUpdate
    ) -> CreditNoteCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                CreditNoteLineInput(
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    sales_invoice_line_id=line.sales_invoice_line_id,
                    sales_return_line_id=line.sales_return_line_id,
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    tax_id=line.tax_id,
                    income_account_id=line.income_account_id,
                )
                for line in existing.lines
            ]
        return CreditNoteCreate(
            customer_id=existing.customer_id,
            sales_invoice_id=values.get("sales_invoice_id", existing.sales_invoice_id),
            sales_return_id=values.get("sales_return_id", existing.sales_return_id),
            reason_code=(
                values["reason_code"]
                if "reason_code" in values
                else CreditNoteReason(existing.reason_code)
            ),
            branch_id=values.get("branch_id", existing.branch_id),
            credit_note_date=values.get("credit_note_date", existing.credit_note_date),
            currency_id=values.get("currency_id", existing.currency_id),
            notes=values.get("notes", existing.notes),
            discount_type=(
                values["discount_type"]
                if "discount_type" in values
                else (DiscountType(existing.discount_type) if existing.discount_type else None)
            ),
            discount_value=values.get("discount_value", existing.discount_value),
            shipping_amount=values.get("shipping_amount", existing.shipping_amount),
            adjustment_amount=values.get("adjustment_amount", existing.adjustment_amount),
            round_off_amount=values.get("round_off_amount", existing.round_off_amount),
            place_of_supply=(
                values["place_of_supply"]
                if "place_of_supply" in values
                else PlaceOfSupply(existing.place_of_supply)
            ),
            lines=lines,
        )

    async def _row_to_create(self, row: CreditNote) -> CreditNoteCreate:
        return CreditNoteCreate(
            customer_id=row.customer_id,
            sales_invoice_id=row.sales_invoice_id,
            sales_return_id=row.sales_return_id,
            reason_code=CreditNoteReason(row.reason_code),
            branch_id=row.branch_id,
            credit_note_date=row.credit_note_date,
            currency_id=row.currency_id,
            notes=row.notes,
            discount_type=DiscountType(row.discount_type) if row.discount_type else None,
            discount_value=row.discount_value,
            shipping_amount=row.shipping_amount,
            adjustment_amount=row.adjustment_amount,
            round_off_amount=row.round_off_amount,
            place_of_supply=PlaceOfSupply(row.place_of_supply),
            lines=[
                CreditNoteLineInput(
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    sales_invoice_line_id=line.sales_invoice_line_id,
                    sales_return_line_id=line.sales_return_line_id,
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    tax_id=line.tax_id,
                    income_account_id=line.income_account_id,
                )
                for line in row.lines
            ],
        )

    def _available_actions(
        self, row: CreditNote, status: InvoiceDocumentStatus, *, period_locked: bool
    ) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            if (
                action in {"post", "cancel"}
                and period_locked
                and status != InvoiceDocumentStatus.DRAFT
            ):
                continue
            if action == "post" and period_locked:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == InvoiceDocumentStatus.DRAFT and has_permission(
            self.actor_permissions, CREDIT_NOTE_DELETE
        ):
            actions.append("delete")
        return actions

    def _to_response(self, row: CreditNote) -> CreditNoteResponse:
        status = InvoiceDocumentStatus(row.status)
        period_locked = self._date_in_locked_period(row.credit_note_date)
        return CreditNoteResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            display_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=row.is_posted,
            credit_note_date=row.credit_note_date,
            document_date=row.credit_note_date,
            customer_id=row.customer_id,
            sales_invoice_id=row.sales_invoice_id,
            sales_return_id=row.sales_return_id,
            reason_code=CreditNoteReason(row.reason_code),
            branch_id=row.branch_id,
            due_date=row.due_date,
            tax_treatment=TaxTreatment(row.tax_treatment),
            place_of_supply=PlaceOfSupply(row.place_of_supply),
            is_export=row.is_export,
            currency_id=row.currency_id,
            base_currency_id=row.base_currency_id,
            exchange_rate=row.exchange_rate,
            discount_type=DiscountType(row.discount_type) if row.discount_type else None,
            discount_value=row.discount_value,
            discount_amount=row.discount_amount,
            shipping_amount=row.shipping_amount,
            adjustment_amount=row.adjustment_amount,
            round_off_amount=row.round_off_amount,
            subtotal=row.subtotal,
            tax_amount=row.tax_amount,
            grand_total=row.grand_total,
            foreign_amount=row.foreign_amount,
            base_amount=row.base_amount,
            notes=row.notes,
            amount_applied=row.amount_applied,
            amount_unapplied=row.amount_unapplied,
            journal_entry_id=row.journal_entry_id,
            reversal_journal_entry_id=row.reversal_journal_entry_id,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            available_actions=self._available_actions(row, status, period_locked=period_locked),
            lines=[
                CreditNoteLineResponse(
                    id=line.id,
                    line_number=line.line_number,
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    sales_invoice_line_id=line.sales_invoice_line_id,
                    sales_return_line_id=line.sales_return_line_id,
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    discount_amount=line.discount_amount,
                    tax_id=line.tax_id,
                    tax_rate=line.tax_rate,
                    tax_amount=line.tax_amount,
                    amount=line.amount,
                    income_account_id=line.income_account_id,
                )
                for line in row.lines
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _related_documents(
        self, tenant_id: UUID, row: CreditNote
    ) -> builtins.list[RelatedDocumentRef]:
        from app.erp.sales_invoices.repository import SalesInvoiceRepository
        from app.inventory_management.sales_returns.repository import SalesReturnRepository

        related: builtins.list[RelatedDocumentRef] = []
        if row.sales_invoice_id is not None:
            invoice = await SalesInvoiceRepository(self.session).get(
                tenant_id, row.sales_invoice_id
            )
            if invoice is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.SALES_INVOICE.value,
                        document_id=invoice.id,
                        document_number=invoice.document_number,
                        status=invoice.status,
                        relationship="source",
                        document_date=invoice.invoice_date,
                    )
                )
        if row.sales_return_id is not None:
            ret = await SalesReturnRepository(self.session).get(tenant_id, row.sales_return_id)
            if ret is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.SALES_RETURN.value,
                        document_id=ret.id,
                        document_number=ret.document_number,
                        status=ret.status,
                        relationship="source",
                        document_date=ret.document_date,
                    )
                )
        return related

    async def _require(
        self, tenant_id: UUID, credit_note_id: UUID, *, for_update: bool = False
    ) -> CreditNote:
        row = await self.repo.get(tenant_id, credit_note_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Credit note not found")
        return row

    async def _today(self, tenant_id: UUID) -> date:
        return today_in_timezone(await self.org.get_timezone(tenant_id))

    def _assert_version(self, row: CreditNote, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, tenant_id: UUID, row: CreditNote) -> dict[str, object]:
        customer = await self.customers.get(tenant_id, row.customer_id)
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "credit_note_date": row.credit_note_date.isoformat(),
            "customer": customer.name,
            "grand_total": str(row.grand_total),
            "tax_amount": str(row.tax_amount),
            "reason_code": row.reason_code,
        }

    async def _ensure_policy(self, tenant_id: UUID) -> PeriodLockPolicy:
        if self._period_policy is None:
            _, self._period_policy = await self.org.get_inventory_controls(tenant_id)
        return self._period_policy

    def _date_in_locked_period(self, document_date: date) -> bool:
        if self._period_policy is None:
            return False
        return self._period_policy.is_locked(document_date, can_override=False)


def _round_off_residual(
    lines: Sequence[JournalLineInput], account_id: UUID
) -> JournalLineInput | None:
    debit = quantize_money(sum((line.debit for line in lines), _ZERO))
    credit = quantize_money(sum((line.credit for line in lines), _ZERO))
    diff = quantize_money(debit - credit)
    if diff == _ZERO:
        return None
    if diff > _ZERO:
        return JournalLineInput(account_id=account_id, credit=diff, description="Round off")
    return JournalLineInput(account_id=account_id, debit=-diff, description="Round off")
