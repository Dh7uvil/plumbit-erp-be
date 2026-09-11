"""Sales order compose, totals, FX snapshot, and status transitions."""

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    ERP_MODULE,
    PROFORMA_INVOICE_CREATE,
    SALES_ORDER_ACKNOWLEDGE,
    SALES_ORDER_APPROVE,
    SALES_ORDER_CLOSE,
    SALES_ORDER_CONFIRM,
    SALES_ORDER_CREATE,
    SALES_ORDER_DELETE,
    SALES_ORDER_UPDATE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.outbox.service import OutboxService
from app.common.schemas.conversion import ConversionLineInput
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import QuantityProgress, RelatedDocumentRef
from app.common.services.audit import AuditWriter
from app.common.utils.conversion import (
    allocate_conversion_qty,
    copy_source_commercial_header,
    remaining_qty,
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
from app.core.enums import (
    AuditAction,
    BillingStatus,
    DiscountType,
    DocumentType,
    FulfillmentStatus,
    ItemType,
    PlaceOfSupply,
    SalesOrderStatus,
    TaxCategory,
    TaxTreatment,
)
from app.core.exceptions import (
    AlreadyAcknowledgedError,
    CustomerPoRequiredError,
    DocumentStaleError,
    InvalidStatusTransitionError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.crm.contacts.service import ContactService
from app.crm.customers.service import CustomerService
from app.db.session import transaction
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.service import (
    DocumentSequenceService,
    PaymentTermService,
    TaxService,
    TermsTemplateService,
)
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService
from app.erp.quotation.service import QuotationService
from app.erp.sales_orders.models import SalesOrder, SalesOrderLine
from app.erp.sales_orders.repository import SalesOrderRepository
from app.erp.sales_orders.schemas import (
    CustomerPoDuplicate,
    OrderTrackerResponse,
    OrderTrackerRow,
    ReservationShortfall,
    SalesOrderComposeDefaults,
    SalesOrderCreate,
    SalesOrderLineInput,
    SalesOrderLineResponse,
    SalesOrderResponse,
    SalesOrderUpdate,
)
from app.erp.sales_orders.workflow import assert_editable, next_status, transition_actions
from app.inventory_management.price_lists.service import PriceListService
from app.inventory_management.products.service import ProductService
from app.inventory_management.stock.availability import available_qty
from app.inventory_management.stock.service import StockService
from app.inventory_management.units.service import UnitService
from app.inventory_management.warehouses.service import WarehouseService

_ZERO = Decimal("0")
_ORDER_SERIES = "SO"
_ACTION_PERMISSIONS: dict[str, str] = {
    "submit": SALES_ORDER_UPDATE,
    "approve": SALES_ORDER_APPROVE,
    "reject": SALES_ORDER_APPROVE,
    "reopen": SALES_ORDER_UPDATE,
    "confirm": SALES_ORDER_CONFIRM,
    "close": SALES_ORDER_CLOSE,
    "cancel": SALES_ORDER_UPDATE,
    "acknowledge": SALES_ORDER_ACKNOWLEDGE,
}


class SalesOrderService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = SalesOrderRepository(session)
        self.org = OrganizationService(session)
        self.customers = CustomerService(session)
        self.contacts = ContactService(session)
        self.products = ProductService(session)
        self.stock = StockService(session)
        self.price_lists = PriceListService(session)
        self.units = UnitService(session)
        self.warehouses = WarehouseService(session)
        self.taxes = TaxService(session)
        self.payment_terms = PaymentTermService(session)
        self.terms = TermsTemplateService(session)
        self.sequences = DocumentSequenceService(session)
        self.currencies = CurrencyService(session)
        self.fx = ExchangeRateService(session)
        self.audit = AuditWriter(session)
        self.outbox = OutboxService(session)
        self.idempotency = IdempotencyService(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        fulfillment_status: str | None = None,
        billing_status: str | None = None,
        customer_id: UUID | None = None,
        branch_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        currency_id: UUID | None = None,
        salesperson_id: UUID | None = None,
        source_quotation_id: UUID | None = None,
        source_proforma_invoice_id: UUID | None = None,
    ) -> tuple[list[SalesOrderResponse], int]:
        requires_approval = await self.org.sales_order_requires_approval(tenant_id)
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if fulfillment_status is not None:
            filters["fulfillment_status"] = fulfillment_status
        if billing_status is not None:
            filters["billing_status"] = billing_status
        if customer_id is not None:
            filters["customer_id"] = customer_id
        if branch_id is not None:
            filters["branch_id"] = branch_id
        if warehouse_id is not None:
            filters["warehouse_id"] = warehouse_id
        if currency_id is not None:
            filters["currency_id"] = currency_id
        if salesperson_id is not None:
            filters["salesperson_id"] = salesperson_id
        if source_quotation_id is not None:
            filters["source_quotation_id"] = source_quotation_id
        if source_proforma_invoice_id is not None:
            filters["source_proforma_invoice_id"] = source_proforma_invoice_id
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
        )
        return [self._to_response(row, requires_approval=requires_approval) for row in rows], total

    async def get(self, tenant_id: UUID, sales_order_id: UUID) -> SalesOrderResponse:
        requires_approval = await self.org.sales_order_requires_approval(tenant_id)
        row = await self._require(tenant_id, sales_order_id)
        response = self._to_response(row, requires_approval=requires_approval)
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def compose_defaults(
        self, tenant_id: UUID, customer_id: UUID
    ) -> SalesOrderComposeDefaults:
        customer = await self.customers.get(tenant_id, customer_id)
        primary = await self.contacts.get_primary(tenant_id, customer_id)
        default_terms = await self.terms.get_default(tenant_id)
        default_warehouse = await self.warehouses.get_default(tenant_id)
        place = place_of_supply_from_address(customer.shipping_address)
        return SalesOrderComposeDefaults(
            customer_id=customer.id,
            customer_name=customer.name,
            customer_trn=customer.trn,
            tax_treatment=customer.tax_treatment,
            currency_id=customer.currency_id,
            price_list_id=customer.default_price_list_id,
            payment_terms_id=customer.payment_terms_id,
            salesperson_id=customer.salesperson_id,
            contact_id=primary.id if primary else None,
            warehouse_id=default_warehouse.id if default_warehouse else None,
            place_of_supply=place,
            bill_to_snapshot=format_address_snapshot(customer.billing_address),
            ship_to_snapshot=format_address_snapshot(customer.shipping_address),
            terms_and_conditions=default_terms.body if default_terms else None,
        )

    async def create(
        self, tenant_id: UUID, payload: SalesOrderCreate, *, actor_user_id: UUID
    ) -> SalesOrderResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            order_date = cast(date, header["order_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.SALES_ORDER,
                series=_ORDER_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, order_date),
                prefix=_ORDER_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": SalesOrderStatus.DRAFT.value,
                    "version": 1,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ERP_MODULE,
                entity_type="sales_order",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, row),
            )
            loaded = await self._require(tenant_id, row.id)
            requires_approval = await self.org.sales_order_requires_approval(tenant_id)
            return self._to_response(loaded, requires_approval=requires_approval)

    async def create_from_quotation(
        self,
        tenant_id: UUID,
        quotation_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        order_date: date | None = None,
        expected_shipment_date: date | None = None,
        reference_number: str | None = None,
        customer_po_number: str | None = None,
        customer_po_date: date | None = None,
        warehouse_id: UUID | None = None,
        branch_id: UUID | None = None,
        conversion_lines: Sequence[ConversionLineInput] | None = None,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> SalesOrderResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return SalesOrderResponse.model_validate(replay)
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
            payload = SalesOrderCreate(
                customer_id=quotation.customer_id,
                contact_id=quotation.contact_id,
                branch_id=quotation.branch_id if branch_id is None else branch_id,
                warehouse_id=warehouse_id,
                order_date=order_date,
                expected_shipment_date=expected_shipment_date,
                reference_number=reference_number,
                customer_po_number=customer_po_number,
                customer_po_date=customer_po_date,
                currency_id=quotation.currency_id,
                price_list_id=quotation.price_list_id,
                payment_terms_id=quotation.payment_terms_id,
                salesperson_id=quotation.salesperson_id,
                notes=quotation.notes,
                terms_and_conditions=quotation.terms_and_conditions,
                discount_type=quotation.discount_type,
                discount_value=quotation.discount_value,
                shipping_amount=quotation.shipping_amount,
                adjustment_amount=quotation.adjustment_amount,
                place_of_supply=quotation.place_of_supply,
                lines=[
                    SalesOrderLineInput(
                        product_id=source.product_id,
                        description=source.description,
                        quantity=qty,
                        unit_id=source.unit_id,
                        rate=source.rate,
                        discount_type=source.discount_type,
                        discount_value=source.discount_value,
                        tax_id=source.tax_id,
                    )
                    for source, qty in selected
                ],
            )
            header, line_rows = await self._build_draft(tenant_id, payload)
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
            order_date_value = cast(date, header["order_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.SALES_ORDER,
                series=_ORDER_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, order_date_value),
                prefix=_ORDER_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": SalesOrderStatus.DRAFT.value,
                    "version": 1,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ERP_MODULE,
                entity_type="sales_order",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, row),
            )
            await quotes._apply_converted(
                tenant_id,
                quotation_id,
                document_type=DocumentType.SALES_ORDER,
                document_id=row.id,
                actor_user_id=actor_user_id,
                expected_version=quotation.version,
                allocations=allocations,
            )
            loaded = await self._require(tenant_id, row.id)
            requires_approval = await self.org.sales_order_requires_approval(tenant_id)
            response = self._to_response(loaded, requires_approval=requires_approval)
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
        order_date: date | None = None,
        expected_shipment_date: date | None = None,
        customer_po_number: str | None = None,
        customer_po_date: date | None = None,
        warehouse_id: UUID | None = None,
        branch_id: UUID | None = None,
        conversion_lines: Sequence[ConversionLineInput] | None = None,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> SalesOrderResponse:
        from app.erp.proforma_invoices.service import ProformaInvoiceService

        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return SalesOrderResponse.model_validate(replay)
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
            payload = SalesOrderCreate(
                customer_id=pfi.customer_id,
                contact_id=pfi.contact_id,
                branch_id=pfi.branch_id if branch_id is None else branch_id,
                warehouse_id=warehouse_id,
                order_date=order_date,
                expected_shipment_date=expected_shipment_date,
                customer_po_number=customer_po_number,
                customer_po_date=customer_po_date,
                currency_id=pfi.currency_id,
                price_list_id=pfi.price_list_id,
                payment_terms_id=pfi.payment_terms_id,
                salesperson_id=pfi.salesperson_id,
                notes=pfi.notes,
                terms_and_conditions=pfi.terms_and_conditions,
                discount_type=pfi.discount_type,
                discount_value=pfi.discount_value,
                shipping_amount=pfi.shipping_amount,
                adjustment_amount=pfi.adjustment_amount,
                place_of_supply=pfi.place_of_supply,
                lines=[
                    SalesOrderLineInput(
                        product_id=source.product_id,
                        description=source.description,
                        quantity=qty,
                        unit_id=source.unit_id,
                        rate=source.rate,
                        discount_type=source.discount_type,
                        discount_value=source.discount_value,
                        tax_id=source.tax_id,
                    )
                    for source, qty in selected
                ],
            )
            header, line_rows = await self._build_draft(tenant_id, payload)
            header["source_proforma_invoice_id"] = pfi.id
            header["source_quotation_id"] = pfi.source_quotation_id
            copy_source_commercial_header(
                header,
                exchange_rate=pfi.exchange_rate,
                base_currency_id=pfi.base_currency_id,
                bill_to_snapshot=pfi.bill_to_snapshot,
                ship_to_snapshot=pfi.ship_to_snapshot,
            )
            for built, (source, _) in zip(line_rows, selected, strict=True):
                built["source_proforma_invoice_line_id"] = source.id
            order_date_value = cast(date, header["order_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.SALES_ORDER,
                series=_ORDER_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, order_date_value),
                prefix=_ORDER_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": SalesOrderStatus.DRAFT.value,
                    "version": 1,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ERP_MODULE,
                entity_type="sales_order",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, row),
            )
            await pfis._apply_converted(
                tenant_id,
                proforma_invoice_id,
                document_type=DocumentType.SALES_ORDER,
                document_id=row.id,
                actor_user_id=actor_user_id,
                expected_version=pfi.version,
                allocations=allocations,
            )
            if pfi.source_quotation_id is not None:
                quotes = QuotationService(self.session, actor_permissions=self.actor_permissions)
                quotation = await quotes.get(tenant_id, pfi.source_quotation_id)
                quote_allocations = [
                    (source.source_quotation_line_id, qty)
                    for source, qty in selected
                    if source.source_quotation_line_id is not None
                ]
                await quotes._apply_converted(
                    tenant_id,
                    pfi.source_quotation_id,
                    document_type=DocumentType.SALES_ORDER,
                    document_id=row.id,
                    actor_user_id=actor_user_id,
                    expected_version=quotation.version,
                    allocations=quote_allocations or None,
                )
            loaded = await self._require(tenant_id, row.id)
            requires_approval = await self.org.sales_order_requires_approval(tenant_id)
            response = self._to_response(loaded, requires_approval=requires_approval)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def update(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        payload: SalesOrderUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> SalesOrderResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, sales_order_id, for_update=True)
            old_values = await self._snapshot(tenant_id, existing)
            requires_approval = await self.org.sales_order_requires_approval(tenant_id)
            assert_editable(SalesOrderStatus(existing.status))
            self._assert_version(existing, expected_version)
            create_payload = await self._update_to_create(existing, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            header["source_quotation_id"] = existing.source_quotation_id
            header["source_proforma_invoice_id"] = existing.source_proforma_invoice_id
            if payload.lines is None:
                for built, existing_line in zip(line_rows, existing.lines, strict=True):
                    built["source_quotation_line_id"] = existing_line.source_quotation_line_id
                    built["source_proforma_invoice_line_id"] = (
                        existing_line.source_proforma_invoice_line_id
                    )
            await self.repo.update(tenant_id, sales_order_id, header)
            await self.repo.replace_lines(tenant_id, sales_order_id, line_rows)
            loaded = await self._require(tenant_id, sales_order_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ERP_MODULE,
                entity_type="sales_order",
                entity_id=sales_order_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded, requires_approval=requires_approval)

    async def submit(
        self, tenant_id: UUID, sales_order_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> SalesOrderResponse:
        return await self._transition(
            tenant_id, sales_order_id, "submit", actor_user_id, expected_version=expected_version
        )

    async def approve(
        self, tenant_id: UUID, sales_order_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> SalesOrderResponse:
        return await self._transition(
            tenant_id, sales_order_id, "approve", actor_user_id, expected_version=expected_version
        )

    async def reject(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> SalesOrderResponse:
        return await self._transition(
            tenant_id,
            sales_order_id,
            "reject",
            actor_user_id,
            expected_version=expected_version,
            reason=reason,
        )

    async def reopen(
        self, tenant_id: UUID, sales_order_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> SalesOrderResponse:
        return await self._transition(
            tenant_id, sales_order_id, "reopen", actor_user_id, expected_version=expected_version
        )

    async def confirm(
        self, tenant_id: UUID, sales_order_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> SalesOrderResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, sales_order_id, for_update=True)
            old_values = await self._snapshot(tenant_id, row)
            requires_approval = await self.org.sales_order_requires_approval(tenant_id)
            current = SalesOrderStatus(row.status)
            self._assert_version(row, expected_version)
            if current == SalesOrderStatus.DRAFT and requires_approval:
                raise ValidationError(
                    "This organization requires approval before a sales order can be confirmed"
                )
            target = next_status(current, "confirm")
            row.status = target.value
            row.confirmed_at = utcnow()
            row.confirmed_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            shortfalls = await self.apply_line_reservations(tenant_id, row)
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CONFIRM,
                module=ERP_MODULE,
                entity_type="sales_order",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            return self._to_response(
                row, requires_approval=requires_approval, reservation_shortfalls=shortfalls
            )

    async def close(
        self, tenant_id: UUID, sales_order_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> SalesOrderResponse:
        return await self._transition(
            tenant_id,
            sales_order_id,
            "close",
            actor_user_id,
            expected_version=expected_version,
            extra={"closed_at": utcnow(), "closed_by": actor_user_id},
        )

    async def cancel(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> SalesOrderResponse:
        return await self._transition(
            tenant_id,
            sales_order_id,
            "cancel",
            actor_user_id,
            expected_version=expected_version,
            reason=reason,
            extra={
                "cancelled_at": utcnow(),
                "cancelled_by": actor_user_id,
                "cancel_reason": reason,
            },
        )

    async def clone(
        self, tenant_id: UUID, sales_order_id: UUID, *, actor_user_id: UUID
    ) -> SalesOrderResponse:
        async with transaction(self.session):
            source = await self._require(tenant_id, sales_order_id)
            payload = SalesOrderCreate(
                customer_id=source.customer_id,
                contact_id=source.contact_id,
                branch_id=source.branch_id,
                warehouse_id=source.warehouse_id,
                order_date=None,
                expected_shipment_date=source.expected_shipment_date,
                reference_number=source.reference_number,
                customer_po_number=source.customer_po_number,
                customer_po_date=source.customer_po_date,
                currency_id=source.currency_id,
                price_list_id=source.price_list_id,
                payment_terms_id=source.payment_terms_id,
                salesperson_id=source.salesperson_id,
                notes=source.notes,
                terms_and_conditions=source.terms_and_conditions,
                discount_type=DiscountType(source.discount_type) if source.discount_type else None,
                discount_value=source.discount_value,
                shipping_amount=source.shipping_amount,
                adjustment_amount=source.adjustment_amount,
                place_of_supply=PlaceOfSupply(source.place_of_supply),
                lines=[
                    SalesOrderLineInput(
                        product_id=line.product_id,
                        description=line.description,
                        quantity=line.quantity,
                        unit_id=line.unit_id,
                        rate=line.rate,
                        discount_type=DiscountType(line.discount_type)
                        if line.discount_type
                        else None,
                        discount_value=line.discount_value,
                        tax_id=line.tax_id,
                    )
                    for line in source.lines
                ],
            )
            header, line_rows = await self._build_draft(tenant_id, payload)
            order_date = cast(date, header["order_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.SALES_ORDER,
                series=_ORDER_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, order_date),
                prefix=_ORDER_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": SalesOrderStatus.DRAFT.value,
                    "version": 1,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            new_values = await self._snapshot(tenant_id, row)
            new_values["cloned_from"] = source.document_number
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CLONE,
                module=ERP_MODULE,
                entity_type="sales_order",
                entity_id=row.id,
                new_values=new_values,
            )
            loaded = await self._require(tenant_id, row.id)
            requires_approval = await self.org.sales_order_requires_approval(tenant_id)
            return self._to_response(loaded, requires_approval=requires_approval)

    async def acknowledge(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> SalesOrderResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, sales_order_id, for_update=True)
            requires_approval = await self.org.sales_order_requires_approval(tenant_id)
            self._assert_version(row, expected_version)
            if SalesOrderStatus(row.status) != SalesOrderStatus.CONFIRMED:
                raise InvalidStatusTransitionError(
                    "Only a confirmed sales order can be acknowledged"
                )
            if not (row.customer_po_number or "").strip():
                raise CustomerPoRequiredError()
            if row.acknowledged_at is not None:
                raise AlreadyAcknowledgedError()
            old_values = await self._snapshot(tenant_id, row)
            row.acknowledged_at = utcnow()
            row.acknowledged_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.ACKNOWLEDGE,
                module=ERP_MODULE,
                entity_type="sales_order",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="erp.sales_order.acknowledged",
                aggregate_type="sales_order",
                aggregate_id=row.id,
                payload={"sales_order_id": str(row.id)},
                dedupe_key=f"sales-order-acknowledged:{row.id}",
            )
            return self._to_response(row, requires_approval=requires_approval)

    async def find_duplicate_customer_po(
        self,
        tenant_id: UUID,
        *,
        customer_id: UUID,
        customer_po_number: str,
        exclude_sales_order_id: UUID | None = None,
    ) -> builtins.list[CustomerPoDuplicate]:
        rows = await self.repo.find_by_customer_po(
            tenant_id,
            customer_id=customer_id,
            customer_po_number=customer_po_number.strip(),
            exclude_id=exclude_sales_order_id,
        )
        return [
            CustomerPoDuplicate(
                id=row.id,
                document_number=row.document_number,
                customer_po_number=row.customer_po_number,
                customer_po_date=row.customer_po_date,
                status=SalesOrderStatus(row.status),
            )
            for row in rows
        ]

    async def delete(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> SalesOrderResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, sales_order_id, for_update=True)
            requires_approval = await self.org.sales_order_requires_approval(tenant_id)
            current = SalesOrderStatus(row.status)
            if current != SalesOrderStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft sales orders can be deleted")
            self._assert_version(row, expected_version)
            response = self._to_response(row, requires_approval=requires_approval)
            old_values = await self._snapshot(tenant_id, row)
            await self.repo.soft_delete(tenant_id, sales_order_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="sales_order",
                entity_id=sales_order_id,
                old_values=old_values,
            )
            return response

    async def _transition(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        action: str,
        actor_user_id: UUID,
        *,
        expected_version: int,
        reason: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> SalesOrderResponse:
        action_map = {
            "submit": AuditAction.SUBMIT,
            "approve": AuditAction.APPROVE,
            "reject": AuditAction.REJECT,
            "reopen": AuditAction.UPDATE,
            "close": AuditAction.CLOSE,
            "cancel": AuditAction.CANCEL,
        }
        async with transaction(self.session):
            row = await self._require(tenant_id, sales_order_id, for_update=True)
            old_values = await self._snapshot(tenant_id, row)
            requires_approval = await self.org.sales_order_requires_approval(tenant_id)
            current = SalesOrderStatus(row.status)
            self._assert_version(row, expected_version)
            if action == "cancel":
                self._assert_cancellable(row, current)
            target = next_status(current, action)
            row.status = target.value
            row.version += 1
            row.updated_by = actor_user_id
            for name, value in (extra or {}).items():
                setattr(row, name, value)
            await self.session.flush()
            if action in {"cancel", "close"}:
                await self._release_line_reservations(tenant_id, row)
            elif action == "reopen" and target == SalesOrderStatus.CONFIRMED:
                await self.apply_line_reservations(tenant_id, row)
            await self.session.refresh(row, attribute_names=["updated_at"])
            new_values = await self._snapshot(tenant_id, row)
            if action == "reject" and reason:
                new_values["reason"] = reason
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=action_map[action],
                module=ERP_MODULE,
                entity_type="sales_order",
                entity_id=row.id,
                old_values=old_values,
                new_values=new_values,
            )
            return self._to_response(row, requires_approval=requires_approval)

    def _assert_cancellable(self, row: SalesOrder, current: SalesOrderStatus) -> None:
        if current != SalesOrderStatus.CONFIRMED:
            return
        if (
            row.fulfillment_status != FulfillmentStatus.NOT_DELIVERED.value
            or row.billing_status != BillingStatus.NOT_INVOICED.value
        ):
            raise InvalidStatusTransitionError(
                "A confirmed sales order cannot be cancelled after fulfillment "
                "or billing has started"
            )

    async def apply_line_reservations(
        self, tenant_id: UUID, row: SalesOrder
    ) -> builtins.list[ReservationShortfall]:
        """Recompute reserved qty from quantity - qty_delivered - qty_returned.

        Reservation must never fail a confirm. If available stock is short, reserve
        what exists and report the shortfall. Repeat calls are a no-op when the
        derived target already matches ``line.qty_reserved``. Caller owns the
        transaction.
        """

        if SalesOrderStatus(row.status) != SalesOrderStatus.CONFIRMED:
            return []
        warehouse_id = await self._reservation_warehouse_id(tenant_id, row)
        shortfalls: builtins.list[ReservationShortfall] = []
        for line in row.lines:
            if line.product_id is None:
                continue
            product = await self.products.get(tenant_id, line.product_id)
            if product.item_type == ItemType.SERVICE or not product.track_inventory:
                if line.qty_reserved > _ZERO and warehouse_id is not None:
                    locked = await self.stock.lock_balance(
                        tenant_id,
                        warehouse_id=warehouse_id,
                        product_id=line.product_id,
                        document_date=row.order_date,
                        assert_period=False,
                    )
                    await self.stock.release_reserved_locked(locked, qty=line.qty_reserved)
                    line.qty_reserved = _ZERO
                continue
            target = quantize_quantity(line.quantity - line.qty_delivered - line.qty_returned)
            if target < _ZERO:
                target = _ZERO
            current = quantize_quantity(line.qty_reserved)
            delta = quantize_quantity(target - current)
            if warehouse_id is None:
                if delta > _ZERO:
                    shortfalls.append(
                        ReservationShortfall(
                            sales_order_line_id=line.id,
                            product_id=line.product_id,
                            requested=target,
                            reserved=current,
                            shortfall=delta,
                        )
                    )
                continue
            locked = await self.stock.lock_balance(
                tenant_id,
                warehouse_id=warehouse_id,
                product_id=line.product_id,
                document_date=row.order_date,
                assert_period=False,
            )
            if delta > _ZERO:
                available = available_qty(
                    locked.row.qty_on_hand,
                    locked.row.qty_reserved,
                    locked.row.qty_quality_hold,
                )
                take = delta if available >= delta else max(available, _ZERO)
                take = quantize_quantity(take)
                if take > _ZERO:
                    await self.stock.reserve_locked(locked, qty=take)
                    current = quantize_quantity(current + take)
                    line.qty_reserved = current
                leftover = quantize_quantity(delta - take)
                if leftover > _ZERO:
                    shortfalls.append(
                        ReservationShortfall(
                            sales_order_line_id=line.id,
                            product_id=line.product_id,
                            requested=target,
                            reserved=current,
                            shortfall=leftover,
                        )
                    )
            elif delta < _ZERO:
                await self.stock.release_reserved_locked(locked, qty=-delta)
                line.qty_reserved = target
        await self.session.flush()
        return shortfalls

    async def apply_line_deliveries(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        deliveries: Mapping[UUID, Decimal],
    ) -> None:
        """Caller owns the transaction. qty may be negative to reverse a delivery note."""

        row = await self._require(tenant_id, sales_order_id, for_update=True)
        by_id = {line.id: line for line in row.lines}
        for line_id, qty in deliveries.items():
            line = by_id.get(line_id)
            if line is None:
                raise ValidationError("Sales order line not found on this order")
            line.qty_delivered = quantize_quantity(line.qty_delivered + qty)
            if line.qty_delivered < _ZERO:
                raise ValidationError("Delivered quantity cannot be negative")
        self._refresh_fulfillment_status(row)
        if SalesOrderStatus(row.status) == SalesOrderStatus.CONFIRMED:
            await self.apply_line_reservations(tenant_id, row)
        await self.session.flush()

    async def apply_line_returns(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        returns: Mapping[UUID, Decimal],
    ) -> None:
        """Caller owns the transaction. qty may be negative to reverse a return.

        Does not re-reserve remaining undelivered quantity.
        """

        row = await self._require(tenant_id, sales_order_id, for_update=True)
        by_id = {line.id: line for line in row.lines}
        for line_id, qty in returns.items():
            line = by_id.get(line_id)
            if line is None:
                raise ValidationError("Sales order line not found on this order")
            line.qty_returned = quantize_quantity(line.qty_returned + qty)
            if line.qty_returned < _ZERO:
                raise ValidationError("Returned quantity cannot be negative")
        self._refresh_fulfillment_status(row)
        await self.session.flush()

    async def apply_line_invoices(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        invoices: Mapping[UUID, Decimal],
    ) -> None:
        """Caller owns the transaction. qty may be negative to reverse an invoice."""

        row = await self._require(tenant_id, sales_order_id, for_update=True)
        by_id = {line.id: line for line in row.lines}
        for line_id, qty in invoices.items():
            line = by_id.get(line_id)
            if line is None:
                raise ValidationError("Sales order line not found on this order")
            line.qty_invoiced = quantize_quantity(line.qty_invoiced + qty)
            if line.qty_invoiced < _ZERO:
                raise ValidationError("Invoiced quantity cannot be negative")
        self._refresh_billing_status(row)
        await self.session.flush()

    def _refresh_billing_status(self, row: SalesOrder) -> None:
        if not row.lines:
            row.billing_status = BillingStatus.NOT_INVOICED.value
            return
        states: builtins.list[str] = []
        for line in row.lines:
            if line.qty_invoiced <= _ZERO:
                states.append("none")
            elif line.qty_invoiced >= line.quantity:
                states.append("full")
            else:
                states.append("partial")
        if all(item == "none" for item in states):
            row.billing_status = BillingStatus.NOT_INVOICED.value
        elif all(item == "full" for item in states):
            row.billing_status = BillingStatus.INVOICED.value
        else:
            row.billing_status = BillingStatus.PARTIALLY_INVOICED.value

    async def deliverable_lines(
        self, tenant_id: UUID, sales_order_id: UUID
    ) -> builtins.list[SalesOrderLine]:
        row = await self._require(tenant_id, sales_order_id)
        if SalesOrderStatus(row.status) != SalesOrderStatus.CONFIRMED:
            raise ValidationError("Delivery notes can only be created from a confirmed sales order")
        return [line for line in row.lines if self._outstanding_delivery(line) > _ZERO]

    def outstanding_delivery(self, line: SalesOrderLine) -> Decimal:
        return self._outstanding_delivery(line)

    async def tracker(self, tenant_id: UUID, sales_order_id: UUID) -> OrderTrackerResponse:
        """Read-only projection of related documents. Payment rows join in a later stage."""

        from app.erp.proforma_invoices.service import ProformaInvoiceService
        from app.erp.purchase_orders.service import PurchaseOrderService
        from app.inventory_management.delivery_notes.repository import DeliveryNoteRepository
        from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository
        from app.inventory_management.packages.repository import PackageRepository
        from app.inventory_management.quality_inspections.repository import (
            QualityInspectionRepository,
        )
        from app.inventory_management.sales_returns.repository import SalesReturnRepository
        from app.inventory_management.shipments.repository import ShipmentRepository

        row = await self._require(tenant_id, sales_order_id)
        rows: builtins.list[OrderTrackerRow] = []
        if row.source_quotation_id is not None:
            from app.erp.quotation.service import QuotationService as QuoteLookup

            quote = await QuoteLookup(
                self.session, actor_permissions=self.actor_permissions
            ).get(tenant_id, row.source_quotation_id)
            rows.append(
                self._tracker_row(
                    stage="quotation",
                    document_type=DocumentType.QUOTATION.value,
                    document_id=quote.id,
                    document_number=quote.document_number,
                    status=quote.status.value,
                    document_date=quote.document_date,
                    quantity_summary=self._qty_summary([line.quantity for line in quote.lines]),
                )
            )
        if row.source_proforma_invoice_id is not None:
            pfi = await ProformaInvoiceService(
                self.session, actor_permissions=self.actor_permissions
            ).get(tenant_id, row.source_proforma_invoice_id)
            rows.append(
                self._tracker_row(
                    stage="proforma_invoice",
                    document_type=DocumentType.PROFORMA_INVOICE.value,
                    document_id=pfi.id,
                    document_number=pfi.document_number,
                    status=pfi.status.value,
                    document_date=pfi.document_date,
                    quantity_summary=self._qty_summary([line.quantity for line in pfi.lines]),
                )
            )
        else:
            rows.append(
                self._tracker_pending("proforma_invoice", DocumentType.PROFORMA_INVOICE.value)
            )

        rows.append(
            self._tracker_row(
                stage="sales_order",
                document_type=DocumentType.SALES_ORDER.value,
                document_id=row.id,
                document_number=row.document_number,
                status=row.status,
                document_date=row.order_date,
                quantity_summary=self._qty_summary([line.quantity for line in row.lines]),
            )
        )

        purchase_orders = PurchaseOrderService(
            self.session, actor_permissions=self.actor_permissions
        )
        coverage = await purchase_orders.coverage_for_sales_order(tenant_id, sales_order_id)
        po_seen: dict[UUID, OrderTrackerRow] = {}
        for line in coverage.lines:
            for ref in line.purchase_orders:
                if ref.id in po_seen:
                    continue
                po_seen[ref.id] = self._tracker_row(
                    stage="purchase_order",
                    document_type=DocumentType.PURCHASE_ORDER.value,
                    document_id=ref.id,
                    document_number=ref.document_number,
                    status=ref.status.value,
                    document_date=None,
                    quantity_summary=self._qty_summary([ref.quantity]),
                )
        if po_seen:
            rows.extend(po_seen.values())
        else:
            rows.append(self._tracker_pending("purchase_order", DocumentType.PURCHASE_ORDER.value))

        receipts = await GoodsReceiptRepository(self.session).list_for_purchase_orders(
            tenant_id, list(po_seen)
        )
        if receipts:
            for receipt in receipts:
                rows.append(
                    self._tracker_row(
                        stage="goods_receipt",
                        document_type=DocumentType.GOODS_RECEIPT.value,
                        document_id=receipt.id,
                        document_number=receipt.document_number,
                        status=receipt.status,
                        document_date=receipt.document_date,
                        quantity_summary=self._qty_summary(
                            [line.quantity for line in receipt.lines]
                        ),
                    )
                )
        else:
            rows.append(self._tracker_pending("goods_receipt", DocumentType.GOODS_RECEIPT.value))

        inspections: builtins.list[OrderTrackerRow] = []
        qc_repo = QualityInspectionRepository(self.session)
        for receipt in receipts:
            for inspection in await qc_repo.list_for_goods_receipt(tenant_id, receipt.id):
                inspections.append(
                    self._tracker_row(
                        stage="quality_inspection",
                        document_type=DocumentType.QUALITY_INSPECTION.value,
                        document_id=inspection.id,
                        document_number=inspection.document_number,
                        status=inspection.status,
                        document_date=inspection.inspection_date,
                        quantity_summary=self._qty_summary(
                            [line.qty_inspected for line in inspection.lines]
                        ),
                    )
                )
        if inspections:
            rows.extend(inspections)
        else:
            rows.append(
                self._tracker_pending("quality_inspection", DocumentType.QUALITY_INSPECTION.value)
            )

        packages = await PackageRepository(self.session).list_for_sales_order(
            tenant_id, sales_order_id
        )
        if packages:
            for package in packages:
                rows.append(
                    self._tracker_row(
                        stage="package",
                        document_type=DocumentType.PACKAGE.value,
                        document_id=package.id,
                        document_number=package.document_number,
                        status=package.status,
                        document_date=package.created_at.date(),
                        quantity_summary=self._qty_summary(
                            [line.quantity for line in package.lines]
                        ),
                    )
                )
        else:
            rows.append(self._tracker_pending("package", DocumentType.PACKAGE.value))

        notes = await DeliveryNoteRepository(self.session).list_for_sales_order(
            tenant_id, sales_order_id
        )
        if notes:
            for note in notes:
                rows.append(
                    self._tracker_row(
                        stage="delivery_note",
                        document_type=DocumentType.DELIVERY_NOTE.value,
                        document_id=note.id,
                        document_number=note.document_number,
                        status=note.status,
                        document_date=note.document_date,
                        quantity_summary=self._qty_summary([line.quantity for line in note.lines]),
                    )
                )
        else:
            rows.append(self._tracker_pending("delivery_note", DocumentType.DELIVERY_NOTE.value))

        shipment_ids = [note.shipment_id for note in notes if note.shipment_id is not None]
        shipments = await ShipmentRepository(self.session).list_by_ids(tenant_id, shipment_ids)
        if shipments:
            for shipment in shipments:
                rows.append(
                    self._tracker_row(
                        stage="shipment",
                        document_type=DocumentType.SHIPMENT.value,
                        document_id=shipment.id,
                        document_number=shipment.document_number,
                        status=shipment.status,
                        document_date=shipment.etd or shipment.created_at.date(),
                        quantity_summary=(
                            str(shipment.total_packages)
                            if shipment.total_packages is not None
                            else None
                        ),
                    )
                )
        else:
            rows.append(self._tracker_pending("shipment", DocumentType.SHIPMENT.value))

        returns = await SalesReturnRepository(self.session).list_for_sales_order(
            tenant_id, sales_order_id
        )
        if returns:
            for item in returns:
                rows.append(
                    self._tracker_row(
                        stage="sales_return",
                        document_type=DocumentType.SALES_RETURN.value,
                        document_id=item.id,
                        document_number=item.document_number,
                        status=item.status,
                        document_date=item.document_date,
                        quantity_summary=self._qty_summary([line.quantity for line in item.lines]),
                    )
                )
        else:
            rows.append(self._tracker_pending("sales_return", DocumentType.SALES_RETURN.value))

        from app.erp.sales_invoices.repository import SalesInvoiceRepository

        invoices = await SalesInvoiceRepository(self.session).list_for_sales_order(
            tenant_id, sales_order_id
        )
        if invoices:
            for item in invoices:
                rows.append(
                    self._tracker_row(
                        stage="sales_invoice",
                        document_type=DocumentType.SALES_INVOICE.value,
                        document_id=item.id,
                        document_number=item.document_number,
                        status=item.status,
                        document_date=item.invoice_date,
                        quantity_summary=self._qty_summary(
                            [line.quantity for line in item.lines]
                        ),
                    )
                )
        else:
            rows.append(
                self._tracker_pending("sales_invoice", DocumentType.SALES_INVOICE.value)
            )

        from app.erp.credit_notes.repository import CreditNoteRepository

        credit_notes: builtins.list[OrderTrackerRow] = []
        cn_repo = CreditNoteRepository(self.session)
        for invoice in invoices:
            for note in await cn_repo.list_for_sales_invoice(tenant_id, invoice.id):
                credit_notes.append(
                    self._tracker_row(
                        stage="credit_note",
                        document_type=DocumentType.CREDIT_NOTE.value,
                        document_id=note.id,
                        document_number=note.document_number,
                        status=note.status,
                        document_date=note.credit_note_date,
                        quantity_summary=self._qty_summary(
                            [line.quantity for line in note.lines]
                        ),
                    )
                )
        if credit_notes:
            rows.extend(credit_notes)
        else:
            rows.append(self._tracker_pending("credit_note", DocumentType.CREDIT_NOTE.value))

        from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository
        from app.erp.debit_notes.repository import DebitNoteRepository

        bill_rows: builtins.list[OrderTrackerRow] = []
        pi_repo = PurchaseInvoiceRepository(self.session)
        dn_repo = DebitNoteRepository(self.session)
        debit_rows: builtins.list[OrderTrackerRow] = []
        for po_id in po_seen:
            for bill in await pi_repo.list_for_purchase_order(tenant_id, po_id):
                bill_rows.append(
                    self._tracker_row(
                        stage="purchase_invoice",
                        document_type=DocumentType.PURCHASE_INVOICE.value,
                        document_id=bill.id,
                        document_number=bill.document_number,
                        status=bill.status,
                        document_date=bill.invoice_date,
                        quantity_summary=self._qty_summary(
                            [line.quantity for line in bill.lines]
                        ),
                    )
                )
                for debit in await dn_repo.list_for_purchase_invoice(tenant_id, bill.id):
                    debit_rows.append(
                        self._tracker_row(
                            stage="debit_note",
                            document_type=DocumentType.DEBIT_NOTE.value,
                            document_id=debit.id,
                            document_number=debit.document_number,
                            status=debit.status,
                            document_date=debit.debit_note_date,
                            quantity_summary=self._qty_summary(
                                [line.quantity for line in debit.lines]
                            ),
                        )
                    )
        if bill_rows:
            rows.extend(bill_rows)
        else:
            rows.append(
                self._tracker_pending("purchase_invoice", DocumentType.PURCHASE_INVOICE.value)
            )
        if debit_rows:
            rows.extend(debit_rows)
        else:
            rows.append(self._tracker_pending("debit_note", DocumentType.DEBIT_NOTE.value))

        rows.append(self._tracker_pending("customer_payment", "CUSTOMER_PAYMENT"))
        return OrderTrackerResponse(sales_order_id=row.id, rows=rows)

    def _tracker_row(
        self,
        *,
        stage: str,
        document_type: str,
        document_id: UUID,
        document_number: str,
        status: str,
        document_date: date | None,
        quantity_summary: str | None,
    ) -> OrderTrackerRow:
        return OrderTrackerRow(
            stage=stage,
            document_type=document_type,
            document_id=document_id,
            document_number=document_number,
            status=status,
            document_date=document_date,
            quantity_summary=quantity_summary,
        )

    def _tracker_pending(self, stage: str, document_type: str) -> OrderTrackerRow:
        return OrderTrackerRow(
            stage=stage,
            document_type=document_type,
            status="PENDING",
        )

    def _qty_summary(self, quantities: Sequence[Decimal]) -> str:
        total = sum(quantities, _ZERO)
        return f"{len(quantities)} lines · qty {total}"

    def _outstanding_delivery(self, line: SalesOrderLine) -> Decimal:
        outstanding = quantize_quantity(line.quantity - line.qty_delivered)
        return outstanding if outstanding > _ZERO else _ZERO

    async def _release_line_reservations(self, tenant_id: UUID, row: SalesOrder) -> None:
        warehouse_id = row.warehouse_id
        if warehouse_id is None:
            default_warehouse = await self.warehouses.get_default(tenant_id)
            warehouse_id = default_warehouse.id if default_warehouse is not None else None
        for line in row.lines:
            reserved = quantize_quantity(line.qty_reserved)
            if reserved <= _ZERO or line.product_id is None:
                line.qty_reserved = _ZERO
                continue
            if warehouse_id is None:
                line.qty_reserved = _ZERO
                continue
            locked = await self.stock.lock_balance(
                tenant_id,
                warehouse_id=warehouse_id,
                product_id=line.product_id,
                document_date=row.order_date,
                assert_period=False,
            )
            await self.stock.release_reserved_locked(locked, qty=reserved)
            line.qty_reserved = _ZERO
        await self.session.flush()

    async def _reservation_warehouse_id(self, tenant_id: UUID, row: SalesOrder) -> UUID | None:
        if row.warehouse_id is not None:
            return row.warehouse_id
        default_warehouse = await self.warehouses.get_default(tenant_id)
        if default_warehouse is None:
            return None
        row.warehouse_id = default_warehouse.id
        return default_warehouse.id

    def _refresh_fulfillment_status(self, row: SalesOrder) -> None:
        if not row.lines:
            row.fulfillment_status = FulfillmentStatus.NOT_DELIVERED.value
            return
        states: builtins.list[str] = []
        for line in row.lines:
            net = quantize_quantity(line.qty_delivered - line.qty_returned)
            if net <= _ZERO:
                states.append("none")
            elif net >= line.quantity:
                states.append("full")
            else:
                states.append("partial")
        if all(item == "none" for item in states):
            row.fulfillment_status = FulfillmentStatus.NOT_DELIVERED.value
        elif all(item == "full" for item in states):
            row.fulfillment_status = FulfillmentStatus.DELIVERED.value
        else:
            row.fulfillment_status = FulfillmentStatus.PARTIALLY_DELIVERED.value

    async def _build_draft(
        self, tenant_id: UUID, payload: SalesOrderCreate
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
        if payload.payment_terms_id is not None:
            await self.payment_terms.require_id(tenant_id, payload.payment_terms_id)
        if payload.price_list_id is not None:
            await self.price_lists.require_id(tenant_id, payload.price_list_id)

        warehouse_id = payload.warehouse_id
        if warehouse_id is None:
            default_warehouse = await self.warehouses.get_default(tenant_id)
            warehouse_id = default_warehouse.id if default_warehouse else None
        else:
            await self.warehouses.require_id(tenant_id, warehouse_id)

        currency_id = payload.currency_id or customer.currency_id
        await self.currencies.require_id(tenant_id, currency_id)
        base = await self.currencies.get_base(tenant_id)
        order_date = payload.order_date or await self._today(tenant_id)
        resolved = await self.fx.resolve(
            tenant_id,
            from_currency_id=currency_id,
            to_currency_id=base.id,
            on_date=order_date,
        )

        place = payload.place_of_supply or place_of_supply_from_address(customer.shipping_address)
        terms_body = payload.terms_and_conditions
        if terms_body is None and payload.terms_template_id is not None:
            template = await self.terms.get(tenant_id, payload.terms_template_id)
            terms_body = template.body
        if terms_body is None:
            default_terms = await self.terms.get_default(tenant_id)
            terms_body = default_terms.body if default_terms else None

        price_list_id = payload.price_list_id or customer.default_price_list_id
        line_rows, line_nets, line_taxes = await self._build_lines(
            tenant_id,
            payload.lines,
            tax_treatment=customer.tax_treatment,
            place_of_supply=place,
            price_list_id=price_list_id,
        )
        subtotal, doc_discount, tax_total, grand = compute_header_totals(
            line_nets=line_nets,
            line_taxes=line_taxes,
            discount_type=payload.discount_type,
            discount_value=payload.discount_value,
            shipping_amount=quantize_money(payload.shipping_amount),
            adjustment_amount=quantize_money(payload.adjustment_amount),
        )
        header: dict[str, object] = {
            "order_date": order_date,
            "expected_shipment_date": payload.expected_shipment_date,
            "reference_number": payload.reference_number,
            "customer_po_number": payload.customer_po_number,
            "customer_po_date": payload.customer_po_date,
            "branch_id": payload.branch_id,
            "warehouse_id": warehouse_id,
            "customer_id": customer.id,
            "contact_id": payload.contact_id,
            "customer_trn": customer.trn,
            "tax_treatment": customer.tax_treatment.value,
            "place_of_supply": place.value,
            "currency_id": currency_id,
            "base_currency_id": base.id,
            "exchange_rate": resolved.rate,
            "price_list_id": price_list_id,
            "payment_terms_id": payload.payment_terms_id or customer.payment_terms_id,
            "salesperson_id": payload.salesperson_id or customer.salesperson_id,
            "notes": payload.notes,
            "terms_and_conditions": terms_body,
            "bill_to_snapshot": format_address_snapshot(customer.billing_address),
            "ship_to_snapshot": format_address_snapshot(customer.shipping_address),
            "discount_type": payload.discount_type.value if payload.discount_type else None,
            "discount_value": payload.discount_value,
            "discount_amount": doc_discount,
            "shipping_amount": quantize_money(payload.shipping_amount),
            "adjustment_amount": quantize_money(payload.adjustment_amount),
            "subtotal": subtotal,
            "tax_amount": tax_total,
            "grand_total": grand,
            "foreign_amount": grand,
            "base_amount": quantize_money(grand * resolved.rate),
            "fulfillment_status": FulfillmentStatus.NOT_DELIVERED.value,
            "billing_status": BillingStatus.NOT_INVOICED.value,
        }
        return header, line_rows

    async def _build_lines(
        self,
        tenant_id: UUID,
        lines: Sequence[SalesOrderLineInput],
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
                    "discount_type": line.discount_type.value if line.discount_type else None,
                    "discount_value": line.discount_value,
                    "discount_amount": line_discount,
                    "tax_id": chosen_tax.id,
                    "tax_rate": chosen_tax.rate,
                    "tax_amount": tax_amount,
                    "amount": net,
                    "qty_delivered": _ZERO,
                    "qty_returned": _ZERO,
                    "qty_reserved": _ZERO,
                    "qty_invoiced": _ZERO,
                    "qty_converted": _ZERO,
                }
            )
            nets.append(net)
            taxes.append(tax_amount)
        return built, nets, taxes

    async def _update_to_create(
        self, existing: SalesOrder, payload: SalesOrderUpdate
    ) -> SalesOrderCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        lines = values.get("lines")
        line_inputs = (
            [SalesOrderLineInput.model_validate(item) for item in lines]
            if lines is not None
            else [
                SalesOrderLineInput(
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    tax_id=line.tax_id,
                )
                for line in existing.lines
            ]
        )
        return SalesOrderCreate(
            customer_id=existing.customer_id,
            contact_id=values.get("contact_id", existing.contact_id),
            branch_id=values.get("branch_id", existing.branch_id),
            warehouse_id=values.get("warehouse_id", existing.warehouse_id),
            order_date=values.get("order_date", existing.order_date),
            expected_shipment_date=values.get(
                "expected_shipment_date", existing.expected_shipment_date
            ),
            reference_number=values.get("reference_number", existing.reference_number),
            customer_po_number=values.get("customer_po_number", existing.customer_po_number),
            customer_po_date=values.get("customer_po_date", existing.customer_po_date),
            currency_id=values.get("currency_id", existing.currency_id),
            price_list_id=values.get("price_list_id", existing.price_list_id),
            payment_terms_id=values.get("payment_terms_id", existing.payment_terms_id),
            salesperson_id=values.get("salesperson_id", existing.salesperson_id),
            notes=values.get("notes", existing.notes),
            terms_and_conditions=values.get("terms_and_conditions", existing.terms_and_conditions),
            discount_type=values.get(
                "discount_type",
                DiscountType(existing.discount_type) if existing.discount_type else None,
            ),
            discount_value=values.get("discount_value", existing.discount_value),
            shipping_amount=values.get("shipping_amount", existing.shipping_amount),
            adjustment_amount=values.get("adjustment_amount", existing.adjustment_amount),
            place_of_supply=values.get("place_of_supply", PlaceOfSupply(existing.place_of_supply)),
            lines=line_inputs,
        )

    def _available_actions(self, row: SalesOrder, *, requires_approval: bool) -> builtins.list[str]:
        status = SalesOrderStatus(row.status)
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            if action == "confirm" and status == SalesOrderStatus.DRAFT and requires_approval:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if (
            status == SalesOrderStatus.CONFIRMED
            and (row.customer_po_number or "").strip()
            and row.acknowledged_at is None
            and has_permission(self.actor_permissions, SALES_ORDER_ACKNOWLEDGE)
        ):
            actions.append("acknowledge")
        if has_permission(self.actor_permissions, SALES_ORDER_CREATE):
            actions.append("clone")
        if status == SalesOrderStatus.DRAFT and has_permission(
            self.actor_permissions, SALES_ORDER_DELETE
        ):
            actions.append("delete")
        if status == SalesOrderStatus.CONFIRMED and has_permission(
            self.actor_permissions, PROFORMA_INVOICE_CREATE
        ):
            actions.append("create_proforma")
        return actions

    def _to_response(
        self,
        row: SalesOrder,
        *,
        requires_approval: bool,
        reservation_shortfalls: builtins.list[ReservationShortfall] | None = None,
    ) -> SalesOrderResponse:
        status = SalesOrderStatus(row.status)
        return SalesOrderResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=False,
            reference_number=row.reference_number,
            customer_po_number=row.customer_po_number,
            customer_po_date=row.customer_po_date,
            order_date=row.order_date,
            document_date=row.order_date,
            expected_shipment_date=row.expected_shipment_date,
            branch_id=row.branch_id,
            warehouse_id=row.warehouse_id,
            customer_id=row.customer_id,
            contact_id=row.contact_id,
            customer_trn=row.customer_trn,
            tax_treatment=TaxTreatment(row.tax_treatment),
            place_of_supply=PlaceOfSupply(row.place_of_supply),
            currency_id=row.currency_id,
            base_currency_id=row.base_currency_id,
            exchange_rate=row.exchange_rate,
            price_list_id=row.price_list_id,
            payment_terms_id=row.payment_terms_id,
            salesperson_id=row.salesperson_id,
            notes=row.notes,
            terms_and_conditions=row.terms_and_conditions,
            bill_to_snapshot=row.bill_to_snapshot,
            ship_to_snapshot=row.ship_to_snapshot,
            discount_type=DiscountType(row.discount_type) if row.discount_type else None,
            discount_value=row.discount_value,
            discount_amount=row.discount_amount,
            shipping_amount=row.shipping_amount,
            adjustment_amount=row.adjustment_amount,
            subtotal=row.subtotal,
            tax_amount=row.tax_amount,
            grand_total=row.grand_total,
            foreign_amount=row.foreign_amount,
            base_amount=row.base_amount,
            fulfillment_status=FulfillmentStatus(row.fulfillment_status),
            billing_status=BillingStatus(row.billing_status),
            source_quotation_id=row.source_quotation_id,
            source_proforma_invoice_id=row.source_proforma_invoice_id,
            confirmed_at=row.confirmed_at,
            confirmed_by=row.confirmed_by,
            closed_at=row.closed_at,
            closed_by=row.closed_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            acknowledged_at=row.acknowledged_at,
            acknowledged_by=row.acknowledged_by,
            available_actions=self._available_actions(row, requires_approval=requires_approval),
            quantity_progress=self._quantity_progress(row),
            related_documents=[],
            lines=[SalesOrderLineResponse.model_validate(line) for line in row.lines],
            reservation_shortfalls=reservation_shortfalls or [],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _quantity_progress(self, row: SalesOrder) -> QuantityProgress:
        ordered = sum((line.quantity for line in row.lines), _ZERO)
        delivered = sum((line.qty_delivered for line in row.lines), _ZERO)
        invoiced = sum((line.qty_invoiced for line in row.lines), _ZERO)
        return QuantityProgress(
            ordered=ordered,
            fulfilled=delivered,
            invoiced=invoiced,
            remaining_to_fulfill=remaining_qty(ordered, delivered),
            remaining_to_invoice=remaining_qty(ordered, invoiced),
        )

    async def _related_documents(
        self, tenant_id: UUID, row: SalesOrder
    ) -> builtins.list[RelatedDocumentRef]:
        from app.erp.credit_notes.repository import CreditNoteRepository
        from app.erp.proforma_invoices.repository import ProformaInvoiceRepository
        from app.erp.quotation.repository import QuotationRepository
        from app.erp.sales_invoices.repository import SalesInvoiceRepository
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
        for item in await ProformaInvoiceRepository(self.session).list_for_sales_order(
            tenant_id, row.id
        ):
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.PROFORMA_INVOICE.value,
                    document_id=item.id,
                    document_number=item.document_number,
                    status=item.status,
                    relationship="child",
                    document_date=item.proforma_date,
                    quantity_summary=self._qty_summary([line.quantity for line in item.lines]),
                )
            )
        for item in await DeliveryNoteRepository(self.session).list_for_sales_order(
            tenant_id, row.id
        ):
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.DELIVERY_NOTE.value,
                    document_id=item.id,
                    document_number=item.document_number,
                    status=item.status,
                    relationship="child",
                    document_date=item.document_date,
                    quantity_summary=self._qty_summary([line.quantity for line in item.lines]),
                )
            )
        invoices = await SalesInvoiceRepository(self.session).list_for_sales_order(
            tenant_id, row.id
        )
        cn_repo = CreditNoteRepository(self.session)
        for item in invoices:
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.SALES_INVOICE.value,
                    document_id=item.id,
                    document_number=item.document_number,
                    status=item.status,
                    relationship="child",
                    document_date=item.invoice_date,
                    quantity_summary=self._qty_summary([line.quantity for line in item.lines]),
                )
            )
            for note in await cn_repo.list_for_sales_invoice(tenant_id, item.id):
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.CREDIT_NOTE.value,
                        document_id=note.id,
                        document_number=note.document_number,
                        status=note.status,
                        relationship="child",
                        document_date=note.credit_note_date,
                        quantity_summary=self._qty_summary(
                            [line.quantity for line in note.lines]
                        ),
                    )
                )
        return related

    async def _today(self, tenant_id: UUID) -> date:
        return today_in_timezone(await self.org.get_timezone(tenant_id))

    def _assert_version(self, row: SalesOrder, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, tenant_id: UUID, row: SalesOrder) -> dict[str, object]:
        branch_name: str | None = None
        if row.branch_id is not None:
            branch_name = (await self.org.get_branch(tenant_id, row.branch_id)).name
        customer = await self.customers.get(tenant_id, row.customer_id)
        contact_name: str | None = None
        if row.contact_id is not None:
            contact_name = (await self.contacts.get(tenant_id, row.contact_id)).name
        currency = await self.currencies.get(tenant_id, row.currency_id)
        price_list_name: str | None = None
        if row.price_list_id is not None:
            price_list = await self.price_lists.get(tenant_id, row.price_list_id)
            price_list_name = price_list.name
        payment_term_name: str | None = None
        if row.payment_terms_id is not None:
            payment_term = await self.payment_terms.get(tenant_id, row.payment_terms_id)
            payment_term_name = payment_term.name
        warehouse_name: str | None = None
        if row.warehouse_id is not None:
            warehouse_name = (await self.warehouses.get(tenant_id, row.warehouse_id)).name
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "order_date": row.order_date,
            "reference_number": row.reference_number,
            "branch": branch_name,
            "warehouse": warehouse_name,
            "customer": customer.name,
            "contact": contact_name,
            "tax_treatment": row.tax_treatment,
            "place_of_supply": row.place_of_supply,
            "currency": currency.code,
            "exchange_rate": row.exchange_rate,
            "price_list": price_list_name,
            "payment_terms": payment_term_name,
            "salesperson": await self.org.employee_audit_label(tenant_id, row.salesperson_id),
            "discount_type": row.discount_type,
            "discount_value": row.discount_value,
            "discount_amount": row.discount_amount,
            "shipping_amount": row.shipping_amount,
            "adjustment_amount": row.adjustment_amount,
            "subtotal": row.subtotal,
            "tax_amount": row.tax_amount,
            "grand_total": row.grand_total,
            "foreign_amount": row.foreign_amount,
            "base_amount": row.base_amount,
            "fulfillment_status": row.fulfillment_status,
            "billing_status": row.billing_status,
            "customer_po_number": row.customer_po_number,
        }

    async def _require(
        self, tenant_id: UUID, sales_order_id: UUID, *, for_update: bool = False
    ) -> SalesOrder:
        row = await self.repo.get(tenant_id, sales_order_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Sales order not found")
        return row
