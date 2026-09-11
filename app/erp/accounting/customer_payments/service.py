"""Customer receipts: bank, AR allocations, PFI advances, refunds."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    CUSTOMER_PAYMENT_CANCEL,
    CUSTOMER_PAYMENT_DELETE,
    CUSTOMER_PAYMENT_POST,
    SALES_MODULE,
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
from app.common.utils.currency import quantize_money
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
    TaxCategory,
    TaxTreatment,
)
from app.core.exceptions import (
    DocumentStaleError,
    InvoiceCannotVoidError,
    PaymentAccountInvalidError,
    PaymentNothingToApplyError,
    PaymentOverAllocatedError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.crm.customers.service import CustomerService
from app.db.session import transaction
from app.erp.accounting.accounts.service import (
    AccountResolver,
    AccountService,
    PartyAccountResolver,
)
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.schemas import JournalEntryResponse, JournalLineInput
from app.erp.accounting.ledger.service import JournalEntryService
from app.erp.accounting.open_items.repository import PaymentAllocationRepository
from app.erp.accounting.open_items.schemas import PaymentAllocationInput
from app.erp.accounting.open_items.service import OpenItemsService
from app.erp.accounting.service import DocumentSequenceService, TaxService
from app.erp.accounting.customer_payments.models import CustomerPayment
from app.erp.accounting.customer_payments.repository import CustomerPaymentRepository
from app.erp.accounting.customer_payments.schemas import (
    CustomerPaymentAllocationResponse,
    CustomerPaymentCreate,
    CustomerPaymentResponse,
    CustomerPaymentUpdate,
)
from app.erp.accounting.customer_payments.workflow import assert_editable, next_status, transition_actions
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_SERIES = "RCP"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": CUSTOMER_PAYMENT_POST,
    "cancel": CUSTOMER_PAYMENT_CANCEL,
}
SOURCE_CUSTOMER_PAYMENT = "customer_payment"
SOURCE_CUSTOMER_PAYMENT_ALLOCATION = "customer_payment_allocation"
SOURCE_CUSTOMER_PAYMENT_REFUND = "customer_payment_refund"
_ALLOCATABLE = frozenset({OpenItemType.SALES_INVOICE, OpenItemType.OPENING_AR})


class CustomerPaymentService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = CustomerPaymentRepository(session)
        self.allocations = PaymentAllocationRepository(session)
        self.open_items = OpenItemsService(session)
        self.org = OrganizationService(session)
        self.customers = CustomerService(session)
        self.currencies = CurrencyService(session)
        self.fx = ExchangeRateService(session)
        self.taxes = TaxService(session)
        self.sequences = DocumentSequenceService(session)
        self.accounts = AccountService(session)
        self.resolver = AccountResolver(session)
        self.party_accounts = PartyAccountResolver(session)
        self.posting = LedgerPostingService(session, actor_permissions=actor_permissions)
        self.journals = JournalEntryService(session, actor_permissions=actor_permissions)
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
        proforma_invoice_id: UUID | None = None,
        sales_order_id: UUID | None = None,
        currency_id: UUID | None = None,
        payment_method: str | None = None,
        payment_date_from: date | None = None,
        payment_date_to: date | None = None,
    ) -> tuple[list[CustomerPaymentResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if customer_id is not None:
            filters["customer_id"] = customer_id
        if proforma_invoice_id is not None:
            filters["proforma_invoice_id"] = proforma_invoice_id
        if sales_order_id is not None:
            filters["sales_order_id"] = sales_order_id
        if currency_id is not None:
            filters["currency_id"] = currency_id
        if payment_method is not None:
            filters["payment_method"] = payment_method
        extra: list[Any] = []
        if payment_date_from is not None:
            extra.append(CustomerPayment.payment_date >= payment_date_from)
        if payment_date_to is not None:
            extra.append(CustomerPayment.payment_date <= payment_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [await self._to_response(tenant_id, row) for row in rows], total

    async def get(self, tenant_id: UUID, payment_id: UUID) -> CustomerPaymentResponse:
        row = await self._require(tenant_id, payment_id)
        await self._ensure_policy(tenant_id)
        response = await self._to_response(tenant_id, row)
        response.related_documents = await self._related_documents(tenant_id, row)
        response.realized_fx_amount = await self._realized_fx_amount(
            tenant_id, row.journal_entry_id
        )
        return response

    async def create(
        self, tenant_id: UUID, payload: CustomerPaymentCreate, *, actor_user_id: UUID
    ) -> CustomerPaymentResponse:
        async with transaction(self.session):
            values = await self._draft_values(tenant_id, payload)
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(values["payment_date"], can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.CUSTOMER_PAYMENT,
                series=_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, values["payment_date"]),
                prefix=_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **values,
                    "document_number": number,
                    "status": InvoiceDocumentStatus.DRAFT.value,
                    "version": 1,
                    "is_posted": False,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self._replace_draft_allocations(tenant_id, row, payload.allocations)
            loaded = await self._require(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=SALES_MODULE,
                entity_type="customer_payment",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return await self._to_response(tenant_id, loaded)

    async def update(
        self,
        tenant_id: UUID,
        payment_id: UUID,
        payload: CustomerPaymentUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> CustomerPaymentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, payment_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(InvoiceDocumentStatus(row.status))
            old_values = await self._snapshot(tenant_id, row)
            merged = await self._merged_create(row, payload)
            values = await self._draft_values(tenant_id, merged)
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(values["payment_date"], can_override=self._can_override)
            for name, value in values.items():
                setattr(row, name, value)
            row.version += 1
            row.updated_by = actor_user_id
            if payload.allocations is not None:
                await self._replace_draft_allocations(tenant_id, row, payload.allocations)
            await self.session.flush()
            loaded = await self._require(tenant_id, payment_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=SALES_MODULE,
                entity_type="customer_payment",
                entity_id=payment_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return await self._to_response(tenant_id, loaded)

    async def delete(
        self,
        tenant_id: UUID,
        payment_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> CustomerPaymentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, payment_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(InvoiceDocumentStatus(row.status))
            old_values = await self._snapshot(tenant_id, row)
            response = await self._to_response(tenant_id, row)
            await self.allocations.delete_live_for_payment(
                tenant_id, PaymentAllocationSource.CUSTOMER_PAYMENT.value, payment_id
            )
            deleted = await self.repo.soft_delete(tenant_id, payment_id)
            if deleted is None:
                raise ResourceNotFoundError("Customer payment not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=SALES_MODULE,
                entity_type="customer_payment",
                entity_id=payment_id,
                old_values=old_values,
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        payment_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> CustomerPaymentResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return CustomerPaymentResponse.model_validate(replay)
            row = await self._require(tenant_id, payment_id, for_update=True)
            if InvoiceDocumentStatus(row.status) == InvoiceDocumentStatus.POSTED:
                response = await self._to_response(tenant_id, row)
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
                return response
            self._assert_version(row, expected_version)
            target = next_status(InvoiceDocumentStatus(row.status), "post")
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(row.payment_date, can_override=self._can_override)
            old_values = await self._snapshot(tenant_id, row)
            await self._apply_rate(tenant_id, row)
            lines, tax_amount = await self._post_journal_lines(tenant_id, row)
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_CUSTOMER_PAYMENT,
                source_id=row.id,
                entry_date=row.payment_date,
                lines=lines,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                narration=f"Customer receipt {row.document_number}",
                branch_id=None,
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
                reference=row.document_number,
            )
            row.journal_entry_id = journal.id
            row.tax_amount = tax_amount
            await self._settle_allocations(tenant_id, row, sign=Decimal("1"))
            row.status = target.value
            row.is_posted = True
            row.posted_at = utcnow()
            row.posted_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            loaded = await self._require(tenant_id, payment_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=SALES_MODULE,
                entity_type="customer_payment",
                entity_id=payment_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="sales.customer_payment.posted",
                aggregate_type="customer_payment",
                aggregate_id=payment_id,
                payload={"customer_payment_id": str(payment_id)},
                dedupe_key=f"customer-payment-posted:{payment_id}",
            )
            response = await self._to_response(tenant_id, loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        payment_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> CustomerPaymentResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return CustomerPaymentResponse.model_validate(replay)
            row = await self._require(tenant_id, payment_id, for_update=True)
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
            loaded = await self._require(tenant_id, payment_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CANCEL,
                module=SALES_MODULE,
                entity_type="customer_payment",
                entity_id=payment_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="sales.customer_payment.cancelled",
                aggregate_type="customer_payment",
                aggregate_id=payment_id,
                payload={"customer_payment_id": str(payment_id)},
                dedupe_key=f"customer-payment-cancelled:{payment_id}",
            )
            response = await self._to_response(tenant_id, loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def allocate(
        self,
        tenant_id: UUID,
        payment_id: UUID,
        allocations: Sequence[PaymentAllocationInput],
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> CustomerPaymentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, payment_id, for_update=True)
            self._assert_version(row, expected_version)
            if InvoiceDocumentStatus(row.status) != InvoiceDocumentStatus.POSTED:
                raise ValidationError("Only posted receipts can be allocated")
            if row.amount_unapplied <= _ZERO:
                raise PaymentNothingToApplyError()
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(row.payment_date, can_override=self._can_override)
            old_values = await self._snapshot(tenant_id, row)
            total = quantize_money(sum((item.amount for item in allocations), _ZERO))
            if total > row.amount_unapplied:
                raise PaymentOverAllocatedError(
                    details={
                        "amount_unapplied": str(row.amount_unapplied),
                        "allocated": str(total),
                    }
                )
            vat_ratio = (
                row.tax_amount / row.amount_unapplied
                if row.amount_unapplied > _ZERO and row.tax_amount > _ZERO
                else _ZERO
            )
            for item in allocations:
                await self._allocate_posted_slice(
                    tenant_id,
                    row,
                    item,
                    actor_user_id=actor_user_id,
                    vat_ratio=vat_ratio,
                )
            row.amount_unapplied = quantize_money(row.amount_unapplied - total)
            row.tax_amount = quantize_money(row.tax_amount - quantize_money(total * vat_ratio))
            if row.amount_unapplied <= _ZERO:
                row.tax_amount = _ZERO
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            loaded = await self._require(tenant_id, payment_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=SALES_MODULE,
                entity_type="customer_payment",
                entity_id=payment_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="sales.customer_payment.allocated",
                aggregate_type="customer_payment",
                aggregate_id=payment_id,
                payload={"customer_payment_id": str(payment_id)},
                dedupe_key=f"customer-payment-allocated:{payment_id}:{row.version}",
            )
            return await self._to_response(tenant_id, loaded)

    async def refund(
        self,
        tenant_id: UUID,
        payment_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> CustomerPaymentResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return CustomerPaymentResponse.model_validate(replay)
            row = await self._require(tenant_id, payment_id, for_update=True)
            self._assert_version(row, expected_version)
            if InvoiceDocumentStatus(row.status) != InvoiceDocumentStatus.POSTED:
                raise ValidationError("Only posted receipts can be refunded")
            if row.refund_journal_entry_id is not None:
                response = await self._to_response(tenant_id, row)
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
                return response
            if row.amount_unapplied <= _ZERO:
                raise PaymentNothingToApplyError()
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(row.payment_date, can_override=self._can_override)
            old_values = await self._snapshot(tenant_id, row)
            lines = await self._refund_journal_lines(tenant_id, row)
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_CUSTOMER_PAYMENT_REFUND,
                source_id=row.id,
                entry_date=row.payment_date,
                lines=lines,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                narration=f"Refund receipt {row.document_number}",
                branch_id=None,
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
                reference=row.document_number,
            )
            row.refund_journal_entry_id = journal.id
            row.amount_refunded = quantize_money(row.amount_refunded + row.amount_unapplied)
            row.amount_unapplied = _ZERO
            row.tax_amount = _ZERO
            row.refunded_at = utcnow()
            row.refunded_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            loaded = await self._require(tenant_id, payment_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.REVERSE,
                module=SALES_MODULE,
                entity_type="customer_payment",
                entity_id=payment_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            response = await self._to_response(tenant_id, loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def auto_apply_pfi_advances(
        self,
        tenant_id: UUID,
        *,
        invoice_id: UUID,
        customer_id: UUID,
        proforma_invoice_id: UUID,
        actor_user_id: UUID,
    ) -> None:
        settings = await self.org.get_money_movement_settings(tenant_id)
        if not settings.auto_apply_advances_on_invoice:
            return
        from app.erp.sales_invoices.service import SalesInvoiceService

        invoices = SalesInvoiceService(self.session, actor_permissions=self.actor_permissions)
        invoice = await invoices._require(tenant_id, invoice_id, for_update=True)
        payments = await self.repo.list_unapplied_for_pfi(
            tenant_id, customer_id, proforma_invoice_id
        )
        for payment in payments:
            if invoice.balance_due <= _ZERO:
                break
            locked = await self._require(tenant_id, payment.id, for_update=True)
            apply_amount = quantize_money(min(locked.amount_unapplied, invoice.balance_due))
            if apply_amount <= _ZERO:
                continue
            vat_ratio = (
                locked.tax_amount / locked.amount_unapplied
                if locked.amount_unapplied > _ZERO and locked.tax_amount > _ZERO
                else _ZERO
            )
            await self._allocate_posted_slice(
                tenant_id,
                locked,
                PaymentAllocationInput(
                    item_type=OpenItemType.SALES_INVOICE,
                    item_id=invoice.id,
                    amount=apply_amount,
                ),
                actor_user_id=actor_user_id,
                vat_ratio=vat_ratio,
            )
            locked.amount_unapplied = quantize_money(locked.amount_unapplied - apply_amount)
            locked.tax_amount = quantize_money(
                locked.tax_amount - quantize_money(apply_amount * vat_ratio)
            )
            if locked.amount_unapplied <= _ZERO:
                locked.tax_amount = _ZERO
            await self.session.flush()
            invoice = await invoices._require(tenant_id, invoice_id, for_update=True)

    async def apply_credits_to_invoice(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        allocations: Sequence[PaymentAllocationInput] | None,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> Any:
        from app.erp.credit_notes.service import CreditNoteService
        from app.erp.sales_invoices.service import SalesInvoiceService

        invoices = SalesInvoiceService(self.session, actor_permissions=self.actor_permissions)
        notes = CreditNoteService(self.session, actor_permissions=self.actor_permissions)
        async with transaction(self.session):
            invoice = await invoices._require(tenant_id, invoice_id, for_update=True)
            invoices._assert_version(invoice, expected_version)
            if InvoiceDocumentStatus(invoice.status) != InvoiceDocumentStatus.POSTED:
                raise ValidationError("Credits can only be applied to a posted invoice")
            if invoice.balance_due <= _ZERO:
                raise PaymentNothingToApplyError()
            items = list(allocations or [])
            if not items:
                items = await self._fifo_credits(tenant_id, invoice)
            if not items:
                raise PaymentNothingToApplyError()
            for item in items:
                if invoice.balance_due <= _ZERO:
                    break
                amount = quantize_money(min(item.amount, invoice.balance_due))
                if amount <= _ZERO:
                    continue
                if item.item_type == OpenItemType.CREDIT_NOTE:
                    await notes.apply_to_invoice(
                        tenant_id, item.item_id, invoice.id, amount, actor_user_id=actor_user_id
                    )
                elif item.item_type == OpenItemType.CUSTOMER_PAYMENT:
                    payment = await self._require(tenant_id, item.item_id, for_update=True)
                    if payment.amount_unapplied < amount:
                        raise PaymentOverAllocatedError()
                    vat_ratio = (
                        payment.tax_amount / payment.amount_unapplied
                        if payment.amount_unapplied > _ZERO and payment.tax_amount > _ZERO
                        else _ZERO
                    )
                    await self._allocate_posted_slice(
                        tenant_id,
                        payment,
                        PaymentAllocationInput(
                            item_type=OpenItemType.SALES_INVOICE,
                            item_id=invoice.id,
                            amount=amount,
                        ),
                        actor_user_id=actor_user_id,
                        vat_ratio=vat_ratio,
                    )
                    payment.amount_unapplied = quantize_money(payment.amount_unapplied - amount)
                    payment.tax_amount = quantize_money(
                        payment.tax_amount - quantize_money(amount * vat_ratio)
                    )
                    if payment.amount_unapplied <= _ZERO:
                        payment.tax_amount = _ZERO
                else:
                    raise ValidationError("apply-credits only accepts credit notes or receipts")
                invoice = await invoices._require(tenant_id, invoice_id, for_update=True)
            invoice.version += 1
            await self.session.flush()
            loaded = await invoices._require(tenant_id, invoice_id)
            return invoices._to_response(loaded)

    async def journal(self, tenant_id: UUID, payment_id: UUID) -> JournalEntryResponse:
        row = await self._require(tenant_id, payment_id)
        if row.journal_entry_id is None:
            raise ResourceNotFoundError("Journal entry not found")
        return await self.journals.get(tenant_id, row.journal_entry_id)

    async def has_live_for_sales_invoice(self, tenant_id: UUID, sales_invoice_id: UUID) -> bool:
        return await self.allocations.has_live_for_item(
            tenant_id, OpenItemType.SALES_INVOICE.value, sales_invoice_id
        )

    async def list_for_sales_invoice(
        self, tenant_id: UUID, sales_invoice_id: UUID
    ) -> list[CustomerPayment]:
        matches = await self.allocations.list_live_for_item(
            tenant_id, OpenItemType.SALES_INVOICE.value, sales_invoice_id
        )
        payments: list[CustomerPayment] = []
        seen: set[UUID] = set()
        for allocation in matches:
            if allocation.payment_type != PaymentAllocationSource.CUSTOMER_PAYMENT.value:
                continue
            if allocation.payment_id in seen:
                continue
            seen.add(allocation.payment_id)
            row = await self.repo.get(tenant_id, allocation.payment_id)
            if (
                row is not None
                and InvoiceDocumentStatus(row.status) != InvoiceDocumentStatus.CANCELLED
            ):
                payments.append(row)
        return payments

    async def list_for_sales_order(
        self, tenant_id: UUID, sales_order_id: UUID
    ) -> list[CustomerPayment]:
        return await self.repo.list_for_sales_order(tenant_id, sales_order_id)

    async def list_for_proforma_invoice(
        self, tenant_id: UUID, proforma_invoice_id: UUID
    ) -> list[CustomerPayment]:
        return await self.repo.list_for_proforma_invoice(tenant_id, proforma_invoice_id)

    async def _fifo_credits(self, tenant_id: UUID, invoice: Any) -> list[PaymentAllocationInput]:
        items = await self.open_items.list_ar_open_items(tenant_id, invoice.customer_id)
        remaining = invoice.balance_due
        chosen: list[PaymentAllocationInput] = []
        for item in items:
            if remaining <= _ZERO:
                break
            if item.item_type not in {OpenItemType.CREDIT_NOTE, OpenItemType.CUSTOMER_PAYMENT}:
                continue
            amount = quantize_money(min(item.balance, remaining))
            if amount <= _ZERO:
                continue
            chosen.append(
                PaymentAllocationInput(
                    item_type=item.item_type, item_id=item.document_id, amount=amount
                )
            )
            remaining = quantize_money(remaining - amount)
        return chosen

    async def _cancel_posted(
        self, tenant_id: UUID, row: CustomerPayment, *, actor_user_id: UUID
    ) -> None:
        policy = await self._ensure_policy(tenant_id)
        if policy.is_locked(row.payment_date, can_override=self._can_override):
            raise InvoiceCannotVoidError("The period is locked")
        if row.amount_refunded > _ZERO:
            raise InvoiceCannotVoidError("This receipt has a refund and cannot be cancelled")
        live = await self.allocations.list_live_for_payment(
            tenant_id, PaymentAllocationSource.CUSTOMER_PAYMENT.value, row.id
        )
        for allocation in live:
            if allocation.journal_entry_id is not None:
                await self.posting.reverse(
                    tenant_id,
                    allocation.journal_entry_id,
                    reversal_date=row.payment_date,
                    reason=row.cancel_reason,
                    actor_id=actor_user_id,
                )
            allocation.reversed_at = utcnow()
        await self._settle_allocations(tenant_id, row, sign=Decimal("-1"), allocations=live)
        if row.journal_entry_id is not None:
            reversal = await self.posting.reverse(
                tenant_id,
                row.journal_entry_id,
                reversal_date=row.payment_date,
                reason=row.cancel_reason,
                actor_id=actor_user_id,
            )
            row.reversal_journal_entry_id = reversal.id
        row.amount_unapplied = _ZERO
        row.tax_amount = _ZERO
        row.is_posted = False

    async def _settle_allocations(
        self,
        tenant_id: UUID,
        row: CustomerPayment,
        *,
        sign: Decimal,
        allocations: Sequence[Any] | None = None,
    ) -> None:
        from app.erp.sales_invoices.service import SalesInvoiceService

        invoices = SalesInvoiceService(self.session, actor_permissions=self.actor_permissions)
        live = list(
            allocations
            if allocations is not None
            else await self.allocations.list_live_for_payment(
                tenant_id, PaymentAllocationSource.CUSTOMER_PAYMENT.value, row.id
            )
        )
        for allocation in live:
            item_type = OpenItemType(allocation.item_type)
            amount = quantize_money(allocation.amount * sign)
            if item_type == OpenItemType.SALES_INVOICE:
                await invoices.apply_payment(tenant_id, allocation.item_id, amount)
            elif item_type == OpenItemType.CREDIT_NOTE:
                from app.erp.credit_notes.service import CreditNoteService

                await CreditNoteService(
                    self.session, actor_permissions=self.actor_permissions
                ).adjust_unapplied(tenant_id, allocation.item_id, -amount)

    async def _allocate_posted_slice(
        self,
        tenant_id: UUID,
        row: CustomerPayment,
        item: PaymentAllocationInput,
        *,
        actor_user_id: UUID,
        vat_ratio: Decimal,
    ) -> None:
        if item.item_type not in {OpenItemType.SALES_INVOICE, OpenItemType.OPENING_AR}:
            raise ValidationError("Receipts allocate to invoices or opening AR only")
        open_row = await self._require_open_item(tenant_id, row.customer_id, item)
        if item.amount > open_row.balance:
            raise PaymentOverAllocatedError(
                details={"item_id": str(item.item_id), "balance": str(open_row.balance)}
            )
        if open_row.currency_id != row.currency_id:
            raise ValidationError("Payment currency must match the open item currency")
        vat_amount = quantize_money(item.amount * vat_ratio)
        net_amount = quantize_money(item.amount - vat_amount)
        lines = await self._application_journal_lines(
            tenant_id,
            row,
            item=item,
            open_row=open_row,
            net_amount=net_amount,
            vat_amount=vat_amount,
        )
        allocation = await self.allocations.create(
            tenant_id,
            payment_type=PaymentAllocationSource.CUSTOMER_PAYMENT.value,
            payment_id=row.id,
            item_type=item.item_type.value,
            item_id=item.item_id,
            amount=item.amount,
        )
        journal = await self.posting.post_for_document(
            tenant_id,
            source_type=SOURCE_CUSTOMER_PAYMENT_ALLOCATION,
            source_id=allocation.id,
            entry_date=row.payment_date,
            lines=lines,
            currency_id=row.currency_id,
            exchange_rate=row.exchange_rate,
            narration=f"Apply receipt {row.document_number}",
            branch_id=None,
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
        )

    async def _post_journal_lines(
        self, tenant_id: UUID, row: CustomerPayment
    ) -> tuple[list[JournalLineInput], Decimal]:
        allocations = await self.allocations.list_live_for_payment(
            tenant_id, PaymentAllocationSource.CUSTOMER_PAYMENT.value, row.id
        )
        allocated = quantize_money(sum((item.amount for item in allocations), _ZERO))
        if allocated > row.amount_received:
            raise PaymentOverAllocatedError(
                details={"amount_received": str(row.amount_received), "allocated": str(allocated)}
            )
        unapplied = quantize_money(row.amount_received - allocated)
        row.amount_unapplied = unapplied
        ar = await self.party_accounts.resolve_receivable(tenant_id, row.customer_id)
        advance = await self.resolver.require(tenant_id, AccountSystemRole.ADVANCE_FROM_CUSTOMER)
        vat_account = await self.resolver.require(tenant_id, AccountSystemRole.VAT_OUTPUT)
        fx_account = await self.resolver.require(tenant_id, AccountSystemRole.FX_GAIN_LOSS)
        charges_account = await self.resolver.require(tenant_id, AccountSystemRole.BANK_CHARGES)
        lines: list[JournalLineInput] = [
            JournalLineInput(
                account_id=row.payment_account_id,
                debit=row.amount_received,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                description=f"Receipt {row.document_number}",
            )
        ]
        if row.bank_charges > _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=charges_account.id,
                    debit=row.bank_charges,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    description="Bank charges",
                )
            )
            lines.append(
                JournalLineInput(
                    account_id=row.payment_account_id,
                    credit=row.bank_charges,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    description="Bank charges",
                )
            )
        fx_total = _ZERO
        for allocation in allocations:
            open_row = await self._require_open_item(
                tenant_id,
                row.customer_id,
                PaymentAllocationInput(
                    item_type=OpenItemType(allocation.item_type),
                    item_id=allocation.item_id,
                    amount=allocation.amount,
                ),
            )
            if open_row.currency_id != row.currency_id:
                raise ValidationError("Payment currency must match the open item currency")
            item_rate = open_row.exchange_rate or row.exchange_rate
            lines.append(
                JournalLineInput(
                    account_id=ar.id,
                    credit=allocation.amount,
                    currency_id=row.currency_id,
                    exchange_rate=item_rate,
                    party_type=PartyType.CUSTOMER,
                    party_id=row.customer_id,
                    description=open_row.document_number,
                )
            )
            fx_total += quantize_money(
                allocation.amount * row.exchange_rate - allocation.amount * item_rate
            )
        tax_amount = _ZERO
        if unapplied > _ZERO:
            net, tax_amount = await self._split_advance_vat(tenant_id, row, unapplied)
            lines.append(
                JournalLineInput(
                    account_id=advance.id,
                    credit=net,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    party_type=PartyType.CUSTOMER,
                    party_id=row.customer_id,
                    description="Unapplied receipt",
                )
            )
            if tax_amount > _ZERO:
                lines.append(
                    JournalLineInput(
                        account_id=vat_account.id,
                        credit=tax_amount,
                        currency_id=row.currency_id,
                        exchange_rate=row.exchange_rate,
                        tax_id=row.tax_id,
                        description="VAT on advance",
                    )
                )
        self._append_fx(lines, fx_account.id, fx_total, row)
        return lines, tax_amount

    async def _application_journal_lines(
        self,
        tenant_id: UUID,
        row: CustomerPayment,
        *,
        item: PaymentAllocationInput,
        open_row: Any,
        net_amount: Decimal,
        vat_amount: Decimal,
    ) -> list[JournalLineInput]:
        ar = await self.party_accounts.resolve_receivable(tenant_id, row.customer_id)
        advance = await self.resolver.require(tenant_id, AccountSystemRole.ADVANCE_FROM_CUSTOMER)
        vat_account = await self.resolver.require(tenant_id, AccountSystemRole.VAT_OUTPUT)
        fx_account = await self.resolver.require(tenant_id, AccountSystemRole.FX_GAIN_LOSS)
        item_rate = open_row.exchange_rate or row.exchange_rate
        lines = [
            JournalLineInput(
                account_id=advance.id,
                debit=net_amount,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                party_type=PartyType.CUSTOMER,
                party_id=row.customer_id,
                description=f"Apply {row.document_number}",
            ),
            JournalLineInput(
                account_id=ar.id,
                credit=item.amount,
                currency_id=row.currency_id,
                exchange_rate=item_rate,
                party_type=PartyType.CUSTOMER,
                party_id=row.customer_id,
                description=open_row.document_number,
            ),
        ]
        if vat_amount > _ZERO:
            lines.insert(
                1,
                JournalLineInput(
                    account_id=vat_account.id,
                    debit=vat_amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    tax_id=row.tax_id,
                    description="Reverse advance VAT",
                ),
            )
        fx_total = quantize_money(item.amount * row.exchange_rate - item.amount * item_rate)
        self._append_fx(lines, fx_account.id, fx_total, row)
        return lines

    async def _refund_journal_lines(
        self, tenant_id: UUID, row: CustomerPayment
    ) -> list[JournalLineInput]:
        advance = await self.resolver.require(tenant_id, AccountSystemRole.ADVANCE_FROM_CUSTOMER)
        vat_account = await self.resolver.require(tenant_id, AccountSystemRole.VAT_OUTPUT)
        net = quantize_money(row.amount_unapplied - row.tax_amount)
        lines = [
            JournalLineInput(
                account_id=advance.id,
                debit=net,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                party_type=PartyType.CUSTOMER,
                party_id=row.customer_id,
                description=f"Refund {row.document_number}",
            ),
            JournalLineInput(
                account_id=row.payment_account_id,
                credit=row.amount_unapplied,
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                description=f"Refund {row.document_number}",
            ),
        ]
        if row.tax_amount > _ZERO:
            lines.insert(
                1,
                JournalLineInput(
                    account_id=vat_account.id,
                    debit=row.tax_amount,
                    currency_id=row.currency_id,
                    exchange_rate=row.exchange_rate,
                    tax_id=row.tax_id,
                    description="Reverse advance VAT",
                ),
            )
        return lines

    def _append_fx(
        self,
        lines: list[JournalLineInput],
        fx_account_id: UUID,
        fx_total: Decimal,
        row: CustomerPayment,
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

    async def _realized_fx_amount(
        self, tenant_id: UUID, journal_entry_id: UUID | None
    ) -> Decimal | None:
        if journal_entry_id is None:
            return None
        fx_account = await self.resolver.require(tenant_id, AccountSystemRole.FX_GAIN_LOSS)
        journal = await self.journals.get(tenant_id, journal_entry_id)
        total = _ZERO
        for line in journal.lines:
            if line.account_id == fx_account.id:
                total += line.credit - line.debit
        return quantize_money(total)

    async def _split_advance_vat(
        self, tenant_id: UUID, row: CustomerPayment, unapplied: Decimal
    ) -> tuple[Decimal, Decimal]:
        settings = await self.org.get_money_movement_settings(tenant_id)
        if not settings.vat_on_advances or unapplied <= _ZERO:
            return unapplied, _ZERO
        customer = await self.customers.get(tenant_id, row.customer_id)
        if customer.tax_treatment == TaxTreatment.EXPORT:
            return unapplied, _ZERO
        tax = None
        if row.tax_id is not None:
            tax = await self.taxes.get(tenant_id, row.tax_id)
        elif row.proforma_invoice_id is not None:
            from app.erp.proforma_invoices.service import ProformaInvoiceService

            pfi = await ProformaInvoiceService(self.session).get(
                tenant_id, row.proforma_invoice_id
            )
            if pfi.tax_treatment == TaxTreatment.EXPORT:
                return unapplied, _ZERO
        if tax is None or tax.tax_category != TaxCategory.STANDARD or tax.rate <= _ZERO:
            return unapplied, _ZERO
        vat = quantize_money(unapplied * tax.rate / (_HUNDRED + tax.rate))
        return quantize_money(unapplied - vat), vat

    async def _draft_values(
        self, tenant_id: UUID, payload: CustomerPaymentCreate
    ) -> dict[str, object]:
        customer = await self.customers.get(tenant_id, payload.customer_id)
        payment_date = payload.payment_date or await self._today(tenant_id)
        currency_id = payload.currency_id or customer.currency_id
        base = await self.currencies.get_base(tenant_id)
        rate = (
            await self.fx.resolve(
                tenant_id,
                from_currency_id=currency_id,
                to_currency_id=base.id,
                on_date=payment_date,
            )
        ).rate
        await self._require_payment_account(tenant_id, payload.payment_account_id)
        if payload.proforma_invoice_id is not None:
            from app.erp.proforma_invoices.service import ProformaInvoiceService

            await ProformaInvoiceService(self.session).get(tenant_id, payload.proforma_invoice_id)
        if payload.sales_order_id is not None:
            from app.erp.sales_orders.service import SalesOrderService

            await SalesOrderService(self.session).get(tenant_id, payload.sales_order_id)
        if payload.tax_id is not None:
            await self.taxes.get(tenant_id, payload.tax_id)
        allocated = quantize_money(sum((item.amount for item in payload.allocations), _ZERO))
        if allocated > payload.amount_received:
            raise PaymentOverAllocatedError(
                details={
                    "amount_received": str(payload.amount_received),
                    "allocated": str(allocated),
                }
            )
        return {
            "payment_date": payment_date,
            "customer_id": payload.customer_id,
            "currency_id": currency_id,
            "base_currency_id": base.id,
            "exchange_rate": rate,
            "amount_received": quantize_money(payload.amount_received),
            "bank_charges": quantize_money(payload.bank_charges),
            "amount_unapplied": quantize_money(payload.amount_received - allocated),
            "payment_account_id": payload.payment_account_id,
            "payment_method": payload.payment_method.value,
            "reference": payload.reference,
            "proforma_invoice_id": payload.proforma_invoice_id,
            "sales_order_id": payload.sales_order_id,
            "tax_id": payload.tax_id,
            "notes": payload.notes,
        }

    async def _merged_create(
        self, row: CustomerPayment, payload: CustomerPaymentUpdate
    ) -> CustomerPaymentCreate:
        allocations = payload.allocations
        if allocations is None:
            live = await self.allocations.list_live_for_payment(
                row.tenant_id, PaymentAllocationSource.CUSTOMER_PAYMENT.value, row.id
            )
            allocations = [
                PaymentAllocationInput(
                    item_type=OpenItemType(item.item_type),
                    item_id=item.item_id,
                    amount=item.amount,
                )
                for item in live
            ]
        return CustomerPaymentCreate(
            customer_id=row.customer_id,
            payment_date=payload.payment_date or row.payment_date,
            currency_id=payload.currency_id or row.currency_id,
            amount_received=payload.amount_received or row.amount_received,
            bank_charges=row.bank_charges if payload.bank_charges is None else payload.bank_charges,
            payment_account_id=payload.payment_account_id or row.payment_account_id,
            payment_method=payload.payment_method or PaymentMethod(row.payment_method),
            reference=row.reference if payload.reference is None else payload.reference,
            proforma_invoice_id=(
                row.proforma_invoice_id
                if "proforma_invoice_id" not in payload.model_fields_set
                else payload.proforma_invoice_id
            ),
            sales_order_id=(
                row.sales_order_id
                if "sales_order_id" not in payload.model_fields_set
                else payload.sales_order_id
            ),
            tax_id=row.tax_id if "tax_id" not in payload.model_fields_set else payload.tax_id,
            notes=row.notes if payload.notes is None else payload.notes,
            allocations=allocations,
        )

    async def _replace_draft_allocations(
        self,
        tenant_id: UUID,
        row: CustomerPayment,
        allocations: Sequence[PaymentAllocationInput],
    ) -> None:
        await self.allocations.delete_live_for_payment(
            tenant_id, PaymentAllocationSource.CUSTOMER_PAYMENT.value, row.id
        )
        seen: set[tuple[str, UUID]] = set()
        for item in allocations:
            if item.item_type not in _ALLOCATABLE:
                raise ValidationError("Invalid allocation item type")
            key = (item.item_type.value, item.item_id)
            if key in seen:
                raise ValidationError("Duplicate allocation row")
            seen.add(key)
            open_row = await self._require_open_item(tenant_id, row.customer_id, item)
            if item.amount > open_row.balance:
                raise PaymentOverAllocatedError(
                    details={"item_id": str(item.item_id), "balance": str(open_row.balance)}
                )
            await self.allocations.create(
                tenant_id,
                payment_type=PaymentAllocationSource.CUSTOMER_PAYMENT.value,
                payment_id=row.id,
                item_type=item.item_type.value,
                item_id=item.item_id,
                amount=item.amount,
            )

    async def _require_open_item(
        self, tenant_id: UUID, customer_id: UUID, item: PaymentAllocationInput
    ) -> Any:
        for row in await self.open_items.list_ar_open_items(tenant_id, customer_id):
            if row.item_type == item.item_type and row.document_id == item.item_id:
                return row
        raise PaymentOverAllocatedError(details={"item_id": str(item.item_id)})

    async def _require_payment_account(self, tenant_id: UUID, account_id: UUID) -> None:
        account = await self.accounts.require_postable(tenant_id, account_id)
        if account.account_subtype not in {AccountSubtype.CASH.value, AccountSubtype.BANK.value}:
            raise PaymentAccountInvalidError(
                details={"account_id": str(account_id), "account_subtype": account.account_subtype}
            )

    async def _apply_rate(self, tenant_id: UUID, row: CustomerPayment) -> None:
        base = await self.currencies.get_base(tenant_id)
        row.base_currency_id = base.id
        row.exchange_rate = (
            await self.fx.resolve(
                tenant_id,
                from_currency_id=row.currency_id,
                to_currency_id=base.id,
                on_date=row.payment_date,
            )
        ).rate

    async def _related_documents(
        self, tenant_id: UUID, row: CustomerPayment
    ) -> list[RelatedDocumentRef]:
        related: list[RelatedDocumentRef] = []
        if row.proforma_invoice_id is not None:
            from app.erp.proforma_invoices.repository import ProformaInvoiceRepository

            pfi = await ProformaInvoiceRepository(self.session).get(
                tenant_id, row.proforma_invoice_id
            )
            if pfi is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.PROFORMA_INVOICE.value,
                        document_id=pfi.id,
                        document_number=pfi.document_number,
                        status=pfi.status,
                        relationship="source",
                        document_date=pfi.proforma_date,
                    )
                )
        if row.sales_order_id is not None:
            from app.erp.sales_orders.repository import SalesOrderRepository

            order = await SalesOrderRepository(self.session).get(tenant_id, row.sales_order_id)
            if order is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.SALES_ORDER.value,
                        document_id=order.id,
                        document_number=order.document_number,
                        status=order.status,
                        relationship="source",
                        document_date=order.order_date,
                    )
                )
        live = await self.allocations.list_live_for_payment(
            tenant_id, PaymentAllocationSource.CUSTOMER_PAYMENT.value, row.id
        )
        from app.erp.sales_invoices.repository import SalesInvoiceRepository

        si_repo = SalesInvoiceRepository(self.session)
        for allocation in live:
            if allocation.item_type != OpenItemType.SALES_INVOICE.value:
                continue
            invoice = await si_repo.get(tenant_id, allocation.item_id)
            if invoice is None:
                continue
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.SALES_INVOICE.value,
                    document_id=invoice.id,
                    document_number=invoice.document_number,
                    status=invoice.status,
                    relationship="child",
                    document_date=invoice.invoice_date,
                    amount_summary=str(allocation.amount),
                )
            )
        return related

    def _available_actions(
        self, row: CustomerPayment, status: InvoiceDocumentStatus, *, period_locked: bool
    ) -> list[str]:
        actions: list[str] = []
        for action in transition_actions(status):
            if action in {"post", "cancel"} and period_locked:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == InvoiceDocumentStatus.DRAFT and has_permission(
            self.actor_permissions, CUSTOMER_PAYMENT_DELETE
        ):
            actions.append("delete")
        if (
            status == InvoiceDocumentStatus.POSTED
            and row.amount_unapplied > _ZERO
            and has_permission(self.actor_permissions, CUSTOMER_PAYMENT_POST)
        ):
            actions.append("allocate")
            actions.append("refund")
        return actions

    async def _to_response(
        self, tenant_id: UUID, row: CustomerPayment
    ) -> CustomerPaymentResponse:
        status = InvoiceDocumentStatus(row.status)
        period_locked = self._date_in_locked_period(row.payment_date)
        live = await self.allocations.list_live_for_payment(
            tenant_id, PaymentAllocationSource.CUSTOMER_PAYMENT.value, row.id
        )
        return CustomerPaymentResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            display_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=row.is_posted,
            payment_date=row.payment_date,
            document_date=row.payment_date,
            customer_id=row.customer_id,
            currency_id=row.currency_id,
            base_currency_id=row.base_currency_id,
            exchange_rate=row.exchange_rate,
            amount_received=row.amount_received,
            bank_charges=row.bank_charges,
            amount_unapplied=row.amount_unapplied,
            amount_refunded=row.amount_refunded,
            payment_account_id=row.payment_account_id,
            payment_method=PaymentMethod(row.payment_method),
            reference=row.reference,
            proforma_invoice_id=row.proforma_invoice_id,
            sales_order_id=row.sales_order_id,
            journal_entry_id=row.journal_entry_id,
            reversal_journal_entry_id=row.reversal_journal_entry_id,
            refund_journal_entry_id=row.refund_journal_entry_id,
            tax_id=row.tax_id,
            tax_amount=row.tax_amount,
            notes=row.notes,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            refunded_at=row.refunded_at,
            refunded_by=row.refunded_by,
            available_actions=self._available_actions(row, status, period_locked=period_locked),
            related_documents=[],
            allocations=[
                CustomerPaymentAllocationResponse(
                    item_type=item.item_type,
                    item_id=item.item_id,
                    amount=item.amount,
                    journal_entry_id=item.journal_entry_id,
                )
                for item in live
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _snapshot(self, tenant_id: UUID, row: CustomerPayment) -> dict[str, object]:
        customer = await self.customers.get(tenant_id, row.customer_id)
        return {
            "document_number": row.document_number,
            "payment_date": str(row.payment_date),
            "customer": customer.name,
            "amount_received": str(row.amount_received),
            "bank_charges": str(row.bank_charges),
            "amount_unapplied": str(row.amount_unapplied),
            "payment_method": row.payment_method,
            "reference": row.reference,
            "status": row.status,
            "version": row.version,
        }

    async def _require(
        self, tenant_id: UUID, payment_id: UUID, *, for_update: bool = False
    ) -> CustomerPayment:
        row = await self.repo.get(tenant_id, payment_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Customer payment not found")
        return row

    async def _today(self, tenant_id: UUID) -> date:
        return today_in_timezone(await self.org.get_timezone(tenant_id))

    def _assert_version(self, row: CustomerPayment, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _ensure_policy(self, tenant_id: UUID) -> PeriodLockPolicy:
        if self._period_policy is None:
            _, self._period_policy = await self.org.get_inventory_controls(tenant_id)
        return self._period_policy

    def _date_in_locked_period(self, value: date) -> bool:
        if self._period_policy is None:
            return False
        return self._period_policy.is_locked(value, can_override=self._can_override)
