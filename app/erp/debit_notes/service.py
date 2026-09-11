"""Debit note compose, post, and void-by-reversal. Does not move stock."""

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
    DEBIT_NOTE_CANCEL,
    DEBIT_NOTE_DELETE,
    DEBIT_NOTE_POST,
    PERIOD_OVERRIDE,
    PURCHASE_MODULE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.print.schemas import PrintDocumentResponse
from app.common.print.service import PrintService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.services.audit import AuditWriter
from app.common.utils.conversion import quantity_summary
from app.common.utils.currency import quantize_money, quantize_quantity
from app.common.utils.datetime import today_in_timezone, utcnow
from app.common.utils.document_totals import (
    compute_header_totals,
    compute_line_amounts,
    format_address_snapshot,
    place_of_supply_from_address,
    resolve_line_tax_category,
)
from app.core.enums import (
    AccountSystemRole,
    AuditAction,
    DebitNoteReason,
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
from app.db.session import transaction
from app.erp.accounting.accounts.service import AccountResolver, AccountService
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.schemas import JournalEntryResponse, JournalLineInput
from app.erp.accounting.ledger.service import JournalEntryService
from app.erp.accounting.service import DocumentSequenceService, TaxService
from app.erp.debit_notes.models import DebitNote, DebitNoteLine
from app.erp.debit_notes.repository import DebitNoteRepository
from app.erp.debit_notes.schemas import (
    DebitNoteCreate,
    DebitNoteCreateFromPurchaseInvoice,
    DebitNoteCreateFromPurchaseReturn,
    DebitNoteLineInput,
    DebitNoteLineResponse,
    DebitNoteResponse,
    DebitNoteUpdate,
)
from app.erp.debit_notes.workflow import assert_editable, next_status, transition_actions
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService
from app.erp.purchase_invoices.models import PurchaseInvoice, PurchaseInvoiceLine
from app.erp.purchase_invoices.service import PurchaseInvoiceService
from app.erp.suppliers.service import SupplierService
from app.inventory_management.products.service import ProductService
from app.inventory_management.units.service import UnitService

_ZERO = Decimal("0")
_SERIES = "SDN"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": DEBIT_NOTE_POST,
    "cancel": DEBIT_NOTE_CANCEL,
}
SOURCE_DEBIT_NOTE = "debit_note"


class DebitNoteService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = DebitNoteRepository(session)
        self.org = OrganizationService(session)
        self.suppliers = SupplierService(session)
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
        self.purchase_invoices = PurchaseInvoiceService(
            session, actor_permissions=actor_permissions
        )
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
        supplier_id: UUID | None = None,
        purchase_invoice_id: UUID | None = None,
        purchase_return_id: UUID | None = None,
        currency_id: UUID | None = None,
        debit_note_date_from: date | None = None,
        debit_note_date_to: date | None = None,
    ) -> tuple[list[DebitNoteResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if supplier_id is not None:
            filters["supplier_id"] = supplier_id
        if purchase_invoice_id is not None:
            filters["purchase_invoice_id"] = purchase_invoice_id
        if purchase_return_id is not None:
            filters["purchase_return_id"] = purchase_return_id
        if currency_id is not None:
            filters["currency_id"] = currency_id
        extra: list[Any] = []
        if debit_note_date_from is not None:
            extra.append(DebitNote.debit_note_date >= debit_note_date_from)
        if debit_note_date_to is not None:
            extra.append(DebitNote.debit_note_date <= debit_note_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, debit_note_id: UUID) -> DebitNoteResponse:
        row = await self._require(tenant_id, debit_note_id)
        await self._ensure_policy(tenant_id)
        response = self._to_response(row)
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def print_document(
        self,
        tenant_id: UUID,
        debit_note_id: UUID,
        *,
        template_family: str = "uae",
    ) -> PrintDocumentResponse:
        row = await self.get(tenant_id, debit_note_id)
        supplier = await self.suppliers.get(tenant_id, row.supplier_id)
        currency = await self.currencies.get(tenant_id, row.currency_id)
        printer = PrintService(self.session)
        family = template_family if template_family in {"uae", "china"} else "uae"
        return await printer.assemble(
            tenant_id,
            document_type=DocumentType.DEBIT_NOTE.value,
            document_id=row.id,
            document_number=row.document_number,
            document_date=row.debit_note_date,
            template_family=family,
            customer_code=supplier.code,
            customer_name=supplier.name,
            customer_address=format_address_snapshot(supplier.billing_address),
            customer_trn=supplier.trn,
            currency_code=currency.code,
            subtotal=row.subtotal,
            tax_amount=row.tax_amount,
            grand_total=row.grand_total,
            notes=row.notes,
            lines=[
                printer.commercial_line(line, index=index)
                for index, line in enumerate(row.lines, start=1)
            ],
        )

    async def create(
        self, tenant_id: UUID, payload: DebitNoteCreate, *, actor_user_id: UUID
    ) -> DebitNoteResponse:
        async with transaction(self.session):
            return await self._persist_composed(tenant_id, payload, actor_user_id=actor_user_id)

    async def create_from_purchase_invoice(
        self,
        tenant_id: UUID,
        payload: DebitNoteCreateFromPurchaseInvoice,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> DebitNoteResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return DebitNoteResponse.model_validate(replay)
            invoice = await self.purchase_invoices._require(tenant_id, payload.purchase_invoice_id)
            if InvoiceDocumentStatus(invoice.status) != InvoiceDocumentStatus.POSTED:
                raise ValidationError(
                    "Debit notes can only be created from a posted purchase invoice"
                )
            lines: list[DebitNoteLineInput] = []
            first_debit = all(line.qty_debited == _ZERO for line in invoice.lines)
            for line in invoice.lines:
                outstanding = quantize_quantity(line.quantity - line.qty_debited)
                if outstanding <= _ZERO:
                    continue
                lines.append(
                    DebitNoteLineInput(
                        product_id=line.product_id,
                        description=line.description,
                        quantity=outstanding,
                        unit_id=line.unit_id,
                        rate=line.rate,
                        purchase_invoice_line_id=line.id,
                        expense_account_id=line.expense_account_id or line.purchase_account_id,
                        discount_type=(
                            DiscountType(line.discount_type) if line.discount_type else None
                        ),
                        discount_value=line.discount_value,
                        tax_id=line.tax_id,
                    )
                )
            if not lines:
                raise ValidationError("This purchase invoice has no remaining quantity to debit")
            create_payload = DebitNoteCreate(
                purchase_invoice_id=invoice.id,
                supplier_id=invoice.supplier_id,
                reason_code=payload.reason_code,
                branch_id=invoice.branch_id,
                debit_note_date=payload.debit_note_date,
                currency_id=invoice.currency_id,
                notes=payload.notes or invoice.notes,
                discount_type=(
                    DiscountType(invoice.discount_type)
                    if first_debit and invoice.discount_type
                    else None
                ),
                discount_value=invoice.discount_value if first_debit else None,
                shipping_amount=invoice.shipping_amount if first_debit else _ZERO,
                adjustment_amount=invoice.adjustment_amount if first_debit else _ZERO,
                round_off_amount=invoice.round_off_amount if first_debit else _ZERO,
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

    async def create_from_purchase_return(
        self,
        tenant_id: UUID,
        payload: DebitNoteCreateFromPurchaseReturn,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> DebitNoteResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return DebitNoteResponse.model_validate(replay)
            from app.inventory_management.purchase_returns.service import PurchaseReturnService

            purchase_returns = PurchaseReturnService(
                self.session, actor_permissions=self.actor_permissions
            )
            purchase_return = await purchase_returns._require(
                tenant_id, payload.purchase_return_id
            )
            if StockDocumentStatus(purchase_return.status) != StockDocumentStatus.POSTED:
                raise ValidationError(
                    "Debit notes can only be created from a posted purchase return"
                )
            invoice = await self._posted_invoice_for_goods_receipt(
                tenant_id, purchase_return.goods_receipt_id
            )
            pi_by_grn_line: dict[UUID, PurchaseInvoiceLine] = {}
            if invoice is not None:
                for line in invoice.lines:
                    if line.goods_receipt_line_id is not None:
                        pi_by_grn_line[line.goods_receipt_line_id] = line
            lines: list[DebitNoteLineInput] = []
            for line in purchase_return.lines:
                pi_line = pi_by_grn_line.get(line.goods_receipt_line_id)
                rate = pi_line.rate if pi_line is not None else (line.rate or None)
                if rate is not None and rate == _ZERO and pi_line is None:
                    rate = None
                lines.append(
                    DebitNoteLineInput(
                        product_id=line.product_id or (pi_line.product_id if pi_line else None),
                        description=pi_line.description if pi_line is not None else None,
                        quantity=line.quantity,
                        unit_id=line.unit_id or (pi_line.unit_id if pi_line else None),
                        rate=rate,
                        purchase_invoice_line_id=pi_line.id if pi_line is not None else None,
                        purchase_return_line_id=line.id,
                        expense_account_id=(
                            (pi_line.expense_account_id or pi_line.purchase_account_id)
                            if pi_line is not None
                            else None
                        ),
                        discount_type=(
                            DiscountType(pi_line.discount_type)
                            if pi_line is not None and pi_line.discount_type
                            else None
                        ),
                        discount_value=pi_line.discount_value if pi_line is not None else None,
                        tax_id=pi_line.tax_id if pi_line is not None else None,
                    )
                )
            if not lines:
                raise ValidationError("This purchase return has no lines to debit")
            create_payload = DebitNoteCreate(
                purchase_invoice_id=invoice.id if invoice is not None else None,
                purchase_return_id=purchase_return.id,
                supplier_id=(
                    invoice.supplier_id if invoice is not None else purchase_return.supplier_id
                ),
                reason_code=payload.reason_code,
                branch_id=invoice.branch_id if invoice is not None else None,
                debit_note_date=payload.debit_note_date,
                currency_id=invoice.currency_id if invoice is not None else None,
                notes=payload.notes or purchase_return.notes,
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
        debit_note_id: UUID,
        payload: DebitNoteUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> DebitNoteResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, debit_note_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(InvoiceDocumentStatus(row.status))
            old_values = await self._snapshot(tenant_id, row)
            create_payload = await self._update_to_create(row, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            note_date = cast(date, header["debit_note_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(note_date, can_override=self._can_override)
            for name, value in header.items():
                setattr(row, name, value)
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, debit_note_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=PURCHASE_MODULE,
                entity_type="debit_note",
                entity_id=debit_note_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        debit_note_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> DebitNoteResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, debit_note_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(InvoiceDocumentStatus(row.status))
            old_values = await self._snapshot(tenant_id, row)
            response = self._to_response(row)
            deleted = await self.repo.soft_delete(tenant_id, debit_note_id)
            if deleted is None:
                raise ResourceNotFoundError("Debit note not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=PURCHASE_MODULE,
                entity_type="debit_note",
                entity_id=debit_note_id,
                old_values=old_values,
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        debit_note_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> DebitNoteResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return DebitNoteResponse.model_validate(replay)
            row = await self._require(tenant_id, debit_note_id, for_update=True)
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
            policy.assert_open(row.debit_note_date, can_override=self._can_override)
            old_values = await self._snapshot(tenant_id, row)
            invoice = None
            if row.purchase_invoice_id is not None:
                invoice = await self._assert_qty_headroom(tenant_id, row)
            await self._recompute_posted_totals(tenant_id, row)
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_DEBIT_NOTE,
                source_id=row.id,
                entry_date=row.debit_note_date,
                lines=await self._journal_lines(tenant_id, row, invoice=invoice),
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                narration=f"Debit note {row.document_number}",
                branch_id=row.branch_id,
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
                reference=row.document_number,
            )
            row.journal_entry_id = journal.id
            if invoice is not None:
                await self._apply_invoice_debits(tenant_id, row, invoice=invoice, sign=Decimal("1"))
            if row.purchase_invoice_id is None:
                row.amount_applied = quantize_money(_ZERO)
                row.amount_unapplied = quantize_money(row.grand_total)
            else:
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
            loaded = await self._require(tenant_id, debit_note_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=PURCHASE_MODULE,
                entity_type="debit_note",
                entity_id=debit_note_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="purchase.debit_note.posted",
                aggregate_type="debit_note",
                aggregate_id=debit_note_id,
                payload={"debit_note_id": str(debit_note_id)},
                dedupe_key=f"debit-note-posted:{debit_note_id}",
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        debit_note_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        endpoint: str | None = None,
    ) -> DebitNoteResponse:
        async with transaction(self.session):
            if idempotency_key and request_hash and endpoint:
                replay = await self.idempotency.begin(
                    tenant_id, idempotency_key, request_hash, endpoint=endpoint
                )
                if replay is not None:
                    return DebitNoteResponse.model_validate(replay)
            row = await self._require(tenant_id, debit_note_id, for_update=True)
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
                module=PURCHASE_MODULE,
                entity_type="debit_note",
                entity_id=debit_note_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            if current == InvoiceDocumentStatus.POSTED:
                await self.outbox.enqueue(
                    tenant_id,
                    event_type="purchase.debit_note.cancelled",
                    aggregate_type="debit_note",
                    aggregate_id=debit_note_id,
                    payload={"debit_note_id": str(debit_note_id)},
                    dedupe_key=f"debit-note-cancelled:{debit_note_id}",
                )
            response = self._to_response(row)
            if idempotency_key and request_hash and endpoint:
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
            return response

    async def journal(self, tenant_id: UUID, debit_note_id: UUID) -> JournalEntryResponse:
        row = await self._require(tenant_id, debit_note_id)
        if row.journal_entry_id is None:
            raise ResourceNotFoundError("Debit note has no journal entry")
        return await self.journals.get(tenant_id, row.journal_entry_id)

    async def has_live_for_purchase_invoice(
        self, tenant_id: UUID, purchase_invoice_id: UUID
    ) -> bool:
        return await self.repo.has_live_for_purchase_invoice(tenant_id, purchase_invoice_id)

    async def has_live_for_purchase_return(
        self, tenant_id: UUID, purchase_return_id: UUID
    ) -> bool:
        return await self.repo.has_live_for_purchase_return(tenant_id, purchase_return_id)

    async def _persist_composed(
        self, tenant_id: UUID, payload: DebitNoteCreate, *, actor_user_id: UUID
    ) -> DebitNoteResponse:
        header, line_rows = await self._build_draft(tenant_id, payload)
        note_date = cast(date, header["debit_note_date"])
        policy = await self._ensure_policy(tenant_id)
        policy.assert_open(note_date, can_override=self._can_override)
        number = await self.sequences.allocate(
            tenant_id,
            document_type=DocumentType.DEBIT_NOTE,
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
            module=PURCHASE_MODULE,
            entity_type="debit_note",
            entity_id=row.id,
            new_values=await self._snapshot(tenant_id, loaded),
        )
        return self._to_response(loaded)

    async def _cancel_posted(
        self, tenant_id: UUID, row: DebitNote, *, actor_user_id: UUID
    ) -> None:
        policy = await self._ensure_policy(tenant_id)
        if policy.is_locked(row.debit_note_date, can_override=self._can_override):
            raise InvoiceCannotVoidError("The period is locked")
        if row.journal_entry_id is not None:
            reversal = await self.posting.reverse(
                tenant_id,
                row.journal_entry_id,
                reversal_date=row.debit_note_date,
                reason=row.cancel_reason,
                actor_id=actor_user_id,
            )
            row.reversal_journal_entry_id = reversal.id
        if row.purchase_invoice_id is not None:
            invoice = await self.purchase_invoices._require(
                tenant_id, row.purchase_invoice_id, for_update=True
            )
            await self._apply_invoice_debits(tenant_id, row, invoice=invoice, sign=Decimal("-1"))
        row.amount_applied = quantize_money(_ZERO)
        row.amount_unapplied = quantize_money(_ZERO)
        row.is_posted = False

    async def _assert_qty_headroom(self, tenant_id: UUID, row: DebitNote) -> PurchaseInvoice:
        invoice = await self.purchase_invoices._require(
            tenant_id, row.purchase_invoice_id, for_update=True
        )
        remaining = {
            line.id: quantize_quantity(line.quantity - line.qty_debited) for line in invoice.lines
        }
        for line in row.lines:
            if line.purchase_invoice_line_id is None:
                continue
            left = remaining.get(line.purchase_invoice_line_id, _ZERO)
            if line.quantity > left:
                raise InvoiceQtyExceededError(
                    details={
                        "purchase_invoice_line_id": str(line.purchase_invoice_line_id),
                        "quantity": str(line.quantity),
                        "outstanding": str(left),
                    }
                )
            remaining[line.purchase_invoice_line_id] = quantize_quantity(left - line.quantity)
        return invoice

    async def _apply_invoice_debits(
        self,
        tenant_id: UUID,
        row: DebitNote,
        *,
        invoice: PurchaseInvoice,
        sign: Decimal,
    ) -> None:
        by_id = {line.id: line for line in invoice.lines}
        for line in row.lines:
            if line.purchase_invoice_line_id is None:
                continue
            pi_line = by_id.get(line.purchase_invoice_line_id)
            if pi_line is None:
                raise ValidationError("Purchase invoice line not found on the linked invoice")
            pi_line.qty_debited = quantize_quantity(pi_line.qty_debited + line.quantity * sign)
            if pi_line.qty_debited < _ZERO:
                raise ValidationError("Debited quantity cannot be negative")
        await self.purchase_invoices.apply_debit(
            tenant_id, invoice.id, quantize_money(row.grand_total * sign)
        )

    async def apply_to_invoice(
        self,
        tenant_id: UUID,
        debit_note_id: UUID,
        invoice_id: UUID,
        amount: Decimal,
        *,
        actor_user_id: UUID,
    ) -> None:
        """Match unused debit-note credit to a bill. Subledger only — no second GL."""

        from app.core.enums import OpenItemType, PaymentAllocationSource
        from app.erp.accounting.open_items.repository import PaymentAllocationRepository

        row = await self._require(tenant_id, debit_note_id, for_update=True)
        if InvoiceDocumentStatus(row.status) != InvoiceDocumentStatus.POSTED:
            raise ValidationError("Only posted debit notes can be applied")
        amount = quantize_money(amount)
        if amount <= _ZERO:
            raise ValidationError("Apply amount must be positive")
        if amount > row.amount_unapplied:
            raise ValidationError("Apply amount exceeds unapplied debit")
        if row.purchase_invoice_id is not None and row.purchase_invoice_id != invoice_id:
            raise ValidationError("This debit note is already linked to another bill")
        await self.purchase_invoices.apply_debit(tenant_id, invoice_id, amount)
        row.amount_applied = quantize_money(row.amount_applied + amount)
        row.amount_unapplied = quantize_money(row.amount_unapplied - amount)
        await PaymentAllocationRepository(self.session).create(
            tenant_id,
            payment_type=PaymentAllocationSource.DEBIT_NOTE.value,
            payment_id=row.id,
            item_type=OpenItemType.PURCHASE_INVOICE.value,
            item_id=invoice_id,
            amount=amount,
        )
        await self.session.flush()

    async def adjust_unapplied(
        self, tenant_id: UUID, debit_note_id: UUID, amount: Decimal
    ) -> None:
        row = await self._require(tenant_id, debit_note_id, for_update=True)
        row.amount_unapplied = quantize_money(row.amount_unapplied + amount)
        row.amount_applied = quantize_money(row.grand_total - row.amount_unapplied)
        if row.amount_unapplied < _ZERO or row.amount_applied < _ZERO:
            raise ValidationError("Applied debit cannot be negative")
        await self.session.flush()

    async def _recompute_posted_totals(self, tenant_id: UUID, row: DebitNote) -> None:
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

    async def _journal_lines(
        self, tenant_id: UUID, row: DebitNote, *, invoice: PurchaseInvoice | None
    ) -> list[JournalLineInput]:
        ap = await self.accounts.party_resolver.resolve_payable(tenant_id, row.supplier_id)
        grni = await self.resolver.require(tenant_id, AccountSystemRole.GOODS_RECEIVED_NOT_INVOICED)
        vat = await self.resolver.require(tenant_id, AccountSystemRole.VAT_INPUT)
        round_off = await self.resolver.require(tenant_id, AccountSystemRole.ROUND_OFF)
        default_purchase = await self.resolver.require(tenant_id, AccountSystemRole.PURCHASES)
        pi_lines = {line.id: line for line in invoice.lines} if invoice is not None else {}
        lines: list[JournalLineInput] = []
        remaining_discount = row.discount_amount
        last_index = len(row.lines) - 1
        for index, line in enumerate(row.lines):
            if index == last_index:
                share = remaining_discount
            else:
                share = self._header_discount_share(row, line)
                remaining_discount = quantize_money(remaining_discount - share)
            net_amount = quantize_money(line.amount - share)
            account_id = await self._resolve_credit_account_id(
                tenant_id,
                line,
                pi_line=pi_lines.get(line.purchase_invoice_line_id),
                grni_id=grni.id,
                default_purchase_id=default_purchase.id,
            )
            if line.expense_account_id is None:
                line.expense_account_id = account_id
            if net_amount != _ZERO:
                lines.append(
                    JournalLineInput(
                        account_id=account_id,
                        credit=net_amount if net_amount > _ZERO else _ZERO,
                        debit=-net_amount if net_amount < _ZERO else _ZERO,
                        description=line.description,
                    )
                )
        if row.tax_amount > _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=vat.id,
                    credit=row.tax_amount,
                    description="VAT input",
                )
            )
        if row.grand_total != _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=ap.id,
                    debit=row.grand_total if row.grand_total > _ZERO else _ZERO,
                    credit=-row.grand_total if row.grand_total < _ZERO else _ZERO,
                    party_type=PartyType.SUPPLIER,
                    party_id=row.supplier_id,
                    due_date=row.due_date,
                    external_reference=row.document_number,
                    description=f"AP {row.document_number}",
                )
            )
        residual = _round_off_residual(lines, round_off.id)
        if residual is not None:
            lines.append(residual)
        return lines

    async def _resolve_credit_account_id(
        self,
        tenant_id: UUID,
        line: DebitNoteLine,
        *,
        pi_line: PurchaseInvoiceLine | None,
        grni_id: UUID,
        default_purchase_id: UUID,
    ) -> UUID:
        if pi_line is not None and pi_line.goods_receipt_line_id is not None:
            return grni_id
        if line.expense_account_id is not None:
            return line.expense_account_id
        if pi_line is not None:
            if pi_line.expense_account_id is not None:
                return pi_line.expense_account_id
            if pi_line.purchase_account_id is not None:
                return pi_line.purchase_account_id
        if line.product_id is not None:
            purchase = await self.accounts.resolve_purchase_account(tenant_id, line.product_id)
            return purchase.id
        return default_purchase_id

    def _header_discount_share(self, row: DebitNote, line: DebitNoteLine) -> Decimal:
        if row.subtotal <= _ZERO or row.discount_amount == _ZERO:
            return quantize_money(_ZERO)
        return quantize_money(row.discount_amount * line.amount / row.subtotal)

    async def _posted_invoice_for_goods_receipt(
        self, tenant_id: UUID, goods_receipt_id: UUID
    ) -> PurchaseInvoice | None:
        statement = (
            select(PurchaseInvoice)
            .where(
                PurchaseInvoice.tenant_id == tenant_id,
                PurchaseInvoice.deleted_at.is_(None),
                PurchaseInvoice.status == InvoiceDocumentStatus.POSTED.value,
                PurchaseInvoice.id.in_(
                    select(PurchaseInvoiceLine.purchase_invoice_id).where(
                        PurchaseInvoiceLine.tenant_id == tenant_id,
                        PurchaseInvoiceLine.goods_receipt_id == goods_receipt_id,
                    )
                ),
            )
            .options(selectinload(PurchaseInvoice.lines))
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def _build_draft(
        self, tenant_id: UUID, payload: DebitNoteCreate
    ) -> tuple[dict[str, object], builtins.list[dict[str, object]]]:
        supplier = await self.suppliers.get(tenant_id, payload.supplier_id)
        if payload.branch_id is not None:
            await self.org.require_branch(tenant_id, payload.branch_id)
        invoice: PurchaseInvoice | None = None
        if payload.purchase_invoice_id is not None:
            invoice = await self.purchase_invoices._require(tenant_id, payload.purchase_invoice_id)
            if InvoiceDocumentStatus(invoice.status) != InvoiceDocumentStatus.POSTED:
                raise ValidationError("Linked purchase invoice must be posted")
            if invoice.supplier_id != supplier.id:
                raise ValidationError("Debit note supplier must match the purchase invoice")
            pi_line_ids = {line.id for line in invoice.lines}
            for line in payload.lines:
                if (
                    line.purchase_invoice_line_id is not None
                    and line.purchase_invoice_line_id not in pi_line_ids
                ):
                    raise ValidationError(
                        "Debit note lines must belong to the linked purchase invoice"
                    )
        if payload.purchase_return_id is not None:
            from app.inventory_management.purchase_returns.service import PurchaseReturnService

            purchase_return = await PurchaseReturnService(
                self.session, actor_permissions=self.actor_permissions
            )._require(tenant_id, payload.purchase_return_id)
            if StockDocumentStatus(purchase_return.status) != StockDocumentStatus.POSTED:
                raise ValidationError("Linked purchase return must be posted")
            if purchase_return.supplier_id != supplier.id:
                raise ValidationError("Debit note supplier must match the purchase return")
        if invoice is None and payload.purchase_return_id is None:
            raise ValidationError("Debit notes require a purchase invoice or a purchase return")

        currency_id = payload.currency_id or (
            invoice.currency_id if invoice is not None else supplier.currency_id
        )
        await self.currencies.require_id(tenant_id, currency_id)
        base = await self.currencies.get_base(tenant_id)
        note_date = payload.debit_note_date or await self._today(tenant_id)
        resolved = await self.fx.resolve(
            tenant_id,
            from_currency_id=currency_id,
            to_currency_id=base.id,
            on_date=note_date,
        )
        place = payload.place_of_supply or (
            PlaceOfSupply(invoice.place_of_supply)
            if invoice is not None
            else place_of_supply_from_address(supplier.shipping_address)
        )
        tax_treatment = (
            TaxTreatment(invoice.tax_treatment)
            if invoice is not None
            else supplier.tax_treatment
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
            "debit_note_date": note_date,
            "purchase_invoice_id": invoice.id if invoice is not None else None,
            "purchase_return_id": payload.purchase_return_id,
            "supplier_id": supplier.id,
            "reason_code": payload.reason_code.value,
            "branch_id": payload.branch_id or (invoice.branch_id if invoice is not None else None),
            "due_date": invoice.due_date if invoice is not None else None,
            "tax_treatment": tax_treatment.value,
            "place_of_supply": place.value,
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
        lines: Sequence[DebitNoteLineInput],
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
                or (product.purchase_description if product else None)
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
                rate = quantize_money(product.purchase_rate)
            else:
                raise ValidationError("Custom lines require a rate")
            if line.expense_account_id is not None:
                await self.accounts.require_postable(tenant_id, line.expense_account_id)
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
                    "purchase_invoice_line_id": line.purchase_invoice_line_id,
                    "purchase_return_line_id": line.purchase_return_line_id,
                    "expense_account_id": line.expense_account_id,
                    "discount_type": line.discount_type.value if line.discount_type else None,
                    "discount_value": line.discount_value,
                    "discount_amount": line_discount,
                    "tax_id": chosen_tax.id,
                    "tax_rate": chosen_tax.rate,
                    "tax_amount": tax_amount,
                    "amount": net,
                }
            )
            nets.append(net)
            taxes.append(tax_amount)
        return built, nets, taxes

    async def _update_to_create(
        self, existing: DebitNote, payload: DebitNoteUpdate
    ) -> DebitNoteCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                DebitNoteLineInput(
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    purchase_invoice_line_id=line.purchase_invoice_line_id,
                    purchase_return_line_id=line.purchase_return_line_id,
                    expense_account_id=line.expense_account_id,
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    tax_id=line.tax_id,
                )
                for line in existing.lines
            ]
        return DebitNoteCreate(
            purchase_invoice_id=existing.purchase_invoice_id,
            purchase_return_id=existing.purchase_return_id,
            supplier_id=existing.supplier_id,
            reason_code=(
                values["reason_code"]
                if "reason_code" in values
                else DebitNoteReason(existing.reason_code)
            ),
            branch_id=values.get("branch_id", existing.branch_id),
            debit_note_date=values.get("debit_note_date", existing.debit_note_date),
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

    async def _row_to_create(self, row: DebitNote) -> DebitNoteCreate:
        return DebitNoteCreate(
            purchase_invoice_id=row.purchase_invoice_id,
            purchase_return_id=row.purchase_return_id,
            supplier_id=row.supplier_id,
            reason_code=DebitNoteReason(row.reason_code),
            branch_id=row.branch_id,
            debit_note_date=row.debit_note_date,
            currency_id=row.currency_id,
            notes=row.notes,
            discount_type=DiscountType(row.discount_type) if row.discount_type else None,
            discount_value=row.discount_value,
            shipping_amount=row.shipping_amount,
            adjustment_amount=row.adjustment_amount,
            round_off_amount=row.round_off_amount,
            place_of_supply=PlaceOfSupply(row.place_of_supply),
            lines=[
                DebitNoteLineInput(
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    purchase_invoice_line_id=line.purchase_invoice_line_id,
                    purchase_return_line_id=line.purchase_return_line_id,
                    expense_account_id=line.expense_account_id,
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    tax_id=line.tax_id,
                )
                for line in row.lines
            ],
        )

    def _available_actions(
        self, row: DebitNote, status: InvoiceDocumentStatus, *, period_locked: bool
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
            self.actor_permissions, DEBIT_NOTE_DELETE
        ):
            actions.append("delete")
        return actions

    def _to_response(self, row: DebitNote) -> DebitNoteResponse:
        status = InvoiceDocumentStatus(row.status)
        period_locked = self._date_in_locked_period(row.debit_note_date)
        return DebitNoteResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            display_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=row.is_posted,
            debit_note_date=row.debit_note_date,
            document_date=row.debit_note_date,
            purchase_invoice_id=row.purchase_invoice_id,
            purchase_return_id=row.purchase_return_id,
            supplier_id=row.supplier_id,
            reason_code=DebitNoteReason(row.reason_code),
            branch_id=row.branch_id,
            due_date=row.due_date,
            tax_treatment=TaxTreatment(row.tax_treatment),
            place_of_supply=PlaceOfSupply(row.place_of_supply),
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
                DebitNoteLineResponse(
                    id=line.id,
                    line_number=line.line_number,
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    purchase_invoice_line_id=line.purchase_invoice_line_id,
                    purchase_return_line_id=line.purchase_return_line_id,
                    expense_account_id=line.expense_account_id,
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    discount_amount=line.discount_amount,
                    tax_id=line.tax_id,
                    tax_rate=line.tax_rate,
                    tax_amount=line.tax_amount,
                    amount=line.amount,
                )
                for line in row.lines
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _related_documents(
        self, tenant_id: UUID, row: DebitNote
    ) -> builtins.list[RelatedDocumentRef]:
        from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository

        related: builtins.list[RelatedDocumentRef] = []
        if row.purchase_invoice_id is not None:
            invoice = await PurchaseInvoiceRepository(self.session).get(
                tenant_id, row.purchase_invoice_id
            )
            if invoice is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.PURCHASE_INVOICE.value,
                        document_id=invoice.id,
                        document_number=invoice.document_number,
                        status=invoice.status,
                        relationship="source",
                        document_date=invoice.invoice_date,
                        quantity_summary=quantity_summary(
                            [line.quantity for line in invoice.lines]
                        ),
                    )
                )
        if row.purchase_return_id is not None:
            from app.inventory_management.purchase_returns.repository import (
                PurchaseReturnRepository,
            )

            ret = await PurchaseReturnRepository(self.session).get(
                tenant_id, row.purchase_return_id
            )
            if ret is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.PURCHASE_RETURN.value,
                        document_id=ret.id,
                        document_number=ret.document_number,
                        status=ret.status,
                        relationship="source",
                        document_date=ret.document_date,
                        quantity_summary=quantity_summary([line.quantity for line in ret.lines]),
                    )
                )
        return related

    async def _require(
        self, tenant_id: UUID, debit_note_id: UUID, *, for_update: bool = False
    ) -> DebitNote:
        row = await self.repo.get(tenant_id, debit_note_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Debit note not found")
        return row

    async def _today(self, tenant_id: UUID) -> date:
        return today_in_timezone(await self.org.get_timezone(tenant_id))

    def _assert_version(self, row: DebitNote, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, tenant_id: UUID, row: DebitNote) -> dict[str, object]:
        supplier = await self.suppliers.get(tenant_id, row.supplier_id)
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "debit_note_date": row.debit_note_date.isoformat(),
            "supplier": supplier.name,
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
