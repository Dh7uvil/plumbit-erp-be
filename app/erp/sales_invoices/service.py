"""Sales invoice compose, post, void-by-reversal, and COGS snapshot."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    CUSTOMER_PAYMENT_CREATE,
    ERP_MODULE,
    PERIOD_OVERRIDE,
    SALES_INVOICE_CANCEL,
    SALES_INVOICE_DELETE,
    SALES_INVOICE_POST,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.registries.sales_invoice_dependents import registered_probes
from app.common.schemas.conversion import ConversionLineInput
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.schemas.warnings import DocumentWarning
from app.common.services.audit import AuditWriter
from app.common.utils.conversion import (
    allocate_conversion_qty,
    copy_source_commercial_header,
    quantity_summary,
)
from app.common.utils.currency import quantize_money, quantize_quantity
from app.common.utils.datetime import today_in_timezone, utcnow
from app.common.utils.document_totals import (
    compute_header_totals,
    compute_line_amounts,
    format_address_snapshot,
    place_of_supply_from_address,
    resolve_line_tax_category,
)
from app.common.utils.due_date import due_date_from_terms
from app.common.utils.export_evidence import has_export_evidence
from app.core.enums import (
    AccountSystemRole,
    AuditAction,
    CogsStatus,
    DiscountType,
    DocumentType,
    InvoiceDocumentStatus,
    ItemType,
    JournalType,
    PartyType,
    PaymentStatus,
    PlaceOfSupply,
    QuotationStatus,
    SalesOrderStatus,
    StockDocumentStatus,
    TaxCategory,
    TaxTreatment,
)
from app.core.exceptions import (
    DocumentStaleError,
    InvoiceCannotVoidError,
    InvoiceQtyExceededError,
    PaymentOverAllocatedError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.crm.contacts.service import ContactService
from app.crm.customers.service import CustomerService
from app.db.session import transaction
from app.erp.accounting.accounts.service import AccountResolver, AccountService
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.inventory_posting import SOURCE_DELIVERY_NOTE
from app.erp.accounting.ledger.posting import LedgerPostingService
from app.erp.accounting.ledger.schemas import JournalEntryResponse, JournalLineInput
from app.erp.accounting.ledger.service import JournalEntryService
from app.erp.accounting.service import (
    DocumentSequenceService,
    PaymentTermService,
    TaxService,
    TermsTemplateService,
)
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService
from app.erp.sales_invoices.models import SalesInvoice, SalesInvoiceLine
from app.erp.sales_invoices.repository import SalesInvoiceRepository
from app.erp.sales_invoices.schemas import (
    SalesInvoiceCreate,
    SalesInvoiceCreateFromDeliveryNotes,
    SalesInvoiceCreateFromSalesOrder,
    SalesInvoiceLineInput,
    SalesInvoiceLineResponse,
    SalesInvoiceMarginLine,
    SalesInvoiceMarginResponse,
    SalesInvoiceResponse,
    SalesInvoiceUpdate,
)
from app.erp.sales_invoices.workflow import assert_editable, next_status, transition_actions
from app.erp.sales_orders.service import SalesOrderService
from app.inventory_management.costing.service import CostingService
from app.inventory_management.delivery_notes.service import DeliveryNoteService
from app.inventory_management.price_lists.service import PriceListService
from app.inventory_management.products.service import ProductService
from app.inventory_management.units.service import UnitService

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_SERIES = "INV"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": SALES_INVOICE_POST,
    "cancel": SALES_INVOICE_CANCEL,
}
SOURCE_SALES_INVOICE = "sales_invoice"


class SalesInvoiceService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = SalesInvoiceRepository(session)
        self.org = OrganizationService(session)
        self.customers = CustomerService(session)
        self.contacts = ContactService(session)
        self.products = ProductService(session)
        self.units = UnitService(session)
        self.price_lists = PriceListService(session)
        self.taxes = TaxService(session)
        self.payment_terms = PaymentTermService(session)
        self.terms = TermsTemplateService(session)
        self.currencies = CurrencyService(session)
        self.fx = ExchangeRateService(session)
        self.sequences = DocumentSequenceService(session)
        self.accounts = AccountService(session)
        self.resolver = AccountResolver(session)
        self.posting = LedgerPostingService(session, actor_permissions=actor_permissions)
        self.journals = JournalEntryService(session, actor_permissions=actor_permissions)
        self.sales_orders = SalesOrderService(session, actor_permissions=actor_permissions)
        self.delivery_notes = DeliveryNoteService(session, actor_permissions=actor_permissions)
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
        customer_id: UUID | None = None,
        sales_order_id: UUID | None = None,
        source_quotation_id: UUID | None = None,
        source_proforma_invoice_id: UUID | None = None,
        branch_id: UUID | None = None,
        currency_id: UUID | None = None,
        payment_status: str | None = None,
        invoice_date_from: date | None = None,
        invoice_date_to: date | None = None,
    ) -> tuple[list[SalesInvoiceResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if customer_id is not None:
            filters["customer_id"] = customer_id
        if sales_order_id is not None:
            filters["sales_order_id"] = sales_order_id
        if source_quotation_id is not None:
            filters["source_quotation_id"] = source_quotation_id
        if source_proforma_invoice_id is not None:
            filters["source_proforma_invoice_id"] = source_proforma_invoice_id
        if branch_id is not None:
            filters["branch_id"] = branch_id
        if currency_id is not None:
            filters["currency_id"] = currency_id
        if payment_status is not None:
            filters["payment_status"] = payment_status
        extra: list[Any] = []
        if invoice_date_from is not None:
            extra.append(SalesInvoice.invoice_date >= invoice_date_from)
        if invoice_date_to is not None:
            extra.append(SalesInvoice.invoice_date <= invoice_date_to)
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

    async def get(self, tenant_id: UUID, invoice_id: UUID) -> SalesInvoiceResponse:
        row = await self._require(tenant_id, invoice_id)
        await self._ensure_policy(tenant_id)
        response = self._to_response(row, today=await self._today(tenant_id))
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def create(
        self, tenant_id: UUID, payload: SalesInvoiceCreate, *, actor_user_id: UUID
    ) -> SalesInvoiceResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            invoice_date = cast(date, header["invoice_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(invoice_date, can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.SALES_INVOICE,
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
                entity_type="sales_invoice",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def create_from_sales_order(
        self,
        tenant_id: UUID,
        payload: SalesInvoiceCreateFromSalesOrder,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> SalesInvoiceResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return SalesInvoiceResponse.model_validate(replay)
            order = await self.sales_orders.get(tenant_id, payload.sales_order_id)
            if order.status != SalesOrderStatus.CONFIRMED:
                raise ValidationError(
                    "Sales invoices can only be created from a confirmed sales order"
                )
            requested = (
                [(item.source_line_id, item.quantity) for item in payload.lines]
                if payload.lines is not None
                else None
            )
            allocations = allocate_conversion_qty(
                lines=[(line.id, line.quantity, line.qty_invoiced) for line in order.lines],
                requested=requested,
                empty_message="This sales order has no remaining quantity to invoice",
            )
            by_id = {line.id: line for line in order.lines}
            lines = [
                SalesInvoiceLineInput(
                    product_id=source.product_id,
                    description=source.description,
                    quantity=qty,
                    unit_id=source.unit_id,
                    rate=source.rate,
                    sales_order_line_id=source.id,
                    discount_type=source.discount_type,
                    discount_value=source.discount_value,
                    tax_id=source.tax_id,
                )
                for line_id, qty in allocations
                for source in (by_id[line_id],)
            ]
            create_payload = SalesInvoiceCreate(
                customer_id=order.customer_id,
                contact_id=order.contact_id,
                branch_id=order.branch_id,
                invoice_date=payload.invoice_date,
                salesperson_id=order.salesperson_id,
                sales_order_id=order.id,
                source_quotation_id=order.source_quotation_id,
                source_proforma_invoice_id=order.source_proforma_invoice_id,
                payment_terms_id=order.payment_terms_id,
                currency_id=order.currency_id,
                notes=payload.notes or order.notes,
                terms_and_conditions=order.terms_and_conditions,
                discount_type=order.discount_type,
                discount_value=order.discount_value,
                shipping_amount=order.shipping_amount,
                adjustment_amount=order.adjustment_amount,
                place_of_supply=order.place_of_supply,
                lines=lines,
            )
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            copy_source_commercial_header(
                header,
                exchange_rate=order.exchange_rate,
                base_currency_id=order.base_currency_id,
                bill_to_snapshot=order.bill_to_snapshot,
                ship_to_snapshot=order.ship_to_snapshot,
            )
            invoice_date = cast(date, header["invoice_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(invoice_date, can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.SALES_INVOICE,
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
                entity_type="sales_invoice",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def create_from_delivery_notes(
        self,
        tenant_id: UUID,
        payload: SalesInvoiceCreateFromDeliveryNotes,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> SalesInvoiceResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return SalesInvoiceResponse.model_validate(replay)
            notes = []
            for note_id in payload.delivery_note_ids:
                notes.append(await self.delivery_notes._require(tenant_id, note_id))
            if any(StockDocumentStatus(note.status) != StockDocumentStatus.POSTED for note in notes):
                raise ValidationError("Sales invoices can only be created from posted delivery notes")
            customer_ids = {note.customer_id for note in notes}
            if len(customer_ids) != 1:
                raise ValidationError("Delivery notes must belong to the same customer")
            order_ids = {note.sales_order_id for note in notes}
            sales_order_id = next(iter(order_ids)) if len(order_ids) == 1 else None
            first = notes[0]
            lines: list[SalesInvoiceLineInput] = []
            for note in notes:
                for line in note.lines:
                    outstanding = quantize_quantity(line.quantity - line.qty_invoiced)
                    if outstanding <= _ZERO:
                        continue
                    lines.append(
                        SalesInvoiceLineInput(
                            product_id=line.product_id,
                            description=line.description,
                            quantity=outstanding,
                            unit_id=line.unit_id,
                            rate=line.rate,
                            sales_order_line_id=line.sales_order_line_id,
                            delivery_note_id=note.id,
                            delivery_note_line_id=line.id,
                        )
                    )
            if not lines:
                raise ValidationError("These delivery notes have no remaining quantity to invoice")
            order = (
                await self.sales_orders.get(tenant_id, sales_order_id)
                if sales_order_id is not None
                else None
            )
            create_payload = SalesInvoiceCreate(
                customer_id=first.customer_id,
                contact_id=order.contact_id if order is not None else None,
                branch_id=first.branch_id or (order.branch_id if order is not None else None),
                invoice_date=payload.invoice_date,
                salesperson_id=order.salesperson_id if order is not None else None,
                sales_order_id=sales_order_id,
                payment_terms_id=order.payment_terms_id if order is not None else None,
                currency_id=first.currency_id,
                notes=payload.notes,
                terms_and_conditions=order.terms_and_conditions if order is not None else None,
                shipping_amount=order.shipping_amount if order is not None else _ZERO,
                adjustment_amount=order.adjustment_amount if order is not None else _ZERO,
                discount_type=order.discount_type if order is not None else None,
                discount_value=order.discount_value if order is not None else None,
                place_of_supply=PlaceOfSupply(first.place_of_supply),
                lines=lines,
            )
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            invoice_date = cast(date, header["invoice_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(invoice_date, can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.SALES_INVOICE,
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
                entity_type="sales_invoice",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def create_from_quotation(
        self,
        tenant_id: UUID,
        quotation_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        invoice_date: date | None = None,
        notes: str | None = None,
        conversion_lines: Sequence[ConversionLineInput] | None = None,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> SalesInvoiceResponse:
        from app.erp.quotation.service import QuotationService

        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return SalesInvoiceResponse.model_validate(replay)
            quotes = QuotationService(self.session, actor_permissions=self.actor_permissions)
            quotation = await quotes.require_convertible(
                tenant_id, quotation_id, expected_version=expected_version
            )
            requested = (
                [(item.source_line_id, item.quantity) for item in conversion_lines]
                if conversion_lines is not None
                else None
            )
            allocations = allocate_conversion_qty(
                lines=[
                    (line.id, line.quantity, line.qty_converted) for line in quotation.lines
                ],
                requested=requested,
                empty_message="This quotation has no remaining quantity to convert",
            )
            by_id = {line.id: line for line in quotation.lines}
            selected = [(by_id[line_id], qty) for line_id, qty in allocations]
            create_payload = SalesInvoiceCreate(
                customer_id=quotation.customer_id,
                contact_id=quotation.contact_id,
                branch_id=quotation.branch_id,
                invoice_date=invoice_date,
                salesperson_id=quotation.salesperson_id,
                source_quotation_id=quotation.id,
                payment_terms_id=quotation.payment_terms_id,
                currency_id=quotation.currency_id,
                notes=notes or quotation.notes,
                terms_and_conditions=quotation.terms_and_conditions,
                discount_type=quotation.discount_type,
                discount_value=quotation.discount_value,
                shipping_amount=quotation.shipping_amount,
                adjustment_amount=quotation.adjustment_amount,
                place_of_supply=quotation.place_of_supply,
                lines=[
                    SalesInvoiceLineInput(
                        product_id=source.product_id,
                        description=source.description,
                        quantity=qty,
                        unit_id=source.unit_id,
                        rate=source.rate,
                        source_quotation_line_id=source.id,
                        discount_type=source.discount_type,
                        discount_value=source.discount_value,
                        tax_id=source.tax_id,
                    )
                    for source, qty in selected
                ],
            )
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            header["source_quotation_id"] = quotation.id
            copy_source_commercial_header(
                header,
                exchange_rate=quotation.exchange_rate,
                base_currency_id=quotation.base_currency_id,
                bill_to_snapshot=quotation.bill_to_snapshot,
                ship_to_snapshot=quotation.ship_to_snapshot,
            )
            for built, (source, _) in zip(line_rows, selected, strict=True):
                built["source_quotation_line_id"] = source.id
            invoice_date_value = cast(date, header["invoice_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(invoice_date_value, can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.SALES_INVOICE,
                series=_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, invoice_date_value),
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
            await quotes._apply_converted(
                tenant_id,
                quotation_id,
                document_type=DocumentType.SALES_INVOICE,
                document_id=row.id,
                actor_user_id=actor_user_id,
                expected_version=quotation.version,
                allocations=allocations,
            )
            loaded = await self._require(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ERP_MODULE,
                entity_type="sales_invoice",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def create_from_proforma_invoice(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        invoice_date: date | None = None,
        notes: str | None = None,
        conversion_lines: Sequence[ConversionLineInput] | None = None,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> SalesInvoiceResponse:
        from app.erp.proforma_invoices.service import ProformaInvoiceService
        from app.erp.quotation.service import QuotationService

        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return SalesInvoiceResponse.model_validate(replay)
            pfis = ProformaInvoiceService(self.session, actor_permissions=self.actor_permissions)
            pfi = await pfis.require_convertible(
                tenant_id, proforma_invoice_id, expected_version=expected_version
            )
            requested = (
                [(item.source_line_id, item.quantity) for item in conversion_lines]
                if conversion_lines is not None
                else None
            )
            allocations = allocate_conversion_qty(
                lines=[(line.id, line.quantity, line.qty_converted) for line in pfi.lines],
                requested=requested,
                empty_message="This proforma invoice has no remaining quantity to convert",
            )
            by_id = {line.id: line for line in pfi.lines}
            selected = [(by_id[line_id], qty) for line_id, qty in allocations]
            create_payload = SalesInvoiceCreate(
                customer_id=pfi.customer_id,
                contact_id=pfi.contact_id,
                branch_id=pfi.branch_id,
                invoice_date=invoice_date,
                salesperson_id=pfi.salesperson_id,
                source_quotation_id=pfi.source_quotation_id,
                source_proforma_invoice_id=pfi.id,
                payment_terms_id=pfi.payment_terms_id,
                currency_id=pfi.currency_id,
                notes=notes or pfi.notes,
                terms_and_conditions=pfi.terms_and_conditions,
                discount_type=pfi.discount_type,
                discount_value=pfi.discount_value,
                shipping_amount=pfi.shipping_amount,
                adjustment_amount=pfi.adjustment_amount,
                place_of_supply=pfi.place_of_supply,
                lines=[
                    SalesInvoiceLineInput(
                        product_id=source.product_id,
                        description=source.description,
                        quantity=qty,
                        unit_id=source.unit_id,
                        rate=source.rate,
                        source_quotation_line_id=source.source_quotation_line_id,
                        source_proforma_invoice_line_id=source.id,
                        discount_type=source.discount_type,
                        discount_value=source.discount_value,
                        tax_id=source.tax_id,
                    )
                    for source, qty in selected
                ],
            )
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            header["source_quotation_id"] = pfi.source_quotation_id
            header["source_proforma_invoice_id"] = pfi.id
            copy_source_commercial_header(
                header,
                exchange_rate=pfi.exchange_rate,
                base_currency_id=pfi.base_currency_id,
                bill_to_snapshot=pfi.bill_to_snapshot,
                ship_to_snapshot=pfi.ship_to_snapshot,
            )
            for built, (source, _) in zip(line_rows, selected, strict=True):
                built["source_proforma_invoice_line_id"] = source.id
                built["source_quotation_line_id"] = source.source_quotation_line_id
            invoice_date_value = cast(date, header["invoice_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(invoice_date_value, can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.SALES_INVOICE,
                series=_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, invoice_date_value),
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
            await pfis._apply_converted(
                tenant_id,
                proforma_invoice_id,
                document_type=DocumentType.SALES_INVOICE,
                document_id=row.id,
                actor_user_id=actor_user_id,
                expected_version=pfi.version,
                allocations=allocations,
            )
            quote_allocations = [
                (source.source_quotation_line_id, qty)
                for source, qty in selected
                if source.source_quotation_line_id is not None
            ]
            if pfi.source_quotation_id is not None and quote_allocations:
                quotes = QuotationService(self.session, actor_permissions=self.actor_permissions)
                quotation = await quotes.get(tenant_id, pfi.source_quotation_id)
                if quotation.status in {
                    QuotationStatus.ACCEPTED,
                    QuotationStatus.PARTIALLY_CONVERTED,
                }:
                    await quotes._apply_converted(
                        tenant_id,
                        pfi.source_quotation_id,
                        document_type=DocumentType.SALES_INVOICE,
                        document_id=row.id,
                        actor_user_id=actor_user_id,
                        expected_version=quotation.version,
                        allocations=quote_allocations,
                    )
            loaded = await self._require(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ERP_MODULE,
                entity_type="sales_invoice",
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
        payload: SalesInvoiceUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> SalesInvoiceResponse:
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
                entity_type="sales_invoice",
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
    ) -> SalesInvoiceResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, invoice_id, for_update=True)
            self._assert_version(row, expected_version)
            assert_editable(InvoiceDocumentStatus(row.status))
            old_values = await self._snapshot(tenant_id, row)
            response = self._to_response(row)
            deleted = await self.repo.soft_delete(tenant_id, invoice_id)
            if deleted is None:
                raise ResourceNotFoundError("Sales invoice not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="sales_invoice",
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
        override_reason: str | None = None,
    ) -> SalesInvoiceResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return SalesInvoiceResponse.model_validate(replay)
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
            from app.erp.credit_control.service import CreditControlService

            settings = await self.org.get_money_movement_settings(tenant_id)
            additional = _ZERO
            if row.sales_order_id is None or not settings.credit_limit_include_open_orders:
                additional = row.grand_total
            warnings = await CreditControlService(
                self.session, actor_permissions=self.actor_permissions
            ).enforce(
                tenant_id,
                row.customer_id,
                additional,
                actor_user_id=actor_user_id,
                override_reason=override_reason,
            )
            await self._stamp_cogs(tenant_id, row)
            journal = await self.posting.post_for_document(
                tenant_id,
                source_type=SOURCE_SALES_INVOICE,
                source_id=row.id,
                entry_date=row.invoice_date,
                lines=await self._journal_lines(tenant_id, row),
                currency_id=row.currency_id,
                exchange_rate=row.exchange_rate,
                narration=f"Sales invoice {row.document_number}",
                branch_id=row.branch_id,
                actor_id=actor_user_id,
                journal_type=JournalType.SYSTEM,
                reference=row.document_number,
            )
            row.journal_entry_id = journal.id
            await self._apply_source_quantities(tenant_id, row, sign=Decimal("1"))
            evidence_ok = True
            if row.is_export:
                dn_ids = list(
                    {line.delivery_note_id for line in row.lines if line.delivery_note_id is not None}
                )
                evidence_ok = bool(dn_ids) and await has_export_evidence(
                    self.session, tenant_id, dn_ids
                )
            row.export_evidence_ok = evidence_ok
            row.export_evidence_checked_at = utcnow()
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
                entity_type="sales_invoice",
                entity_id=invoice_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="erp.sales_invoice.posted",
                aggregate_type="sales_invoice",
                aggregate_id=invoice_id,
                payload={"sales_invoice_id": str(invoice_id)},
                dedupe_key=f"sales-invoice-posted:{invoice_id}",
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="erp.einvoice.submit_requested",
                aggregate_type="sales_invoice",
                aggregate_id=invoice_id,
                payload={"sales_invoice_id": str(invoice_id)},
                dedupe_key=f"einvoice-submit:{invoice_id}",
            )
            if loaded.source_proforma_invoice_id is not None:
                from app.erp.customer_payments.service import CustomerPaymentService

                await CustomerPaymentService(
                    self.session, actor_permissions=self.actor_permissions
                ).auto_apply_pfi_advances(
                    tenant_id,
                    invoice_id=loaded.id,
                    customer_id=loaded.customer_id,
                    proforma_invoice_id=loaded.source_proforma_invoice_id,
                    actor_user_id=actor_user_id,
                )
                loaded = await self._require(tenant_id, invoice_id)
            response = self._to_response(loaded, warnings=warnings)
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
    ) -> SalesInvoiceResponse:
        async with transaction(self.session):
            if idempotency_key and request_hash and endpoint:
                replay = await self.idempotency.begin(
                    tenant_id, idempotency_key, request_hash, endpoint=endpoint
                )
                if replay is not None:
                    return SalesInvoiceResponse.model_validate(replay)
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
                entity_type="sales_invoice",
                entity_id=invoice_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            if current == InvoiceDocumentStatus.POSTED:
                await self.outbox.enqueue(
                    tenant_id,
                    event_type="erp.sales_invoice.cancelled",
                    aggregate_type="sales_invoice",
                    aggregate_id=invoice_id,
                    payload={"sales_invoice_id": str(invoice_id)},
                    dedupe_key=f"sales-invoice-cancelled:{invoice_id}",
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
            raise ResourceNotFoundError("Sales invoice has no journal entry")
        return await self.journals.get(tenant_id, row.journal_entry_id)

    async def margin(self, tenant_id: UUID, invoice_id: UUID) -> SalesInvoiceMarginResponse:
        row = await self._require(tenant_id, invoice_id)
        line_rows: list[SalesInvoiceMarginLine] = []
        revenue = _ZERO
        for line in row.lines:
            share = self._header_discount_share(row, line)
            line_revenue = quantize_money(line.amount - share)
            revenue += line_revenue
            line_rows.append(
                SalesInvoiceMarginLine(
                    line_id=line.id,
                    line_number=line.line_number,
                    revenue=line_revenue,
                    cogs_amount=line.cogs_amount,
                    cogs_status=CogsStatus(line.cogs_status),
                    margin=quantize_money(line_revenue - line.cogs_amount),
                )
            )
        cogs = quantize_money(row.cogs_amount)
        margin = quantize_money(revenue - cogs)
        percent = quantize_money(margin * _HUNDRED / revenue) if revenue else None
        return SalesInvoiceMarginResponse(
            invoice_id=row.id,
            revenue=revenue,
            cogs_amount=cogs,
            cogs_status=CogsStatus(row.cogs_status),
            margin=margin,
            margin_percent=percent,
            lines=line_rows,
        )

    async def has_live_for_delivery_note(self, tenant_id: UUID, delivery_note_id: UUID) -> bool:
        return await self.repo.has_live_for_delivery_note(tenant_id, delivery_note_id)

    async def apply_credit(
        self, tenant_id: UUID, invoice_id: UUID, amount: Decimal
    ) -> SalesInvoice:
        """Caller owns the transaction. Amount may be negative to reverse a credit note."""

        row = await self._require(tenant_id, invoice_id, for_update=True)
        row.amount_credited = quantize_money(row.amount_credited + amount)
        if row.amount_credited < _ZERO:
            raise ValidationError("Credited amount cannot be negative")
        self._refresh_payment_status(row)
        await self.session.flush()
        return row

    async def apply_payment(
        self, tenant_id: UUID, invoice_id: UUID, amount: Decimal
    ) -> SalesInvoice:
        """Caller owns the transaction. Amount may be negative to reverse a receipt."""

        row = await self._require(tenant_id, invoice_id, for_update=True)
        row.amount_paid = quantize_money(row.amount_paid + amount)
        if row.amount_paid < _ZERO:
            raise ValidationError("Paid amount cannot be negative")
        settled = quantize_money(row.amount_paid + row.amount_credited)
        if settled > row.grand_total:
            raise PaymentOverAllocatedError(
                details={
                    "grand_total": str(row.grand_total),
                    "amount_paid": str(row.amount_paid),
                    "amount_credited": str(row.amount_credited),
                }
            )
        self._refresh_payment_status(row)
        await self.session.flush()
        return row

    async def _cancel_posted(
        self, tenant_id: UUID, row: SalesInvoice, *, actor_user_id: UUID
    ) -> None:
        policy = await self._ensure_policy(tenant_id)
        if policy.is_locked(row.invoice_date, can_override=self._can_override):
            raise InvoiceCannotVoidError("The period is locked")
        if row.amount_paid > _ZERO:
            raise InvoiceCannotVoidError("This invoice has payments and cannot be voided")
        if row.amount_credited > _ZERO:
            raise InvoiceCannotVoidError("This invoice has credit notes and cannot be voided")
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
        await self._apply_source_quantities(tenant_id, row, sign=Decimal("-1"))
        row.is_posted = False

    async def _assert_qty_headroom(self, tenant_id: UUID, row: SalesInvoice) -> None:
        so_remaining: dict[UUID, Decimal] = {}
        if row.sales_order_id is not None:
            order = await self.sales_orders._require(tenant_id, row.sales_order_id, for_update=True)
            so_remaining = {
                line.id: quantize_quantity(line.quantity - line.qty_invoiced) for line in order.lines
            }
        dn_remaining: dict[UUID, Decimal] = {}
        dn_ids = {line.delivery_note_id for line in row.lines if line.delivery_note_id is not None}
        for note_id in dn_ids:
            note = await self.delivery_notes._require(tenant_id, note_id, for_update=True)
            for line in note.lines:
                dn_remaining[line.id] = quantize_quantity(line.quantity - line.qty_invoiced)
        for line in row.lines:
            if line.delivery_note_line_id is not None:
                remaining = dn_remaining.get(line.delivery_note_line_id, _ZERO)
                if line.quantity > remaining:
                    raise InvoiceQtyExceededError(
                        details={
                            "delivery_note_line_id": str(line.delivery_note_line_id),
                            "quantity": str(line.quantity),
                            "outstanding": str(remaining),
                        }
                    )
            if line.sales_order_line_id is not None:
                remaining = so_remaining.get(line.sales_order_line_id, _ZERO)
                if line.quantity > remaining:
                    raise InvoiceQtyExceededError(
                        details={
                            "sales_order_line_id": str(line.sales_order_line_id),
                            "quantity": str(line.quantity),
                            "outstanding": str(remaining),
                        }
                    )

    async def _apply_source_quantities(
        self, tenant_id: UUID, row: SalesInvoice, *, sign: Decimal
    ) -> None:
        so_qty: dict[UUID, dict[UUID, Decimal]] = {}
        dn_qty: dict[UUID, dict[UUID, Decimal]] = {}
        for line in row.lines:
            delta = quantize_quantity(line.quantity * sign)
            if line.sales_order_line_id is not None and row.sales_order_id is not None:
                bucket = so_qty.setdefault(row.sales_order_id, {})
                bucket[line.sales_order_line_id] = bucket.get(line.sales_order_line_id, _ZERO) + delta
            elif line.sales_order_line_id is not None:
                # Line linked to an SO without a header sales_order_id — still bill the line.
                order_id = await self._sales_order_id_for_line(tenant_id, line.sales_order_line_id)
                bucket = so_qty.setdefault(order_id, {})
                bucket[line.sales_order_line_id] = bucket.get(line.sales_order_line_id, _ZERO) + delta
            if line.delivery_note_id is not None and line.delivery_note_line_id is not None:
                bucket = dn_qty.setdefault(line.delivery_note_id, {})
                bucket[line.delivery_note_line_id] = (
                    bucket.get(line.delivery_note_line_id, _ZERO) + delta
                )
        for order_id, invoices in so_qty.items():
            await self.sales_orders.apply_line_invoices(tenant_id, order_id, invoices)
        for note_id, invoices in dn_qty.items():
            await self.delivery_notes.apply_line_invoices(tenant_id, note_id, invoices)

    async def _sales_order_id_for_line(self, tenant_id: UUID, sales_order_line_id: UUID) -> UUID:
        from app.erp.sales_orders.models import SalesOrderLine

        line = await self.session.get(SalesOrderLine, sales_order_line_id)
        if line is None or line.tenant_id != tenant_id:
            raise ValidationError("Sales order line not found")
        return line.sales_order_id

    async def _recompute_posted_totals(self, tenant_id: UUID, row: SalesInvoice) -> None:
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

    async def _stamp_cogs(self, tenant_id: UUID, row: SalesInvoice) -> None:
        statuses: list[str] = []
        total = _ZERO
        for line in row.lines:
            stockable = await self._is_stockable(tenant_id, line.product_id)
            if line.delivery_note_id is not None and line.delivery_note_line_id is not None:
                _qty, value = await self.costing.net_cost_for_source_line(
                    tenant_id,
                    SOURCE_DELIVERY_NOTE,
                    line.delivery_note_id,
                    line.delivery_note_line_id,
                )
                note = await self.delivery_notes._require(tenant_id, line.delivery_note_id)
                dn_line = next(
                    (item for item in note.lines if item.id == line.delivery_note_line_id),
                    None,
                )
                if dn_line is not None and dn_line.quantity > _ZERO:
                    line.cogs_amount = quantize_money(value * line.quantity / dn_line.quantity)
                else:
                    line.cogs_amount = quantize_money(_ZERO)
                line.cogs_status = (
                    CogsStatus.POSTED.value if line.cogs_amount > _ZERO or not stockable else CogsStatus.PENDING.value
                )
                if not stockable:
                    line.cogs_status = CogsStatus.NOT_APPLICABLE.value
                    line.cogs_amount = quantize_money(_ZERO)
            elif stockable:
                line.cogs_amount = quantize_money(_ZERO)
                line.cogs_status = CogsStatus.PENDING.value
            else:
                line.cogs_amount = quantize_money(_ZERO)
                line.cogs_status = CogsStatus.NOT_APPLICABLE.value
            statuses.append(line.cogs_status)
            total += line.cogs_amount
        row.cogs_amount = quantize_money(total)
        row.cogs_status = _header_cogs_status(statuses)

    async def _journal_lines(
        self, tenant_id: UUID, row: SalesInvoice
    ) -> list[JournalLineInput]:
        ar = await self.accounts.party_resolver.resolve_receivable(tenant_id, row.customer_id)
        vat = await self.resolver.require(tenant_id, AccountSystemRole.VAT_OUTPUT)
        shipping = await self.resolver.require(tenant_id, AccountSystemRole.SHIPPING_INCOME)
        other = await self.resolver.require(tenant_id, AccountSystemRole.OTHER_CHARGES)
        round_off = await self.resolver.require(tenant_id, AccountSystemRole.ROUND_OFF)
        default_income = await self.resolver.require(tenant_id, AccountSystemRole.SALES_REVENUE)
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
            if line.product_id is not None:
                income = await self.accounts.resolve_income_account(tenant_id, line.product_id)
            else:
                income = default_income
            line.income_account_id = income.id
            if net_revenue != _ZERO:
                lines.append(
                    JournalLineInput(
                        account_id=income.id,
                        credit=net_revenue if net_revenue > _ZERO else _ZERO,
                        debit=-net_revenue if net_revenue < _ZERO else _ZERO,
                        description=line.description,
                    )
                )
        if row.tax_amount > _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=vat.id,
                    credit=row.tax_amount,
                    description="VAT output",
                )
            )
        if row.shipping_amount != _ZERO:
            lines.append(
                _signed_line(shipping.id, row.shipping_amount, credit_positive=True, description="Shipping")
            )
        if row.adjustment_amount != _ZERO:
            lines.append(
                _signed_line(
                    other.id, row.adjustment_amount, credit_positive=True, description="Other charges"
                )
            )
        if row.round_off_amount != _ZERO:
            lines.append(
                _signed_line(
                    round_off.id, row.round_off_amount, credit_positive=True, description="Round off"
                )
            )
        if row.grand_total != _ZERO:
            lines.append(
                JournalLineInput(
                    account_id=ar.id,
                    debit=row.grand_total if row.grand_total > _ZERO else _ZERO,
                    credit=-row.grand_total if row.grand_total < _ZERO else _ZERO,
                    party_type=PartyType.CUSTOMER,
                    party_id=row.customer_id,
                    due_date=row.due_date,
                    external_reference=row.document_number,
                    description=f"AR {row.document_number}",
                )
            )
        return lines

    def _header_discount_share(self, row: SalesInvoice, line: SalesInvoiceLine) -> Decimal:
        if row.subtotal <= _ZERO or row.discount_amount == _ZERO:
            return quantize_money(_ZERO)
        return quantize_money(row.discount_amount * line.amount / row.subtotal)

    async def _build_draft(
        self, tenant_id: UUID, payload: SalesInvoiceCreate
    ) -> tuple[dict[str, object], builtins.list[dict[str, object]]]:
        customer = await self.customers.get(tenant_id, payload.customer_id)
        if payload.branch_id is not None:
            await self.org.require_branch(tenant_id, payload.branch_id)
        if payload.contact_id is not None:
            contact = await self.contacts.get(tenant_id, payload.contact_id)
            if contact.customer_id != customer.id:
                raise ValidationError("Contact does not belong to this customer")
        if payload.salesperson_id is not None:
            await self.org.require_employee(tenant_id, payload.salesperson_id)
        payment_terms_id = payload.payment_terms_id or customer.payment_terms_id
        if payment_terms_id is not None:
            await self.payment_terms.require_id(tenant_id, payment_terms_id)
        if payload.sales_order_id is not None:
            await self.sales_orders.get(tenant_id, payload.sales_order_id)

        currency_id = payload.currency_id or customer.currency_id
        await self.currencies.require_id(tenant_id, currency_id)
        base = await self.currencies.get_base(tenant_id)
        invoice_date = payload.invoice_date or await self._today(tenant_id)
        resolved = await self.fx.resolve(
            tenant_id,
            from_currency_id=currency_id,
            to_currency_id=base.id,
            on_date=invoice_date,
        )
        place = payload.place_of_supply or place_of_supply_from_address(customer.shipping_address)
        terms_body = payload.terms_and_conditions
        if terms_body is None and payload.terms_template_id is not None:
            template = await self.terms.get(tenant_id, payload.terms_template_id)
            terms_body = template.body
        if terms_body is None:
            default_terms = await self.terms.get_default(tenant_id)
            terms_body = default_terms.body if default_terms else None
        tax_treatment = TaxTreatment(customer.tax_treatment)
        is_export = tax_treatment in {TaxTreatment.EXPORT, TaxTreatment.GCC} or place == PlaceOfSupply.OUTSIDE_UAE
        line_rows, line_nets, line_taxes = await self._build_lines(
            tenant_id,
            payload.lines,
            tax_treatment=tax_treatment,
            place_of_supply=place,
            price_list_id=customer.default_price_list_id,
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
        due_date = await due_date_from_terms(
            self.session, tenant_id, payment_terms_id, invoice_date
        )
        header: dict[str, object] = {
            "invoice_date": invoice_date,
            "customer_id": customer.id,
            "contact_id": payload.contact_id,
            "customer_trn": customer.trn,
            "branch_id": payload.branch_id,
            "salesperson_id": payload.salesperson_id or customer.salesperson_id,
            "sales_order_id": payload.sales_order_id,
            "source_quotation_id": payload.source_quotation_id,
            "source_proforma_invoice_id": payload.source_proforma_invoice_id,
            "payment_terms_id": payment_terms_id,
            "due_date": due_date,
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
            "bill_to_snapshot": format_address_snapshot(customer.billing_address),
            "ship_to_snapshot": format_address_snapshot(customer.shipping_address),
            "notes": payload.notes,
            "terms_and_conditions": terms_body,
            "amount_paid": _ZERO,
            "amount_credited": _ZERO,
            "balance_due": grand,
            "payment_status": PaymentStatus.UNPAID.value,
            "cogs_amount": _ZERO,
            "cogs_status": CogsStatus.NOT_APPLICABLE.value,
            "export_evidence_ok": True,
        }
        return header, line_rows

    async def _build_lines(
        self,
        tenant_id: UUID,
        lines: Sequence[SalesInvoiceLineInput],
        *,
        tax_treatment: TaxTreatment,
        place_of_supply: PlaceOfSupply,
        price_list_id: UUID | None,
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
            if product is None:
                if line.rate is None:
                    raise ValidationError("Custom lines require a rate")
                rate = quantize_money(line.rate)
            else:
                rate = await self.price_lists.resolve_rate(
                    tenant_id,
                    product_id=product.id,
                    selling_rate=product.selling_rate,
                    price_list_id=price_list_id,
                    line_override=line.rate,
                )
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
                    "sales_order_line_id": line.sales_order_line_id,
                    "source_quotation_line_id": line.source_quotation_line_id,
                    "source_proforma_invoice_line_id": line.source_proforma_invoice_line_id,
                    "delivery_note_id": line.delivery_note_id,
                    "delivery_note_line_id": line.delivery_note_line_id,
                    "discount_type": line.discount_type.value if line.discount_type else None,
                    "discount_value": line.discount_value,
                    "discount_amount": line_discount,
                    "tax_id": chosen_tax.id,
                    "tax_rate": chosen_tax.rate,
                    "tax_amount": tax_amount,
                    "amount": net,
                    "cogs_amount": _ZERO,
                    "cogs_status": CogsStatus.NOT_APPLICABLE.value,
                    "qty_credited": _ZERO,
                }
            )
            nets.append(net)
            taxes.append(tax_amount)
        return built, nets, taxes

    async def _update_to_create(
        self, existing: SalesInvoice, payload: SalesInvoiceUpdate
    ) -> SalesInvoiceCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                SalesInvoiceLineInput(
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    sales_order_line_id=line.sales_order_line_id,
                    source_quotation_line_id=line.source_quotation_line_id,
                    source_proforma_invoice_line_id=line.source_proforma_invoice_line_id,
                    delivery_note_id=line.delivery_note_id,
                    delivery_note_line_id=line.delivery_note_line_id,
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    tax_id=line.tax_id,
                )
                for line in existing.lines
            ]
        return SalesInvoiceCreate(
            customer_id=existing.customer_id,
            contact_id=values.get("contact_id", existing.contact_id),
            branch_id=values.get("branch_id", existing.branch_id),
            invoice_date=values.get("invoice_date", existing.invoice_date),
            salesperson_id=values.get("salesperson_id", existing.salesperson_id),
            sales_order_id=values.get("sales_order_id", existing.sales_order_id),
            source_quotation_id=existing.source_quotation_id,
            source_proforma_invoice_id=existing.source_proforma_invoice_id,
            payment_terms_id=values.get("payment_terms_id", existing.payment_terms_id),
            currency_id=values.get("currency_id", existing.currency_id),
            notes=values.get("notes", existing.notes),
            terms_and_conditions=values.get("terms_and_conditions", existing.terms_and_conditions),
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

    async def _row_to_create(self, row: SalesInvoice) -> SalesInvoiceCreate:
        return SalesInvoiceCreate(
            customer_id=row.customer_id,
            contact_id=row.contact_id,
            branch_id=row.branch_id,
            invoice_date=row.invoice_date,
            salesperson_id=row.salesperson_id,
            sales_order_id=row.sales_order_id,
            source_quotation_id=row.source_quotation_id,
            source_proforma_invoice_id=row.source_proforma_invoice_id,
            payment_terms_id=row.payment_terms_id,
            currency_id=row.currency_id,
            notes=row.notes,
            terms_and_conditions=row.terms_and_conditions,
            discount_type=DiscountType(row.discount_type) if row.discount_type else None,
            discount_value=row.discount_value,
            shipping_amount=row.shipping_amount,
            adjustment_amount=row.adjustment_amount,
            round_off_amount=row.round_off_amount,
            place_of_supply=PlaceOfSupply(row.place_of_supply),
            lines=[
                SalesInvoiceLineInput(
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    sales_order_line_id=line.sales_order_line_id,
                    source_quotation_line_id=line.source_quotation_line_id,
                    source_proforma_invoice_line_id=line.source_proforma_invoice_line_id,
                    delivery_note_id=line.delivery_note_id,
                    delivery_note_line_id=line.delivery_note_line_id,
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    tax_id=line.tax_id,
                )
                for line in row.lines
            ],
        )

    async def _is_stockable(self, tenant_id: UUID, product_id: UUID | None) -> bool:
        if product_id is None:
            return False
        product = await self.products.get(tenant_id, product_id)
        return product.item_type != ItemType.SERVICE and product.track_inventory

    def _refresh_payment_status(self, row: SalesInvoice) -> None:
        row.balance_due = quantize_money(row.grand_total - row.amount_paid - row.amount_credited)
        if row.balance_due < _ZERO:
            row.balance_due = _ZERO
        applied = quantize_money(row.amount_paid + row.amount_credited)
        if applied <= _ZERO:
            row.payment_status = PaymentStatus.UNPAID.value
        elif row.balance_due <= _ZERO:
            row.payment_status = PaymentStatus.PAID.value
        else:
            row.payment_status = PaymentStatus.PARTIALLY_PAID.value

    def _available_actions(
        self, row: SalesInvoice, status: InvoiceDocumentStatus, *, period_locked: bool
    ) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            if action in {"post", "cancel"} and period_locked and status != InvoiceDocumentStatus.DRAFT:
                continue
            if action == "post" and period_locked:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == InvoiceDocumentStatus.DRAFT and has_permission(
            self.actor_permissions, SALES_INVOICE_DELETE
        ):
            actions.append("delete")
        if (
            status == InvoiceDocumentStatus.POSTED
            and row.balance_due > _ZERO
            and has_permission(self.actor_permissions, CUSTOMER_PAYMENT_CREATE)
        ):
            actions.append("record_payment")
            actions.append("apply_credits")
        return actions

    def _to_response(
        self,
        row: SalesInvoice,
        *,
        today: date | None = None,
        warnings: builtins.list[DocumentWarning] | None = None,
    ) -> SalesInvoiceResponse:
        status = InvoiceDocumentStatus(row.status)
        period_locked = self._date_in_locked_period(row.invoice_date)
        credited = row.amount_credited
        is_fully_credited = credited > _ZERO and credited >= row.grand_total
        is_partially_credited = credited > _ZERO and not is_fully_credited
        is_overdue = (
            today is not None
            and row.due_date is not None
            and row.due_date < today
            and status == InvoiceDocumentStatus.POSTED
            and row.balance_due > _ZERO
        )
        return SalesInvoiceResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            display_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=row.is_posted,
            invoice_date=row.invoice_date,
            document_date=row.invoice_date,
            customer_id=row.customer_id,
            contact_id=row.contact_id,
            customer_trn=row.customer_trn,
            branch_id=row.branch_id,
            salesperson_id=row.salesperson_id,
            sales_order_id=row.sales_order_id,
            source_quotation_id=row.source_quotation_id,
            source_proforma_invoice_id=row.source_proforma_invoice_id,
            payment_terms_id=row.payment_terms_id,
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
            bill_to_snapshot=row.bill_to_snapshot,
            ship_to_snapshot=row.ship_to_snapshot,
            notes=row.notes,
            terms_and_conditions=row.terms_and_conditions,
            amount_paid=row.amount_paid,
            amount_credited=row.amount_credited,
            balance_due=row.balance_due,
            payment_status=PaymentStatus(row.payment_status),
            cogs_amount=row.cogs_amount,
            cogs_status=CogsStatus(row.cogs_status),
            journal_entry_id=row.journal_entry_id,
            reversal_journal_entry_id=row.reversal_journal_entry_id,
            export_evidence_ok=row.export_evidence_ok,
            export_evidence_checked_at=row.export_evidence_checked_at,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            is_overdue=is_overdue,
            is_partially_credited=is_partially_credited,
            is_fully_credited=is_fully_credited,
            available_actions=self._available_actions(row, status, period_locked=period_locked),
            related_documents=[],
            warnings=warnings or [],
            lines=[
                SalesInvoiceLineResponse(
                    id=line.id,
                    line_number=line.line_number,
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    sales_order_line_id=line.sales_order_line_id,
                    source_quotation_line_id=line.source_quotation_line_id,
                    source_proforma_invoice_line_id=line.source_proforma_invoice_line_id,
                    delivery_note_id=line.delivery_note_id,
                    delivery_note_line_id=line.delivery_note_line_id,
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    discount_amount=line.discount_amount,
                    tax_id=line.tax_id,
                    tax_rate=line.tax_rate,
                    tax_amount=line.tax_amount,
                    amount=line.amount,
                    income_account_id=line.income_account_id,
                    cogs_amount=line.cogs_amount,
                    cogs_status=CogsStatus(line.cogs_status),
                    qty_credited=line.qty_credited,
                )
                for line in row.lines
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _related_documents(
        self, tenant_id: UUID, row: SalesInvoice
    ) -> builtins.list[RelatedDocumentRef]:
        from app.erp.credit_notes.repository import CreditNoteRepository
        from app.erp.proforma_invoices.repository import ProformaInvoiceRepository
        from app.erp.quotation.repository import QuotationRepository
        from app.erp.sales_orders.repository import SalesOrderRepository
        from app.inventory_management.delivery_notes.repository import DeliveryNoteRepository

        related: builtins.list[RelatedDocumentRef] = []
        if row.source_quotation_id is not None:
            quote = await QuotationRepository(self.session).get(tenant_id, row.source_quotation_id)
            if quote is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.QUOTATION.value,
                        document_id=quote.id,
                        document_number=quote.quote_number,
                        status=quote.status,
                        relationship="source",
                        document_date=quote.quote_date,
                    )
                )
        if row.source_proforma_invoice_id is not None:
            pfi = await ProformaInvoiceRepository(self.session).get(
                tenant_id, row.source_proforma_invoice_id
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
        note_ids = {
            line.delivery_note_id for line in row.lines if line.delivery_note_id is not None
        }
        dn_repo = DeliveryNoteRepository(self.session)
        for note_id in note_ids:
            note = await dn_repo.get(tenant_id, note_id)
            if note is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.DELIVERY_NOTE.value,
                        document_id=note.id,
                        document_number=note.document_number,
                        status=note.status,
                        relationship="source",
                        document_date=note.document_date,
                        quantity_summary=quantity_summary([line.quantity for line in note.lines]),
                    )
                )
        for item in await CreditNoteRepository(self.session).list_for_sales_invoice(
            tenant_id, row.id
        ):
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.CREDIT_NOTE.value,
                    document_id=item.id,
                    document_number=item.document_number,
                    status=item.status,
                    relationship="child",
                    document_date=item.credit_note_date,
                    quantity_summary=quantity_summary([line.quantity for line in item.lines]),
                )
            )
        from app.erp.customer_payments.service import CustomerPaymentService

        for payment in await CustomerPaymentService(
            self.session, actor_permissions=self.actor_permissions
        ).list_for_sales_invoice(tenant_id, row.id):
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.CUSTOMER_PAYMENT.value,
                    document_id=payment.id,
                    document_number=payment.document_number,
                    status=payment.status,
                    relationship="child",
                    document_date=payment.payment_date,
                    amount_summary=str(payment.amount_received),
                )
            )
        return related

    async def _require(
        self, tenant_id: UUID, invoice_id: UUID, *, for_update: bool = False
    ) -> SalesInvoice:
        row = await self.repo.get(tenant_id, invoice_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Sales invoice not found")
        return row

    async def _today(self, tenant_id: UUID) -> date:
        return today_in_timezone(await self.org.get_timezone(tenant_id))

    def _assert_version(self, row: SalesInvoice, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, tenant_id: UUID, row: SalesInvoice) -> dict[str, object]:
        customer = await self.customers.get(tenant_id, row.customer_id)
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "invoice_date": row.invoice_date.isoformat(),
            "customer": customer.name,
            "grand_total": str(row.grand_total),
            "tax_amount": str(row.tax_amount),
            "payment_status": row.payment_status,
            "cogs_status": row.cogs_status,
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
    account_id: UUID, amount: Decimal, *, credit_positive: bool, description: str
) -> JournalLineInput:
    if credit_positive:
        credit = amount if amount > _ZERO else _ZERO
        debit = -amount if amount < _ZERO else _ZERO
    else:
        debit = amount if amount > _ZERO else _ZERO
        credit = -amount if amount < _ZERO else _ZERO
    return JournalLineInput(
        account_id=account_id, debit=debit, credit=credit, description=description
    )


def _header_cogs_status(statuses: Sequence[str]) -> str:
    unique = set(statuses)
    if not unique or unique == {CogsStatus.NOT_APPLICABLE.value}:
        return CogsStatus.NOT_APPLICABLE.value
    material = unique - {CogsStatus.NOT_APPLICABLE.value}
    if material == {CogsStatus.POSTED.value}:
        return CogsStatus.POSTED.value
    if material == {CogsStatus.PENDING.value}:
        return CogsStatus.PENDING.value
    return CogsStatus.PARTIAL.value
