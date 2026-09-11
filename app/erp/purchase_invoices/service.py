"""Purchase invoice compose, post, void-by-reversal, and GRNI/PPV snapshot."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    ERP_MODULE,
    PERIOD_OVERRIDE,
    PURCHASE_INVOICE_CANCEL,
    PURCHASE_INVOICE_DELETE,
    PURCHASE_INVOICE_POST,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.registries.purchase_invoice_dependents import registered_probes
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
    place_of_supply_from_address,
    resolve_line_tax_category,
)
from app.common.utils.due_date import due_date_from_terms
from app.core.enums import (
    AccountSystemRole,
    AuditAction,
    BillType,
    DiscountType,
    DocumentType,
    ExpenseCategory,
    InvoiceDocumentStatus,
    JournalType,
    PartyType,
    PaymentStatus,
    PlaceOfSupply,
    PurchaseInvoiceLineType,
    PurchaseOrderStatus,
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
from app.crm.contacts.service import ContactService
from app.db.session import transaction
from app.erp.accounting.accounts.models import Account
from app.erp.accounting.accounts.service import AccountResolver, AccountService
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.inventory_posting import SOURCE_GOODS_RECEIPT
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.schemas import JournalEntryResponse, JournalLineInput
from app.erp.accounting.ledger.service import JournalEntryService
from app.erp.accounting.service import DocumentSequenceService, PaymentTermService, TaxService
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService
from app.erp.purchase_invoices.models import PurchaseInvoice, PurchaseInvoiceLine
from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository
from app.erp.purchase_invoices.schemas import (
    PurchaseInvoiceCreate,
    PurchaseInvoiceCreateFromGoodsReceipt,
    PurchaseInvoiceCreateFromPurchaseOrder,
    PurchaseInvoiceLineInput,
    PurchaseInvoiceLineResponse,
    PurchaseInvoiceResponse,
    PurchaseInvoiceUpdate,
)
from app.erp.purchase_invoices.workflow import assert_editable, next_status, transition_actions
from app.erp.purchase_orders.service import PurchaseOrderService
from app.erp.suppliers.service import SupplierService
from app.inventory_management.costing.models import StockCostLayer
from app.inventory_management.costing.service import CostingService
from app.inventory_management.goods_receipts.service import GoodsReceiptService
from app.inventory_management.products.service import ProductService
from app.inventory_management.units.service import UnitService

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_SERIES = "BILL"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": PURCHASE_INVOICE_POST,
    "cancel": PURCHASE_INVOICE_CANCEL,
}
SOURCE_PURCHASE_INVOICE = "purchase_invoice"


class PurchaseInvoiceService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = PurchaseInvoiceRepository(session)
        self.org = OrganizationService(session)
        self.suppliers = SupplierService(session)
        self.contacts = ContactService(session)
        self.products = ProductService(session)
        self.units = UnitService(session)
        self.taxes = TaxService(session)
        self.payment_terms = PaymentTermService(session)
        self.currencies = CurrencyService(session)
        self.fx = ExchangeRateService(session)
        self.sequences = DocumentSequenceService(session)
        self.accounts = AccountService(session)
        self.resolver = AccountResolver(session)
        self.posting = LedgerPostingService(session, actor_permissions=actor_permissions)
        self.journals = JournalEntryService(session, actor_permissions=actor_permissions)
        self.purchase_orders = PurchaseOrderService(session, actor_permissions=actor_permissions)
        self.goods_receipts = GoodsReceiptService(session, actor_permissions=actor_permissions)
        self.costing = CostingService(session)
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
        purchase_order_id: UUID | None = None,
        goods_receipt_id: UUID | None = None,
        bill_type: str | None = None,
        payment_status: str | None = None,
        invoice_date_from: date | None = None,
        invoice_date_to: date | None = None,
    ) -> tuple[list[PurchaseInvoiceResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if supplier_id is not None:
            filters["supplier_id"] = supplier_id
        if purchase_order_id is not None:
            filters["purchase_order_id"] = purchase_order_id
        if goods_receipt_id is not None:
            filters["goods_receipt_id"] = goods_receipt_id
        if bill_type is not None:
            filters["bill_type"] = bill_type
        if payment_status is not None:
            filters["payment_status"] = payment_status
        extra: list[Any] = []
        if invoice_date_from is not None:
            extra.append(PurchaseInvoice.invoice_date >= invoice_date_from)
        if invoice_date_to is not None:
            extra.append(PurchaseInvoice.invoice_date <= invoice_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        today = await self._today(tenant_id)
        return [self._to_response(row, today=today) for row in rows], total

    async def get(self, tenant_id: UUID, invoice_id: UUID) -> PurchaseInvoiceResponse:
        row = await self._require(tenant_id, invoice_id)
        await self._ensure_policy(tenant_id)
        response = self._to_response(row, today=await self._today(tenant_id))
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def create(
        self, tenant_id: UUID, payload: PurchaseInvoiceCreate, *, actor_user_id: UUID
    ) -> PurchaseInvoiceResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            invoice_date = cast(date, header["invoice_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(invoice_date, can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.PURCHASE_INVOICE,
                series=_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, invoice_date),
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
                entity_type="purchase_invoice",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def create_from_purchase_order(
        self,
        tenant_id: UUID,
        payload: PurchaseInvoiceCreateFromPurchaseOrder,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> PurchaseInvoiceResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return PurchaseInvoiceResponse.model_validate(replay)
            order = await self.purchase_orders.get(tenant_id, payload.purchase_order_id)
            if order.status != PurchaseOrderStatus.ISSUED:
                raise ValidationError(
                    "Purchase invoices can only be created from an issued purchase order"
                )
            lines: list[PurchaseInvoiceLineInput] = []
            for line in order.lines:
                outstanding = quantize_quantity(line.quantity - line.qty_billed)
                if outstanding <= _ZERO:
                    continue
                lines.append(
                    PurchaseInvoiceLineInput(
                        line_type=PurchaseInvoiceLineType.PRODUCT,
                        product_id=line.product_id,
                        description=line.description,
                        quantity=outstanding,
                        unit_id=line.unit_id,
                        rate=line.rate,
                        purchase_order_line_id=line.id,
                        supplier_product_id=line.supplier_product_id,
                        supplier_sku=line.supplier_sku,
                        discount_type=line.discount_type,
                        discount_value=line.discount_value,
                        tax_id=line.tax_id,
                    )
                )
            if not lines:
                raise ValidationError("This purchase order has no remaining quantity to bill")
            create_payload = PurchaseInvoiceCreate(
                supplier_id=order.supplier_id,
                contact_id=order.contact_id,
                branch_id=order.branch_id,
                invoice_date=payload.invoice_date,
                purchase_order_id=order.id,
                payment_terms_id=order.payment_terms_id,
                currency_id=order.currency_id,
                notes=payload.notes or order.notes,
                discount_type=order.discount_type,
                discount_value=order.discount_value,
                shipping_amount=order.shipping_amount,
                adjustment_amount=order.adjustment_amount,
                place_of_supply=order.place_of_supply,
                lines=lines,
            )
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            invoice_date = cast(date, header["invoice_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(invoice_date, can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.PURCHASE_INVOICE,
                series=_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, invoice_date),
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
                entity_type="purchase_invoice",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def create_from_goods_receipt(
        self,
        tenant_id: UUID,
        payload: PurchaseInvoiceCreateFromGoodsReceipt,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> PurchaseInvoiceResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return PurchaseInvoiceResponse.model_validate(replay)
            receipt = await self.goods_receipts._require(tenant_id, payload.goods_receipt_id)
            if StockDocumentStatus(receipt.status) != StockDocumentStatus.POSTED:
                raise ValidationError(
                    "Purchase invoices can only be created from a posted goods receipt"
                )
            lines: list[PurchaseInvoiceLineInput] = []
            for line in receipt.lines:
                outstanding = quantize_quantity(line.quantity - line.qty_billed)
                if outstanding <= _ZERO:
                    continue
                lines.append(
                    PurchaseInvoiceLineInput(
                        line_type=PurchaseInvoiceLineType.PRODUCT,
                        product_id=line.product_id,
                        description=line.description,
                        quantity=outstanding,
                        unit_id=line.unit_id,
                        rate=line.rate,
                        purchase_order_line_id=line.purchase_order_line_id,
                        goods_receipt_id=receipt.id,
                        goods_receipt_line_id=line.id,
                        supplier_product_id=line.supplier_product_id,
                        supplier_sku=line.supplier_sku,
                    )
                )
            if not lines:
                raise ValidationError("This goods receipt has no remaining quantity to bill")
            order = (
                await self.purchase_orders.get(tenant_id, receipt.purchase_order_id)
                if receipt.purchase_order_id is not None
                else None
            )
            create_payload = PurchaseInvoiceCreate(
                supplier_id=receipt.supplier_id,
                contact_id=order.contact_id if order is not None else None,
                branch_id=receipt.branch_id or (order.branch_id if order is not None else None),
                invoice_date=payload.invoice_date,
                purchase_order_id=receipt.purchase_order_id,
                goods_receipt_id=receipt.id,
                supplier_invoice_number=receipt.supplier_invoice_number,
                payment_terms_id=order.payment_terms_id if order is not None else None,
                currency_id=receipt.currency_id,
                notes=payload.notes,
                discount_type=order.discount_type if order is not None else None,
                discount_value=order.discount_value if order is not None else None,
                shipping_amount=order.shipping_amount if order is not None else _ZERO,
                adjustment_amount=order.adjustment_amount if order is not None else _ZERO,
                place_of_supply=PlaceOfSupply(receipt.place_of_supply),
                lines=lines,
            )
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            invoice_date = cast(date, header["invoice_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(invoice_date, can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.PURCHASE_INVOICE,
                series=_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, invoice_date),
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
                entity_type="purchase_invoice",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def update(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        payload: PurchaseInvoiceUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PurchaseInvoiceResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, invoice_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(InvoiceDocumentStatus(row.status))
            old_values = await self._snapshot(tenant_id, row)
            create_payload = await self._update_to_create(row, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            invoice_date = cast(date, header["invoice_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(invoice_date, can_override=self._can_override)
            for name, value in header.items():
                setattr(row, name, value)
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, invoice_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ERP_MODULE,
                entity_type="purchase_invoice",
                entity_id=invoice_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PurchaseInvoiceResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, invoice_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(InvoiceDocumentStatus(row.status))
            old_values = await self._snapshot(tenant_id, row)
            response = self._to_response(row)
            deleted = await self.repo.soft_delete(tenant_id, invoice_id)
            if deleted is None:
                raise ResourceNotFoundError("Purchase invoice not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="purchase_invoice",
                entity_id=invoice_id,
                old_values=old_values,
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> PurchaseInvoiceResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return PurchaseInvoiceResponse.model_validate(replay)
            row = await self._require(tenant_id, invoice_id, for_update=True)
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
            policy.assert_open(row.invoice_date, can_override=self._can_override)
            old_values = await self._snapshot(tenant_id, row)
            await self._assert_qty_headroom(tenant_id, row)
            await self._recompute_posted_totals(tenant_id, row)
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_PURCHASE_INVOICE,
                source_id=row.id,
                entry_date=row.invoice_date,
                lines=await self._journal_lines(tenant_id, row),
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                narration=f"Purchase invoice {row.document_number}",
                branch_id=row.branch_id,
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
                reference=row.document_number,
            )
            row.journal_entry_id = journal.id
            await self._apply_source_quantities(tenant_id, row, sign=Decimal("1"))
            row.status = target.value
            row.is_posted = True
            row.posted_at = utcnow()
            row.posted_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, invoice_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=ERP_MODULE,
                entity_type="purchase_invoice",
                entity_id=invoice_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="erp.purchase_invoice.posted",
                aggregate_type="purchase_invoice",
                aggregate_id=invoice_id,
                payload={"purchase_invoice_id": str(invoice_id)},
                dedupe_key=f"purchase-invoice-posted:{invoice_id}",
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        invoice_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        endpoint: str | None = None,
    ) -> PurchaseInvoiceResponse:
        async with transaction(self.session):
            if idempotency_key and request_hash and endpoint:
                replay = await self.idempotency.begin(
                    tenant_id, idempotency_key, request_hash, endpoint=endpoint
                )
                if replay is not None:
                    return PurchaseInvoiceResponse.model_validate(replay)
            row = await self._require(tenant_id, invoice_id, for_update=True)
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
                entity_type="purchase_invoice",
                entity_id=invoice_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            if current == InvoiceDocumentStatus.POSTED:
                await self.outbox.enqueue(
                    tenant_id,
                    event_type="erp.purchase_invoice.cancelled",
                    aggregate_type="purchase_invoice",
                    aggregate_id=invoice_id,
                    payload={"purchase_invoice_id": str(invoice_id)},
                    dedupe_key=f"purchase-invoice-cancelled:{invoice_id}",
                )
            response = self._to_response(row)
            if idempotency_key and request_hash and endpoint:
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
            return response

    async def journal(self, tenant_id: UUID, invoice_id: UUID) -> JournalEntryResponse:
        row = await self._require(tenant_id, invoice_id)
        if row.journal_entry_id is None:
            raise ResourceNotFoundError("Purchase invoice has no journal entry")
        return await self.journals.get(tenant_id, row.journal_entry_id)

    async def has_live_for_goods_receipt(self, tenant_id: UUID, goods_receipt_id: UUID) -> bool:
        return await self.repo.has_live_for_goods_receipt(tenant_id, goods_receipt_id)

    async def apply_debit(
        self, tenant_id: UUID, invoice_id: UUID, amount: Decimal
    ) -> PurchaseInvoice:
        """Caller owns the transaction. Amount may be negative to reverse a debit note."""

        row = await self._require(tenant_id, invoice_id, for_update=True)
        row.amount_debited = quantize_money(row.amount_debited + amount)
        if row.amount_debited < _ZERO:
            raise ValidationError("Debited amount cannot be negative")
        self._refresh_payment_status(row)
        await self.session.flush()
        return row

    async def _cancel_posted(
        self, tenant_id: UUID, row: PurchaseInvoice, *, actor_user_id: UUID
    ) -> None:
        policy = await self._ensure_policy(tenant_id)
        if policy.is_locked(row.invoice_date, can_override=self._can_override):
            raise InvoiceCannotVoidError("The period is locked")
        if row.amount_paid > _ZERO:
            raise InvoiceCannotVoidError("This invoice has payments and cannot be voided")
        if row.amount_debited > _ZERO:
            raise InvoiceCannotVoidError("This invoice has debit notes and cannot be voided")
        for probe in registered_probes():
            if await probe(self.session, tenant_id, row.id):
                raise InvoiceCannotVoidError(
                    "This invoice has dependent documents and cannot be voided"
                )
        if row.journal_entry_id is not None:
            reversal = await self.posting.reverse(
                tenant_id,
                row.journal_entry_id,
                reversal_date=row.invoice_date,
                reason=row.cancel_reason,
                actor_id=actor_user_id,
            )
            row.reversal_journal_entry_id = reversal.id
        await self._restore_grn_layer_costs(tenant_id, row)
        await self._apply_source_quantities(tenant_id, row, sign=Decimal("-1"))
        row.is_posted = False

    async def _restore_grn_layer_costs(self, tenant_id: UUID, row: PurchaseInvoice) -> None:
        for line in row.lines:
            if line.goods_receipt_id is None or line.goods_receipt_line_id is None:
                continue
            layers = await self.costing.layers_for_source(
                tenant_id,
                SOURCE_GOODS_RECEIPT,
                line.goods_receipt_id,
                source_line_id=line.goods_receipt_line_id,
            )
            for layer in layers:
                if layer.qty_remaining > _ZERO:
                    await self.costing.revalue(tenant_id, layer.id, line.grn_unit_cost)

    async def _assert_qty_headroom(self, tenant_id: UUID, row: PurchaseInvoice) -> None:
        po_remaining: dict[UUID, Decimal] = {}
        if row.purchase_order_id is not None:
            order = await self.purchase_orders._require(
                tenant_id, row.purchase_order_id, for_update=True
            )
            po_remaining = {
                line.id: quantize_quantity(line.quantity - line.qty_billed) for line in order.lines
            }
        grn_remaining: dict[UUID, Decimal] = {}
        grn_ids = {line.goods_receipt_id for line in row.lines if line.goods_receipt_id is not None}
        for receipt_id in grn_ids:
            receipt = await self.goods_receipts._require(tenant_id, receipt_id, for_update=True)
            for line in receipt.lines:
                grn_remaining[line.id] = quantize_quantity(line.quantity - line.qty_billed)
        for line in row.lines:
            if line.goods_receipt_line_id is not None:
                remaining = grn_remaining.get(line.goods_receipt_line_id, _ZERO)
                if line.quantity > remaining:
                    raise InvoiceQtyExceededError(
                        details={
                            "goods_receipt_line_id": str(line.goods_receipt_line_id),
                            "quantity": str(line.quantity),
                            "outstanding": str(remaining),
                        }
                    )
                grn_remaining[line.goods_receipt_line_id] = quantize_quantity(
                    remaining - line.quantity
                )
            if line.purchase_order_line_id is not None:
                if line.purchase_order_line_id not in po_remaining:
                    order_id = await self._purchase_order_id_for_line(
                        tenant_id, line.purchase_order_line_id
                    )
                    order = await self.purchase_orders._require(
                        tenant_id, order_id, for_update=True
                    )
                    for po_line in order.lines:
                        po_remaining.setdefault(
                            po_line.id, quantize_quantity(po_line.quantity - po_line.qty_billed)
                        )
                remaining = po_remaining.get(line.purchase_order_line_id, _ZERO)
                if line.quantity > remaining:
                    raise InvoiceQtyExceededError(
                        details={
                            "purchase_order_line_id": str(line.purchase_order_line_id),
                            "quantity": str(line.quantity),
                            "outstanding": str(remaining),
                        }
                    )
                po_remaining[line.purchase_order_line_id] = quantize_quantity(
                    remaining - line.quantity
                )

    async def _apply_source_quantities(
        self, tenant_id: UUID, row: PurchaseInvoice, *, sign: Decimal
    ) -> None:
        po_qty: dict[UUID, dict[UUID, Decimal]] = {}
        grn_qty: dict[UUID, dict[UUID, Decimal]] = {}
        for line in row.lines:
            delta = quantize_quantity(line.quantity * sign)
            if line.purchase_order_line_id is not None and row.purchase_order_id is not None:
                bucket = po_qty.setdefault(row.purchase_order_id, {})
                bucket[line.purchase_order_line_id] = (
                    bucket.get(line.purchase_order_line_id, _ZERO) + delta
                )
            elif line.purchase_order_line_id is not None:
                order_id = await self._purchase_order_id_for_line(
                    tenant_id, line.purchase_order_line_id
                )
                bucket = po_qty.setdefault(order_id, {})
                bucket[line.purchase_order_line_id] = (
                    bucket.get(line.purchase_order_line_id, _ZERO) + delta
                )
            if line.goods_receipt_id is not None and line.goods_receipt_line_id is not None:
                bucket = grn_qty.setdefault(line.goods_receipt_id, {})
                bucket[line.goods_receipt_line_id] = (
                    bucket.get(line.goods_receipt_line_id, _ZERO) + delta
                )
        for order_id, bills in po_qty.items():
            await self.purchase_orders.apply_line_bills(tenant_id, order_id, bills)
        for receipt_id, bills in grn_qty.items():
            await self.goods_receipts.apply_line_bills(tenant_id, receipt_id, bills)

    async def _purchase_order_id_for_line(
        self, tenant_id: UUID, purchase_order_line_id: UUID
    ) -> UUID:
        from app.erp.purchase_orders.models import PurchaseOrderLine

        line = await self.session.get(PurchaseOrderLine, purchase_order_line_id)
        if line is None or line.tenant_id != tenant_id:
            raise ValidationError("Purchase order line not found")
        return line.purchase_order_id

    async def _recompute_posted_totals(self, tenant_id: UUID, row: PurchaseInvoice) -> None:
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
        self, tenant_id: UUID, row: PurchaseInvoice
    ) -> list[JournalLineInput]:
        ap = await self.accounts.party_resolver.resolve_payable(tenant_id, row.supplier_id)
        grni = await self.resolver.require(tenant_id, AccountSystemRole.GOODS_RECEIVED_NOT_INVOICED)
        inventory = await self.resolver.require(tenant_id, AccountSystemRole.INVENTORY)
        ppv = await self.resolver.require(tenant_id, AccountSystemRole.PURCHASE_PRICE_VARIANCE)
        vat_input = await self.resolver.require(tenant_id, AccountSystemRole.VAT_INPUT)
        vat_rcm_input = await self.resolver.require(tenant_id, AccountSystemRole.VAT_RCM_INPUT)
        vat_rcm_output = await self.resolver.require(tenant_id, AccountSystemRole.VAT_RCM_OUTPUT)
        freight_in = await self.resolver.require(tenant_id, AccountSystemRole.FREIGHT_IN)
        other = await self.resolver.require(tenant_id, AccountSystemRole.OTHER_CHARGES)
        round_off = await self.resolver.require(tenant_id, AccountSystemRole.ROUND_OFF)
        default_purchase = await self.resolver.require(tenant_id, AccountSystemRole.PURCHASES)
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
            line_type = PurchaseInvoiceLineType(line.line_type)
            if (
                line_type == PurchaseInvoiceLineType.PRODUCT
                and line.goods_receipt_id is not None
                and line.goods_receipt_line_id is not None
            ):
                lines.extend(
                    await self._grn_product_journal_lines(
                        tenant_id,
                        line,
                        net_amount=net_amount,
                        grni_id=grni.id,
                        inventory_id=inventory.id,
                        ppv_id=ppv.id,
                    )
                )
            elif line_type == PurchaseInvoiceLineType.EXPENSE:
                account = await self._resolve_expense_account(tenant_id, line)
                line.expense_account_id = account.id
                if net_amount != _ZERO:
                    lines.append(
                        _signed_line(
                            account.id,
                            net_amount,
                            debit_positive=True,
                            description=line.description,
                        )
                    )
            else:
                if line.product_id is not None:
                    purchase = await self.accounts.resolve_purchase_account(
                        tenant_id, line.product_id
                    )
                else:
                    purchase = default_purchase
                line.purchase_account_id = purchase.id
                if net_amount != _ZERO:
                    lines.append(
                        _signed_line(
                            purchase.id,
                            net_amount,
                            debit_positive=True,
                            description=line.description,
                        )
                    )
        if row.is_reverse_charge:
            if row.rcm_tax_amount > _ZERO:
                lines.append(
                    JournalLineInput(
                        account_id=vat_rcm_input.id,
                        debit=row.rcm_tax_amount,
                        description="VAT RCM input",
                    )
                )
                lines.append(
                    JournalLineInput(
                        account_id=vat_rcm_output.id,
                        credit=row.rcm_tax_amount,
                        description="VAT RCM output",
                    )
                )
        elif row.tax_amount > _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=vat_input.id,
                    debit=row.tax_amount,
                    description="VAT input",
                )
            )
        if row.shipping_amount != _ZERO:
            lines.append(
                _signed_line(
                    freight_in.id,
                    row.shipping_amount,
                    debit_positive=True,
                    description="Freight in",
                )
            )
        if row.adjustment_amount != _ZERO:
            lines.append(
                _signed_line(
                    other.id,
                    row.adjustment_amount,
                    debit_positive=True,
                    description="Other charges",
                )
            )
        if row.round_off_amount != _ZERO:
            lines.append(
                _signed_line(
                    round_off.id,
                    row.round_off_amount,
                    debit_positive=True,
                    description="Round off",
                )
            )
        if row.grand_total != _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=ap.id,
                    credit=row.grand_total if row.grand_total > _ZERO else _ZERO,
                    debit=-row.grand_total if row.grand_total < _ZERO else _ZERO,
                    party_type=PartyType.SUPPLIER,
                    party_id=row.supplier_id,
                    due_date=row.due_date,
                    external_reference=row.document_number,
                    description=f"AP {row.document_number}",
                )
            )
        return lines

    async def _grn_product_journal_lines(
        self,
        tenant_id: UUID,
        line: PurchaseInvoiceLine,
        *,
        net_amount: Decimal,
        grni_id: UUID,
        inventory_id: UUID,
        ppv_id: UUID,
    ) -> list[JournalLineInput]:
        receipt_id = line.goods_receipt_id
        receipt_line_id = line.goods_receipt_line_id
        if receipt_id is None or receipt_line_id is None:
            raise ValidationError("GRN-linked product lines require goods_receipt_id and line id")
        layers = await self.costing.layers_for_source(
            tenant_id,
            SOURCE_GOODS_RECEIPT,
            receipt_id,
            source_line_id=receipt_line_id,
        )
        fallback = await self._grn_line_rate(
            tenant_id, receipt_id, receipt_line_id, default=line.rate
        )
        grn_unit_cost = _weighted_landed_unit_cost(layers, fallback)
        line.grn_unit_cost = grn_unit_cost
        billed_qty = line.quantity
        bill_unit = quantize_money(net_amount / billed_qty) if billed_qty else _ZERO
        qty_remaining = quantize_quantity(sum((layer.qty_remaining for layer in layers), _ZERO))
        qty_received = quantize_quantity(sum((layer.qty_received for layer in layers), _ZERO))
        qty_consumed = quantize_quantity(max(qty_received - qty_remaining, _ZERO))
        qty_to_remaining = min(billed_qty, max(qty_remaining, _ZERO))
        leftover = quantize_quantity(billed_qty - qty_to_remaining)
        qty_to_consumed = min(leftover, qty_consumed) if qty_consumed > _ZERO else leftover
        for layer in layers:
            if layer.qty_remaining > _ZERO:
                await self.costing.revalue(tenant_id, layer.id, bill_unit)
        grni_amount = quantize_money(grn_unit_cost * billed_qty)
        variance = quantize_money(net_amount - grni_amount)
        if billed_qty <= _ZERO or variance == _ZERO:
            inv_amount = _ZERO
            ppv_amount = _ZERO
        elif qty_to_consumed == _ZERO:
            inv_amount = variance
            ppv_amount = _ZERO
        elif qty_to_remaining == _ZERO:
            inv_amount = _ZERO
            ppv_amount = variance
        else:
            inv_amount = quantize_money(variance * qty_to_remaining / billed_qty)
            ppv_amount = quantize_money(variance - inv_amount)
        built: list[JournalLineInput] = []
        if grni_amount != _ZERO:
            built.append(
                _signed_line(
                    grni_id, grni_amount, debit_positive=True, description=line.description
                )
            )
        if inv_amount != _ZERO:
            built.append(
                _signed_line(
                    inventory_id,
                    inv_amount,
                    debit_positive=True,
                    description="Inventory revaluation",
                )
            )
        if ppv_amount != _ZERO:
            built.append(
                _signed_line(
                    ppv_id,
                    ppv_amount,
                    debit_positive=True,
                    description="Purchase price variance",
                )
            )
        return built

    async def _grn_line_rate(
        self,
        tenant_id: UUID,
        goods_receipt_id: UUID,
        goods_receipt_line_id: UUID,
        *,
        default: Decimal,
    ) -> Decimal:
        receipt = await self.goods_receipts._require(tenant_id, goods_receipt_id)
        grn_line = next(
            (item for item in receipt.lines if item.id == goods_receipt_line_id), None
        )
        if grn_line is None:
            return quantize_money(default)
        return quantize_money(grn_line.rate)

    async def _resolve_expense_account(
        self, tenant_id: UUID, line: PurchaseInvoiceLine
    ) -> Account:
        category = ExpenseCategory(line.expense_category) if line.expense_category else None
        if category == ExpenseCategory.FREIGHT:
            return await self.resolver.require(tenant_id, AccountSystemRole.FREIGHT_IN)
        if category == ExpenseCategory.CUSTOMS_DUTY:
            return await self.resolver.require(tenant_id, AccountSystemRole.CUSTOMS_DUTY)
        if line.expense_account_id is None:
            raise ValidationError("Expense lines require expense_account_id")
        return await self.accounts.require_postable(tenant_id, line.expense_account_id)

    def _header_discount_share(self, row: PurchaseInvoice, line: PurchaseInvoiceLine) -> Decimal:
        if row.subtotal <= _ZERO or row.discount_amount == _ZERO:
            return quantize_money(_ZERO)
        return quantize_money(row.discount_amount * line.amount / row.subtotal)

    async def _build_draft(
        self, tenant_id: UUID, payload: PurchaseInvoiceCreate
    ) -> tuple[dict[str, object], builtins.list[dict[str, object]]]:
        supplier = await self.suppliers.get(tenant_id, payload.supplier_id)
        if payload.branch_id is not None:
            await self.org.require_branch(tenant_id, payload.branch_id)
        if payload.contact_id is not None:
            contact = await self.contacts.get(tenant_id, payload.contact_id)
            if contact.customer_id != supplier.id:
                raise ValidationError("Contact does not belong to this supplier")
        payment_terms_id = payload.payment_terms_id or supplier.payment_terms_id
        if payment_terms_id is not None:
            await self.payment_terms.require_id(tenant_id, payment_terms_id)
        if payload.purchase_order_id is not None:
            await self.purchase_orders.get(tenant_id, payload.purchase_order_id)
        if payload.goods_receipt_id is not None:
            await self.goods_receipts._require(tenant_id, payload.goods_receipt_id)

        currency_id = payload.currency_id or supplier.currency_id
        await self.currencies.require_id(tenant_id, currency_id)
        base = await self.currencies.get_base(tenant_id)
        invoice_date = payload.invoice_date or await self._today(tenant_id)
        resolved = await self.fx.resolve(
            tenant_id,
            from_currency_id=currency_id,
            to_currency_id=base.id,
            on_date=invoice_date,
        )
        place = payload.place_of_supply or place_of_supply_from_address(
            supplier.shipping_address or supplier.billing_address
        )
        tax_treatment = TaxTreatment(supplier.tax_treatment)
        reverse_charge = _resolve_reverse_charge(payload.bill_type, payload.is_reverse_charge)
        line_rows, line_nets, line_taxes = await self._build_lines(
            tenant_id,
            payload.lines,
            tax_treatment=tax_treatment,
            place_of_supply=place,
            reverse_charge=reverse_charge,
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
        rcm_taxable = _ZERO
        rcm_tax = _ZERO
        if reverse_charge:
            rcm_taxable = quantize_money(subtotal - doc_discount)
            standard = await self.taxes.get_by_category(tenant_id, TaxCategory.STANDARD)
            rcm_tax = quantize_money(rcm_taxable * standard.rate / _HUNDRED)
        due_date = await due_date_from_terms(
            self.session, tenant_id, payment_terms_id, invoice_date
        )
        header: dict[str, object] = {
            "invoice_date": invoice_date,
            "bill_type": payload.bill_type.value,
            "supplier_id": supplier.id,
            "contact_id": payload.contact_id,
            "supplier_trn": supplier.trn,
            "branch_id": payload.branch_id,
            "purchase_order_id": payload.purchase_order_id,
            "goods_receipt_id": payload.goods_receipt_id,
            "supplier_invoice_number": payload.supplier_invoice_number,
            "supplier_invoice_date": payload.supplier_invoice_date,
            "payment_terms_id": payment_terms_id,
            "due_date": due_date,
            "tax_treatment": tax_treatment.value,
            "place_of_supply": place.value,
            "is_reverse_charge": reverse_charge,
            "rcm_taxable_amount": rcm_taxable,
            "rcm_tax_amount": rcm_tax,
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
            "amount_paid": _ZERO,
            "amount_debited": _ZERO,
            "balance_due": grand,
            "payment_status": PaymentStatus.UNPAID.value,
        }
        return header, line_rows

    async def _build_lines(
        self,
        tenant_id: UUID,
        lines: Sequence[PurchaseInvoiceLineInput],
        *,
        tax_treatment: TaxTreatment,
        place_of_supply: PlaceOfSupply,
        reverse_charge: bool,
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
                or (line.expense_category.value if line.expense_category else None)
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
            if (
                line.line_type == PurchaseInvoiceLineType.EXPENSE
                and line.expense_category
                not in {ExpenseCategory.FREIGHT, ExpenseCategory.CUSTOMS_DUTY}
                and line.expense_account_id is None
            ):
                raise ValidationError("Expense lines require expense_account_id")
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
            applied_rate = _ZERO if reverse_charge else chosen_tax.rate
            qty, line_discount, tax_amount, net = compute_line_amounts(
                quantity=line.quantity,
                rate=rate,
                discount_type=line.discount_type,
                discount_value=line.discount_value,
                tax_rate=applied_rate,
            )
            built.append(
                {
                    "line_number": index,
                    "line_type": line.line_type.value,
                    "product_id": product.id if product else None,
                    "description": description,
                    "quantity": qty,
                    "unit_id": unit_id,
                    "rate": rate,
                    "purchase_order_line_id": line.purchase_order_line_id,
                    "goods_receipt_id": line.goods_receipt_id,
                    "goods_receipt_line_id": line.goods_receipt_line_id,
                    "supplier_product_id": line.supplier_product_id,
                    "supplier_sku": line.supplier_sku,
                    "expense_account_id": line.expense_account_id,
                    "expense_category": (
                        line.expense_category.value if line.expense_category else None
                    ),
                    "discount_type": line.discount_type.value if line.discount_type else None,
                    "discount_value": line.discount_value,
                    "discount_amount": line_discount,
                    "tax_id": chosen_tax.id,
                    "tax_rate": applied_rate,
                    "tax_amount": tax_amount,
                    "amount": net,
                    "purchase_account_id": None,
                    "grn_unit_cost": _ZERO,
                    "qty_debited": _ZERO,
                }
            )
            nets.append(net)
            taxes.append(tax_amount)
        return built, nets, taxes

    async def _update_to_create(
        self, existing: PurchaseInvoice, payload: PurchaseInvoiceUpdate
    ) -> PurchaseInvoiceCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                PurchaseInvoiceLineInput(
                    line_type=PurchaseInvoiceLineType(line.line_type),
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    purchase_order_line_id=line.purchase_order_line_id,
                    goods_receipt_id=line.goods_receipt_id,
                    goods_receipt_line_id=line.goods_receipt_line_id,
                    supplier_product_id=line.supplier_product_id,
                    supplier_sku=line.supplier_sku,
                    expense_account_id=line.expense_account_id,
                    expense_category=(
                        ExpenseCategory(line.expense_category) if line.expense_category else None
                    ),
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    tax_id=line.tax_id,
                )
                for line in existing.lines
            ]
        return PurchaseInvoiceCreate(
            supplier_id=existing.supplier_id,
            bill_type=(
                values["bill_type"]
                if "bill_type" in values
                else BillType(existing.bill_type)
            ),
            contact_id=values.get("contact_id", existing.contact_id),
            branch_id=values.get("branch_id", existing.branch_id),
            invoice_date=values.get("invoice_date", existing.invoice_date),
            purchase_order_id=values.get("purchase_order_id", existing.purchase_order_id),
            goods_receipt_id=values.get("goods_receipt_id", existing.goods_receipt_id),
            supplier_invoice_number=values.get(
                "supplier_invoice_number", existing.supplier_invoice_number
            ),
            supplier_invoice_date=values.get(
                "supplier_invoice_date", existing.supplier_invoice_date
            ),
            payment_terms_id=values.get("payment_terms_id", existing.payment_terms_id),
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
            is_reverse_charge=values.get("is_reverse_charge", existing.is_reverse_charge),
            lines=lines,
        )

    async def _row_to_create(self, row: PurchaseInvoice) -> PurchaseInvoiceCreate:
        return PurchaseInvoiceCreate(
            supplier_id=row.supplier_id,
            bill_type=BillType(row.bill_type),
            contact_id=row.contact_id,
            branch_id=row.branch_id,
            invoice_date=row.invoice_date,
            purchase_order_id=row.purchase_order_id,
            goods_receipt_id=row.goods_receipt_id,
            supplier_invoice_number=row.supplier_invoice_number,
            supplier_invoice_date=row.supplier_invoice_date,
            payment_terms_id=row.payment_terms_id,
            currency_id=row.currency_id,
            notes=row.notes,
            discount_type=DiscountType(row.discount_type) if row.discount_type else None,
            discount_value=row.discount_value,
            shipping_amount=row.shipping_amount,
            adjustment_amount=row.adjustment_amount,
            round_off_amount=row.round_off_amount,
            place_of_supply=PlaceOfSupply(row.place_of_supply),
            is_reverse_charge=row.is_reverse_charge,
            lines=[
                PurchaseInvoiceLineInput(
                    line_type=PurchaseInvoiceLineType(line.line_type),
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    purchase_order_line_id=line.purchase_order_line_id,
                    goods_receipt_id=line.goods_receipt_id,
                    goods_receipt_line_id=line.goods_receipt_line_id,
                    supplier_product_id=line.supplier_product_id,
                    supplier_sku=line.supplier_sku,
                    expense_account_id=line.expense_account_id,
                    expense_category=(
                        ExpenseCategory(line.expense_category) if line.expense_category else None
                    ),
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    tax_id=line.tax_id,
                )
                for line in row.lines
            ],
        )

    def _refresh_payment_status(self, row: PurchaseInvoice) -> None:
        row.balance_due = quantize_money(row.grand_total - row.amount_paid - row.amount_debited)
        applied = quantize_money(row.amount_paid + row.amount_debited)
        if applied <= _ZERO:
            row.payment_status = PaymentStatus.UNPAID.value
        elif row.balance_due <= _ZERO:
            row.payment_status = PaymentStatus.PAID.value
        else:
            row.payment_status = PaymentStatus.PARTIALLY_PAID.value

    def _available_actions(
        self, row: PurchaseInvoice, status: InvoiceDocumentStatus, *, period_locked: bool
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
            self.actor_permissions, PURCHASE_INVOICE_DELETE
        ):
            actions.append("delete")
        return actions

    def _to_response(
        self, row: PurchaseInvoice, *, today: date | None = None
    ) -> PurchaseInvoiceResponse:
        status = InvoiceDocumentStatus(row.status)
        period_locked = self._date_in_locked_period(row.invoice_date)
        debited = row.amount_debited
        is_fully_debited = debited > _ZERO and debited >= row.grand_total
        is_partially_debited = debited > _ZERO and not is_fully_debited
        is_overdue = (
            today is not None
            and row.due_date is not None
            and row.due_date < today
            and status == InvoiceDocumentStatus.POSTED
            and row.balance_due > _ZERO
        )
        return PurchaseInvoiceResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            display_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=row.is_posted,
            invoice_date=row.invoice_date,
            document_date=row.invoice_date,
            bill_type=BillType(row.bill_type),
            supplier_id=row.supplier_id,
            contact_id=row.contact_id,
            supplier_trn=row.supplier_trn,
            branch_id=row.branch_id,
            purchase_order_id=row.purchase_order_id,
            goods_receipt_id=row.goods_receipt_id,
            supplier_invoice_number=row.supplier_invoice_number,
            supplier_invoice_date=row.supplier_invoice_date,
            payment_terms_id=row.payment_terms_id,
            due_date=row.due_date,
            tax_treatment=TaxTreatment(row.tax_treatment),
            place_of_supply=PlaceOfSupply(row.place_of_supply),
            is_reverse_charge=row.is_reverse_charge,
            rcm_taxable_amount=row.rcm_taxable_amount,
            rcm_tax_amount=row.rcm_tax_amount,
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
            amount_paid=row.amount_paid,
            amount_debited=row.amount_debited,
            balance_due=row.balance_due,
            payment_status=PaymentStatus(row.payment_status),
            journal_entry_id=row.journal_entry_id,
            reversal_journal_entry_id=row.reversal_journal_entry_id,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            is_overdue=is_overdue,
            is_partially_debited=is_partially_debited,
            is_fully_debited=is_fully_debited,
            available_actions=self._available_actions(row, status, period_locked=period_locked),
            related_documents=[],
            lines=[
                PurchaseInvoiceLineResponse(
                    id=line.id,
                    line_number=line.line_number,
                    line_type=PurchaseInvoiceLineType(line.line_type),
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    purchase_order_line_id=line.purchase_order_line_id,
                    goods_receipt_id=line.goods_receipt_id,
                    goods_receipt_line_id=line.goods_receipt_line_id,
                    supplier_product_id=line.supplier_product_id,
                    supplier_sku=line.supplier_sku,
                    expense_account_id=line.expense_account_id,
                    expense_category=(
                        ExpenseCategory(line.expense_category) if line.expense_category else None
                    ),
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    discount_amount=line.discount_amount,
                    tax_id=line.tax_id,
                    tax_rate=line.tax_rate,
                    tax_amount=line.tax_amount,
                    amount=line.amount,
                    purchase_account_id=line.purchase_account_id,
                    grn_unit_cost=line.grn_unit_cost,
                    qty_debited=line.qty_debited,
                )
                for line in row.lines
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _related_documents(
        self, tenant_id: UUID, row: PurchaseInvoice
    ) -> builtins.list[RelatedDocumentRef]:
        from app.erp.debit_notes.repository import DebitNoteRepository
        from app.erp.purchase_orders.repository import PurchaseOrderRepository
        from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository

        related: builtins.list[RelatedDocumentRef] = []
        if row.purchase_order_id is not None:
            order = await PurchaseOrderRepository(self.session).get(
                tenant_id, row.purchase_order_id
            )
            if order is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.PURCHASE_ORDER.value,
                        document_id=order.id,
                        document_number=order.document_number,
                        status=order.status,
                        relationship="source",
                        document_date=order.order_date,
                    )
                )
        if row.goods_receipt_id is not None:
            receipt = await GoodsReceiptRepository(self.session).get(
                tenant_id, row.goods_receipt_id
            )
            if receipt is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.GOODS_RECEIPT.value,
                        document_id=receipt.id,
                        document_number=receipt.document_number,
                        status=receipt.status,
                        relationship="source",
                        document_date=receipt.document_date,
                    )
                )
        for item in await DebitNoteRepository(self.session).list_for_purchase_invoice(
            tenant_id, row.id
        ):
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.DEBIT_NOTE.value,
                    document_id=item.id,
                    document_number=item.document_number,
                    status=item.status,
                    relationship="child",
                    document_date=item.debit_note_date,
                    quantity_summary=quantity_summary([line.quantity for line in item.lines]),
                )
            )
        return related

    async def _require(
        self, tenant_id: UUID, invoice_id: UUID, *, for_update: bool = False
    ) -> PurchaseInvoice:
        row = await self.repo.get(tenant_id, invoice_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Purchase invoice not found")
        return row

    async def _today(self, tenant_id: UUID) -> date:
        return today_in_timezone(await self.org.get_timezone(tenant_id))

    def _assert_version(self, row: PurchaseInvoice, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, tenant_id: UUID, row: PurchaseInvoice) -> dict[str, object]:
        supplier = await self.suppliers.get(tenant_id, row.supplier_id)
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "invoice_date": row.invoice_date.isoformat(),
            "supplier": supplier.name,
            "grand_total": str(row.grand_total),
            "tax_amount": str(row.tax_amount),
            "payment_status": row.payment_status,
            "is_reverse_charge": row.is_reverse_charge,
        }

    async def _ensure_policy(self, tenant_id: UUID) -> PeriodLockPolicy:
        if self._period_policy is None:
            _, self._period_policy = await self.org.get_inventory_controls(tenant_id)
        return self._period_policy

    def _date_in_locked_period(self, document_date: date) -> bool:
        if self._period_policy is None:
            return False
        return self._period_policy.is_locked(document_date, can_override=False)


def _signed_line(
    account_id: UUID, amount: Decimal, *, debit_positive: bool, description: str
) -> JournalLineInput:
    if debit_positive:
        debit = amount if amount > _ZERO else _ZERO
        credit = -amount if amount < _ZERO else _ZERO
    else:
        credit = amount if amount > _ZERO else _ZERO
        debit = -amount if amount < _ZERO else _ZERO
    return JournalLineInput(
        account_id=account_id, debit=debit, credit=credit, description=description
    )


def _resolve_reverse_charge(bill_type: BillType, is_reverse_charge: bool | None) -> bool:
    if is_reverse_charge is not None:
        return is_reverse_charge
    return bill_type == BillType.IMPORT


def _weighted_landed_unit_cost(
    layers: Sequence[StockCostLayer], fallback: Decimal
) -> Decimal:
    total_qty = sum((layer.qty_received for layer in layers), _ZERO)
    if total_qty > _ZERO:
        return quantize_money(
            sum((layer.landed_unit_cost * layer.qty_received for layer in layers), _ZERO)
            / total_qty
        )
    if layers:
        return quantize_money(layers[0].landed_unit_cost)
    return quantize_money(fallback)
