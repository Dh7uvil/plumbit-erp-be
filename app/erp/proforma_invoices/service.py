"""Proforma invoice compose, totals, milestones, and status transitions."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    PROFORMA_INVOICE_CONFIRM,
    PROFORMA_INVOICE_CREATE,
    PROFORMA_INVOICE_DELETE,
    PROFORMA_INVOICE_SEND,
    PROFORMA_INVOICE_UPDATE,
    SALES_INVOICE_CREATE,
    SALES_MODULE,
    SALES_ORDER_CREATE,
)
from app.auth.org_service import OrganizationService
from app.common.outbox.service import OutboxService
from app.common.print.schemas import PrintDocumentResponse
from app.common.print.service import PrintService
from app.common.schemas.conversion import ConversionLineInput
from app.common.schemas.filters import BaseFilter
from app.common.schemas.packing import packing_persist
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.services.audit import AuditWriter
from app.common.utils.conversion import (
    allocate_conversion_qty,
    copy_source_commercial_header,
    quantity_summary,
    remaining_after_allocations,
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
    DiscountType,
    DocumentType,
    Incoterm,
    PaymentMilestoneTrigger,
    PlaceOfSupply,
    ProformaInvoiceStatus,
    SalesOrderStatus,
    TaxCategory,
    TaxTreatment,
)
from app.core.exceptions import (
    DocumentStaleError,
    InvalidStatusTransitionError,
    MilestoneModeMixedError,
    MilestoneTotalMismatchError,
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
from app.erp.proforma_invoices.models import ProformaInvoice
from app.erp.proforma_invoices.repository import ProformaInvoiceRepository
from app.erp.proforma_invoices.schemas import (
    ProformaInvoiceComposeDefaults,
    ProformaInvoiceCreate,
    ProformaInvoiceLineInput,
    ProformaInvoiceLineResponse,
    ProformaInvoiceMilestoneInput,
    ProformaInvoiceMilestoneResponse,
    ProformaInvoiceResponse,
    ProformaInvoiceUpdate,
)
from app.erp.proforma_invoices.workflow import (
    assert_convertible,
    assert_editable,
    next_status,
    transition_actions,
)
from app.erp.quotation.service import QuotationService
from app.inventory_management.price_lists.service import PriceListService
from app.inventory_management.products.service import ProductService
from app.inventory_management.units.service import UnitService

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_PFI_SERIES = "PFI"
_ACTION_PERMISSIONS: dict[str, str] = {
    "send": PROFORMA_INVOICE_SEND,
    "confirm": PROFORMA_INVOICE_CONFIRM,
    "decline": PROFORMA_INVOICE_UPDATE,
    "cancel": PROFORMA_INVOICE_UPDATE,
    "reopen": PROFORMA_INVOICE_UPDATE,
    "revise": PROFORMA_INVOICE_UPDATE,
    "convert": SALES_ORDER_CREATE,
}


def compute_milestone_amounts(
    milestones: Sequence[ProformaInvoiceMilestoneInput],
    grand_total: Decimal,
) -> builtins.list[dict[str, object]]:
    """Validate milestone mode/sum and return rows with computed_amount filled.

    The last milestone by sequence absorbs rounding so the amounts sum to grand_total.
    """

    if not milestones:
        return []
    ordered = list(milestones)
    percent_flags = [item.percent is not None for item in ordered]
    amount_flags = [item.amount is not None for item in ordered]
    if any(p and a for p, a in zip(percent_flags, amount_flags, strict=True)):
        raise MilestoneModeMixedError("Each milestone must set percent or amount, not both")
    if any(not p and not a for p, a in zip(percent_flags, amount_flags, strict=True)):
        raise MilestoneModeMixedError("Each milestone must set percent or amount")
    percent_mode = all(percent_flags)
    amount_mode = all(amount_flags)
    if not percent_mode and not amount_mode:
        raise MilestoneModeMixedError()

    for item in ordered:
        if item.trigger == PaymentMilestoneTrigger.NET_DAYS and item.net_days is None:
            raise ValidationError("net_days is required when trigger is NET_DAYS")

    if percent_mode:
        total_percent = sum((item.percent or _ZERO) for item in ordered)
        if total_percent != _HUNDRED:
            raise MilestoneTotalMismatchError("Percent milestones must sum to 100")
    else:
        total_amount = sum((quantize_money(item.amount or _ZERO) for item in ordered), _ZERO)
        if total_amount != quantize_money(grand_total):
            raise MilestoneTotalMismatchError("Amount milestones must sum to the grand total")

    built: builtins.list[dict[str, object]] = []
    running = _ZERO
    last_index = len(ordered) - 1
    for index, item in enumerate(ordered):
        sequence = item.sequence if item.sequence is not None else index + 1
        if index == last_index:
            computed = quantize_money(grand_total) - running
        elif percent_mode:
            computed = quantize_money(
                quantize_money(grand_total) * (item.percent or _ZERO) / _HUNDRED
            )
        else:
            computed = quantize_money(item.amount or _ZERO)
        running += computed
        built.append(
            {
                "sequence": sequence,
                "label": item.label,
                "trigger": item.trigger.value,
                "percent": item.percent,
                "amount": item.amount,
                "net_days": (
                    item.net_days if item.trigger == PaymentMilestoneTrigger.NET_DAYS else None
                ),
                "due_date": item.due_date,
                "computed_amount": computed,
                "notes": item.notes,
            }
        )
    return built


def default_milestones() -> builtins.list[ProformaInvoiceMilestoneInput]:
    return [
        ProformaInvoiceMilestoneInput(
            sequence=1,
            label="30% advance TT",
            trigger=PaymentMilestoneTrigger.ON_CONFIRMATION,
            percent=Decimal("30"),
        ),
        ProformaInvoiceMilestoneInput(
            sequence=2,
            label="70% before shipment",
            trigger=PaymentMilestoneTrigger.BEFORE_SHIPMENT,
            percent=Decimal("70"),
        ),
    ]


class ProformaInvoiceService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = ProformaInvoiceRepository(session)
        self.org = OrganizationService(session)
        self.customers = CustomerService(session)
        self.contacts = ContactService(session)
        self.products = ProductService(session)
        self.price_lists = PriceListService(session)
        self.units = UnitService(session)
        self.taxes = TaxService(session)
        self.payment_terms = PaymentTermService(session)
        self.terms = TermsTemplateService(session)
        self.sequences = DocumentSequenceService(session)
        self.currencies = CurrencyService(session)
        self.fx = ExchangeRateService(session)
        self.audit = AuditWriter(session)
        self.outbox = OutboxService(session)

    async def has_live_for_quotation(self, tenant_id: UUID, quotation_id: UUID) -> bool:
        return await self.repo.has_live_for_quotation(tenant_id, quotation_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        customer_id: UUID | None = None,
        branch_id: UUID | None = None,
        currency_id: UUID | None = None,
        source_quotation_id: UUID | None = None,
        source_sales_order_id: UUID | None = None,
    ) -> tuple[list[ProformaInvoiceResponse], int]:
        today = await self._today(tenant_id)
        filters: dict[str, object] = {}
        if customer_id is not None:
            filters["customer_id"] = customer_id
        if branch_id is not None:
            filters["branch_id"] = branch_id
        if currency_id is not None:
            filters["currency_id"] = currency_id
        if source_quotation_id is not None:
            filters["source_quotation_id"] = source_quotation_id
        if source_sales_order_id is not None:
            filters["source_sales_order_id"] = source_sales_order_id
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            status=status,
            today=today,
        )
        return [self._to_response(row, today) for row in rows], total

    async def get(self, tenant_id: UUID, proforma_invoice_id: UUID) -> ProformaInvoiceResponse:
        today = await self._today(tenant_id)
        row = await self._require(tenant_id, proforma_invoice_id)
        response = self._to_response(row, today)
        response.related_documents = await self._related_documents(tenant_id, row)
        from app.erp.accounting.customer_payments.service import CustomerPaymentService

        payments = await CustomerPaymentService(
            self.session, actor_permissions=self.actor_permissions
        ).list_for_proforma_invoice(tenant_id, row.id)
        outstanding = sum(
            (
                payment.amount_unapplied
                for payment in payments
                if payment.status == "POSTED"
            ),
            Decimal("0"),
        )
        response.advance_outstanding = quantize_money(outstanding)
        return response

    async def print_document(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        *,
        template_family: str = "uae",
    ) -> PrintDocumentResponse:
        row = await self.get(tenant_id, proforma_invoice_id)
        customer = await self.customers.get(tenant_id, row.customer_id)
        currency = await self.currencies.get(tenant_id, row.currency_id)
        printer = PrintService(self.session)
        family = template_family if template_family in {"uae", "china"} else "uae"
        return await printer.assemble(
            tenant_id,
            document_type=DocumentType.PROFORMA_INVOICE.value,
            document_id=row.id,
            document_number=row.document_number,
            document_date=row.document_date,
            template_family=family,
            customer_code=customer.code,
            customer_name=customer.name,
            customer_address=format_address_snapshot(customer.billing_address),
            customer_trn=customer.trn,
            incoterm=row.incoterm.value if row.incoterm else None,
            incoterm_place=row.incoterm_place,
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

    async def import_drafts(
        self,
        tenant_id: UUID,
        *,
        filename: str | None,
        content: bytes,
        mapping: builtins.list[object],
        actor_user_id: UUID,
    ) -> object:
        from app.common.imex.commercial import (
            group_fill_forward,
            import_result,
            load_mapped_rows,
            packing_kwargs,
            require_line_quantity,
        )
        from app.common.imex.schemas import ImportRowError
        from app.common.imex.service import parse_optional_date, parse_optional_decimal

        rows = load_mapped_rows(
            "proforma_invoice", filename=filename, content=content, mapping=mapping
        )
        created_ids: builtins.list[UUID] = []
        errors: builtins.list[ImportRowError] = []
        for (_key, items) in group_fill_forward(rows, ("customer_name", "document_date")).items():
            first_row_number, header = items[0]
            try:
                customer = await self.customers.find_by_name_or_code(
                    tenant_id, header.get("customer_name") or ""
                )
                if customer is None:
                    raise ValidationError("Customer not found")
                currency_id = customer.currency_id
                currency_code = (header.get("currency_code") or "").strip()
                if currency_code:
                    currency = await self.currencies.get_by_code(tenant_id, currency_code)
                    if currency is None:
                        raise ValidationError(f"Unknown currency {currency_code}")
                    currency_id = currency.id
                incoterm = None
                token = (header.get("incoterm") or "").strip().upper()
                if token:
                    try:
                        incoterm = Incoterm(token[:3])
                    except ValueError:
                        incoterm = None
                lines: builtins.list[ProformaInvoiceLineInput] = []
                for _row_number, item in items:
                    sku = (item.get("line.sku") or "").strip()
                    product = await self.products.find_by_sku(tenant_id, sku) if sku else None
                    lines.append(
                        ProformaInvoiceLineInput(
                            product_id=product.id if product else None,
                            quantity=require_line_quantity(item),
                            rate=parse_optional_decimal(item.get("line.unit_price")),
                            **packing_kwargs(item, sku=sku),
                        )
                    )
                created = await self.create(
                    tenant_id,
                    ProformaInvoiceCreate(
                        customer_id=customer.id,
                        proforma_date=parse_optional_date(header.get("document_date")),
                        currency_id=currency_id,
                        notes=(header.get("notes") or "").strip() or None,
                        incoterm=incoterm,
                        incoterm_place=(header.get("incoterm_place") or "").strip() or None,
                        lines=lines,
                    ),
                    actor_user_id=actor_user_id,
                )
                created_ids.append(created.id)
            except (ValidationError, ValueError) as exc:
                errors.append(ImportRowError(row_number=first_row_number, message=str(exc)))
        return import_result(created_ids, errors)

    async def export_rows(
        self,
        tenant_id: UUID,
        *,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        customer_id: UUID | None = None,
        branch_id: UUID | None = None,
        currency_id: UUID | None = None,
        source_quotation_id: UUID | None = None,
        source_sales_order_id: UUID | None = None,
    ) -> builtins.list[builtins.list[object]]:
        from app.common.imex.commercial import commercial_export_row
        from app.core.constants import MAX_PAGE_SIZE

        exported: builtins.list[builtins.list[object]] = []
        page = 1
        while True:
            rows, total = await self.list(
                tenant_id,
                page=PageParams(page=page, page_size=MAX_PAGE_SIZE),
                common_filter=common_filter,
                status=status,
                customer_id=customer_id,
                branch_id=branch_id,
                currency_id=currency_id,
                source_quotation_id=source_quotation_id,
                source_sales_order_id=source_sales_order_id,
            )
            for row in rows:
                for line in row.lines:
                    exported.append(
                        commercial_export_row(row, line, party_id=row.customer_id)
                    )
            if len(rows) < MAX_PAGE_SIZE or page * MAX_PAGE_SIZE >= total:
                break
            page += 1
        return exported

    async def compose_defaults(
        self, tenant_id: UUID, customer_id: UUID
    ) -> ProformaInvoiceComposeDefaults:
        customer = await self.customers.get(tenant_id, customer_id)
        primary = await self.contacts.get_primary(tenant_id, customer_id)
        default_terms = await self.terms.get_default(tenant_id)
        place = place_of_supply_from_address(customer.shipping_address)
        return ProformaInvoiceComposeDefaults(
            customer_id=customer.id,
            customer_name=customer.name,
            customer_trn=customer.trn,
            tax_treatment=customer.tax_treatment,
            currency_id=customer.currency_id,
            price_list_id=customer.default_price_list_id,
            payment_terms_id=customer.payment_terms_id,
            salesperson_id=customer.salesperson_id,
            contact_id=primary.id if primary else None,
            place_of_supply=place,
            bill_to_snapshot=format_address_snapshot(customer.billing_address),
            ship_to_snapshot=format_address_snapshot(customer.shipping_address),
            terms_and_conditions=default_terms.body if default_terms else None,
        )

    async def create(
        self, tenant_id: UUID, payload: ProformaInvoiceCreate, *, actor_user_id: UUID
    ) -> ProformaInvoiceResponse:
        async with transaction(self.session):
            header, line_rows, milestone_rows = await self._build_draft(tenant_id, payload)
            proforma_date = cast(date, header["proforma_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.PROFORMA_INVOICE,
                series=_PFI_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, proforma_date),
                prefix=_PFI_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": ProformaInvoiceStatus.DRAFT.value,
                    "version": 1,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            await self.repo.replace_milestones(tenant_id, row.id, milestone_rows)
            loaded = await self._require(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=SALES_MODULE,
                entity_type="proforma_invoice",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded, await self._today(tenant_id))

    async def create_from_quotation(
        self,
        tenant_id: UUID,
        quotation_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        proforma_date: date | None = None,
        valid_until: date | None = None,
        incoterm: Incoterm | None = None,
        incoterm_place: str | None = None,
    ) -> ProformaInvoiceResponse:
        async with transaction(self.session):
            quotes = QuotationService(self.session, actor_permissions=self.actor_permissions)
            quotation = await quotes.require_proforma_source(
                tenant_id, quotation_id, expected_version=expected_version
            )
            payload = ProformaInvoiceCreate(
                customer_id=quotation.customer_id,
                contact_id=quotation.contact_id,
                branch_id=quotation.branch_id,
                proforma_date=proforma_date,
                valid_until=valid_until if valid_until is not None else quotation.valid_until,
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
                source_quotation_id=quotation.id,
                incoterm=incoterm,
                incoterm_place=incoterm_place,
                lines=[
                    ProformaInvoiceLineInput(
                        product_id=line.product_id,
                        description=line.description,
                        quantity=line.quantity,
                        unit_id=line.unit_id,
                        rate=line.rate,
                        discount_type=line.discount_type,
                        discount_value=line.discount_value,
                        tax_id=line.tax_id,
                        source_quotation_line_id=line.id,
                    )
                    for line in quotation.lines
                ],
                milestones=default_milestones(),
            )
            header, line_rows, milestone_rows = await self._build_draft(tenant_id, payload)
            header["source_quotation_id"] = quotation.id
            copy_source_commercial_header(
                header,
                exchange_rate=quotation.exchange_rate,
                base_currency_id=quotation.base_currency_id,
                bill_to_snapshot=quotation.bill_to_snapshot,
                ship_to_snapshot=quotation.ship_to_snapshot,
            )
            for built, source in zip(line_rows, quotation.lines, strict=True):
                built["source_quotation_line_id"] = source.id
            proforma_date_value = cast(date, header["proforma_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.PROFORMA_INVOICE,
                series=_PFI_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, proforma_date_value),
                prefix=_PFI_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": ProformaInvoiceStatus.DRAFT.value,
                    "version": 1,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            await self.repo.replace_milestones(tenant_id, row.id, milestone_rows)
            loaded = await self._require(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=SALES_MODULE,
                entity_type="proforma_invoice",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded, await self._today(tenant_id))

    async def create_from_sales_order(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        proforma_date: date | None = None,
        valid_until: date | None = None,
        conversion_lines: Sequence[ConversionLineInput] | None = None,
    ) -> ProformaInvoiceResponse:
        from app.erp.sales_orders.service import SalesOrderService

        async with transaction(self.session):
            sales_orders = SalesOrderService(self.session, actor_permissions=self.actor_permissions)
            order = await sales_orders._require(tenant_id, sales_order_id, for_update=True)
            sales_orders._assert_version(order, expected_version)
            if order.status != SalesOrderStatus.CONFIRMED.value:
                raise ValidationError(
                    "Proforma invoices can only be created from a confirmed sales order"
                )
            requested = (
                [(item.source_line_id, item.quantity) for item in conversion_lines]
                if conversion_lines is not None
                else None
            )
            allocations = allocate_conversion_qty(
                lines=[(line.id, line.quantity, line.qty_converted) for line in order.lines],
                requested=requested,
                empty_message="This sales order has no remaining quantity to convert",
            )
            by_id = {line.id: line for line in order.lines}
            selected = [(by_id[line_id], qty) for line_id, qty in allocations]
            payload = ProformaInvoiceCreate(
                customer_id=order.customer_id,
                contact_id=order.contact_id,
                branch_id=order.branch_id,
                proforma_date=proforma_date,
                valid_until=valid_until,
                currency_id=order.currency_id,
                price_list_id=order.price_list_id,
                payment_terms_id=order.payment_terms_id,
                salesperson_id=order.salesperson_id,
                notes=order.notes,
                terms_and_conditions=order.terms_and_conditions,
                discount_type=DiscountType(order.discount_type) if order.discount_type else None,
                discount_value=order.discount_value,
                shipping_amount=order.shipping_amount,
                adjustment_amount=order.adjustment_amount,
                place_of_supply=PlaceOfSupply(order.place_of_supply),
                source_quotation_id=order.source_quotation_id,
                source_sales_order_id=order.id,
                lines=[
                    ProformaInvoiceLineInput(
                        product_id=source.product_id,
                        description=source.description,
                        quantity=qty,
                        unit_id=source.unit_id,
                        rate=source.rate,
                        discount_type=DiscountType(source.discount_type)
                        if source.discount_type
                        else None,
                        discount_value=source.discount_value,
                        tax_id=source.tax_id,
                        source_quotation_line_id=source.source_quotation_line_id,
                        source_sales_order_line_id=source.id,
                    )
                    for source, qty in selected
                ],
                milestones=default_milestones(),
            )
            header, line_rows, milestone_rows = await self._build_draft(tenant_id, payload)
            header["source_quotation_id"] = order.source_quotation_id
            header["source_sales_order_id"] = order.id
            copy_source_commercial_header(
                header,
                exchange_rate=order.exchange_rate,
                base_currency_id=order.base_currency_id,
                bill_to_snapshot=order.bill_to_snapshot,
                ship_to_snapshot=order.ship_to_snapshot,
            )
            for built, (source, _) in zip(line_rows, selected, strict=True):
                built["source_sales_order_line_id"] = source.id
                built["source_quotation_line_id"] = source.source_quotation_line_id
            for line_id, qty in allocations:
                source = by_id[line_id]
                source.qty_converted = quantize_quantity(source.qty_converted + qty)
            proforma_date_value = cast(date, header["proforma_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.PROFORMA_INVOICE,
                series=_PFI_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, proforma_date_value),
                prefix=_PFI_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": ProformaInvoiceStatus.DRAFT.value,
                    "version": 1,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            await self.repo.replace_milestones(tenant_id, row.id, milestone_rows)
            loaded = await self._require(tenant_id, row.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=SALES_MODULE,
                entity_type="proforma_invoice",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded, await self._today(tenant_id))

    async def update(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        payload: ProformaInvoiceUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ProformaInvoiceResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, proforma_invoice_id, for_update=True)
            old_values = await self._snapshot(tenant_id, existing)
            today = await self._today(tenant_id)
            assert_editable(self._effective_status(existing, today))
            self._assert_version(existing, expected_version)
            create_payload = await self._update_to_create(existing, payload)
            header, line_rows, milestone_rows = await self._build_draft(tenant_id, create_payload)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            header["source_quotation_id"] = existing.source_quotation_id
            header["source_sales_order_id"] = existing.source_sales_order_id
            if payload.lines is None:
                for built, existing_line in zip(line_rows, existing.lines, strict=True):
                    built["source_quotation_line_id"] = existing_line.source_quotation_line_id
                    built["source_sales_order_line_id"] = existing_line.source_sales_order_line_id
            await self.repo.update(tenant_id, proforma_invoice_id, header)
            await self.repo.replace_lines(tenant_id, proforma_invoice_id, line_rows)
            await self.repo.replace_milestones(tenant_id, proforma_invoice_id, milestone_rows)
            loaded = await self._require(tenant_id, proforma_invoice_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=SALES_MODULE,
                entity_type="proforma_invoice",
                entity_id=proforma_invoice_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded, today)

    async def send(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ProformaInvoiceResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, proforma_invoice_id, for_update=True)
            old_values = await self._snapshot(tenant_id, row)
            today = await self._today(tenant_id)
            current = self._effective_status(row, today)
            self._assert_version(row, expected_version)
            target = next_status(current, "send")
            if not row.bank_details_snapshot:
                row.bank_details_snapshot = await self.org.get_bank_details(tenant_id)
            now = utcnow()
            row.status = target.value
            row.sent_at = now
            row.sent_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.SEND,
                module=SALES_MODULE,
                entity_type="proforma_invoice",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="sales.proforma_invoice.sent",
                aggregate_type="proforma_invoice",
                aggregate_id=row.id,
                payload={"proforma_invoice_id": str(row.id)},
                dedupe_key=f"proforma-sent:{row.id}:{row.version}",
            )
            return self._to_response(row, today)

    async def confirm(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ProformaInvoiceResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, proforma_invoice_id, for_update=True)
            old_values = await self._snapshot(tenant_id, row)
            today = await self._today(tenant_id)
            current = self._effective_status(row, today)
            self._assert_version(row, expected_version)
            target = next_status(current, "confirm")
            now = utcnow()
            confirmed_on = now.date()
            row.status = target.value
            row.confirmed_at = now
            row.confirmed_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            for milestone in row.milestones:
                if (
                    milestone.trigger == PaymentMilestoneTrigger.NET_DAYS.value
                    and milestone.net_days is not None
                ):
                    milestone.due_date = confirmed_on + timedelta(days=milestone.net_days)
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CONFIRM,
                module=SALES_MODULE,
                entity_type="proforma_invoice",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="sales.proforma_invoice.confirmed",
                aggregate_type="proforma_invoice",
                aggregate_id=row.id,
                payload={"proforma_invoice_id": str(row.id)},
                dedupe_key=f"proforma-confirmed:{row.id}:{row.version}",
            )
            if row.source_quotation_id is not None:
                quotes = QuotationService(self.session, actor_permissions=self.actor_permissions)
                await quotes.accept_from_proforma(
                    tenant_id, row.source_quotation_id, actor_user_id=actor_user_id
                )
            return self._to_response(row, today)

    async def decline(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> ProformaInvoiceResponse:
        return await self._transition(
            tenant_id,
            proforma_invoice_id,
            "decline",
            actor_user_id,
            expected_version=expected_version,
            reason=reason,
        )

    async def cancel(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> ProformaInvoiceResponse:
        return await self._transition(
            tenant_id,
            proforma_invoice_id,
            "cancel",
            actor_user_id,
            expected_version=expected_version,
            reason=reason,
        )

    async def reopen(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ProformaInvoiceResponse:
        return await self._transition(
            tenant_id,
            proforma_invoice_id,
            "reopen",
            actor_user_id,
            expected_version=expected_version,
        )

    async def revise(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ProformaInvoiceResponse:
        return await self._transition(
            tenant_id,
            proforma_invoice_id,
            "revise",
            actor_user_id,
            expected_version=expected_version,
        )

    async def clone(
        self, tenant_id: UUID, proforma_invoice_id: UUID, *, actor_user_id: UUID
    ) -> ProformaInvoiceResponse:
        async with transaction(self.session):
            source = await self._require(tenant_id, proforma_invoice_id)
            payload = await self._update_to_create(source, ProformaInvoiceUpdate())
            payload.proforma_date = None
            payload.source_quotation_id = None
            for line in payload.lines:
                line.source_quotation_line_id = None
            header, line_rows, milestone_rows = await self._build_draft(tenant_id, payload)
            proforma_date = cast(date, header["proforma_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.PROFORMA_INVOICE,
                series=_PFI_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, proforma_date),
                prefix=_PFI_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": ProformaInvoiceStatus.DRAFT.value,
                    "version": 1,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            await self.repo.replace_milestones(tenant_id, row.id, milestone_rows)
            loaded = await self._require(tenant_id, row.id)
            new_values = await self._snapshot(tenant_id, loaded)
            new_values["cloned_from"] = source.document_number
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CLONE,
                module=SALES_MODULE,
                entity_type="proforma_invoice",
                entity_id=row.id,
                new_values=new_values,
            )
            return self._to_response(loaded, await self._today(tenant_id))

    async def delete(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ProformaInvoiceResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, proforma_invoice_id, for_update=True)
            today = await self._today(tenant_id)
            current = self._effective_status(row, today)
            if current != ProformaInvoiceStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft proforma invoices can be deleted")
            self._assert_version(row, expected_version)
            response = self._to_response(row, today)
            old_values = await self._snapshot(tenant_id, row)
            await self.repo.soft_delete(tenant_id, proforma_invoice_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=SALES_MODULE,
                entity_type="proforma_invoice",
                entity_id=proforma_invoice_id,
                old_values=old_values,
            )
            return response

    async def require_convertible(
        self, tenant_id: UUID, proforma_invoice_id: UUID, *, expected_version: int
    ) -> ProformaInvoiceResponse:
        row = await self._require(tenant_id, proforma_invoice_id, for_update=True)
        today = await self._today(tenant_id)
        current = self._effective_status(row, today)
        self._assert_version(row, expected_version)
        assert_convertible(current)
        if not any(remaining_qty(line.quantity, line.qty_converted) > _ZERO for line in row.lines):
            raise InvalidStatusTransitionError("Proforma invoice has already been converted")
        return self._to_response(row, today)

    async def mark_converted(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        *,
        document_type: DocumentType,
        document_id: UUID,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ProformaInvoiceResponse:
        async with transaction(self.session):
            return await self._apply_converted(
                tenant_id,
                proforma_invoice_id,
                document_type=document_type,
                document_id=document_id,
                actor_user_id=actor_user_id,
                expected_version=expected_version,
            )

    async def _apply_converted(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        *,
        document_type: DocumentType,
        document_id: UUID,
        actor_user_id: UUID,
        expected_version: int,
        allocations: Sequence[tuple[UUID, Decimal]] | None = None,
    ) -> ProformaInvoiceResponse:
        row = await self._require(tenant_id, proforma_invoice_id, for_update=True)
        old_values = await self._snapshot(tenant_id, row)
        today = await self._today(tenant_id)
        current = self._effective_status(row, today)
        self._assert_version(row, expected_version)
        assert_convertible(current)
        line_specs = [(line.id, line.quantity, line.qty_converted) for line in row.lines]
        applied = allocate_conversion_qty(
            lines=line_specs,
            requested=allocations,
            empty_message="This proforma invoice has no remaining quantity to convert",
        )
        by_id = {line.id: line for line in row.lines}
        for line_id, qty in applied:
            source = by_id[line_id]
            source.qty_converted = quantize_quantity(source.qty_converted + qty)
        leftover = remaining_after_allocations(line_specs, applied)
        target = (
            ProformaInvoiceStatus.CONVERTED
            if leftover <= _ZERO
            else ProformaInvoiceStatus.PARTIALLY_CONVERTED
        )
        row.status = target.value
        row.converted_at = utcnow()
        row.converted_document_type = document_type.value
        row.converted_document_id = document_id
        row.version += 1
        row.updated_by = actor_user_id
        await self.session.flush()
        await self.session.refresh(row, attribute_names=["updated_at"])
        await self.audit.write(
            tenant_id=tenant_id,
            user_id=actor_user_id,
            action=AuditAction.CONVERT,
            module=SALES_MODULE,
            entity_type="proforma_invoice",
            entity_id=row.id,
            old_values=old_values,
            new_values=await self._snapshot(tenant_id, row),
        )
        return self._to_response(row, today)

    async def _transition(
        self,
        tenant_id: UUID,
        proforma_invoice_id: UUID,
        action: str,
        actor_user_id: UUID,
        *,
        expected_version: int,
        reason: str | None = None,
    ) -> ProformaInvoiceResponse:
        action_map = {
            "decline": AuditAction.DECLINE,
            "cancel": AuditAction.CANCEL,
            "reopen": AuditAction.UPDATE,
            "revise": AuditAction.REVISE,
        }
        async with transaction(self.session):
            row = await self._require(tenant_id, proforma_invoice_id, for_update=True)
            old_values = await self._snapshot(tenant_id, row)
            today = await self._today(tenant_id)
            current = self._effective_status(row, today)
            self._assert_version(row, expected_version)
            target = next_status(current, action)
            now = utcnow()
            row.status = target.value
            row.version += 1
            row.updated_by = actor_user_id
            if action == "decline":
                row.declined_at = now
                row.declined_by = actor_user_id
                row.decline_reason = reason
            if action == "cancel":
                row.cancelled_at = now
                row.cancelled_by = actor_user_id
                row.cancel_reason = reason
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            new_values = await self._snapshot(tenant_id, row)
            if reason:
                new_values["reason"] = reason
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=action_map[action],
                module=SALES_MODULE,
                entity_type="proforma_invoice",
                entity_id=row.id,
                old_values=old_values,
                new_values=new_values,
            )
            return self._to_response(row, today)

    async def _build_draft(
        self, tenant_id: UUID, payload: ProformaInvoiceCreate
    ) -> tuple[
        dict[str, object],
        builtins.list[dict[str, object]],
        builtins.list[dict[str, object]],
    ]:
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

        currency_id = payload.currency_id or customer.currency_id
        await self.currencies.require_id(tenant_id, currency_id)
        base = await self.currencies.get_base(tenant_id)
        proforma_date = payload.proforma_date or await self._today(tenant_id)
        resolved = await self.fx.resolve(
            tenant_id,
            from_currency_id=currency_id,
            to_currency_id=base.id,
            on_date=proforma_date,
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
        milestone_rows = compute_milestone_amounts(payload.milestones, grand)
        header: dict[str, object] = {
            "proforma_date": proforma_date,
            "valid_until": payload.valid_until,
            "branch_id": payload.branch_id,
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
            "source_quotation_id": payload.source_quotation_id,
            "source_sales_order_id": payload.source_sales_order_id,
            "incoterm": payload.incoterm.value if payload.incoterm else None,
            "incoterm_place": payload.incoterm_place,
            "port_of_loading": payload.port_of_loading,
            "port_of_discharge": payload.port_of_discharge,
            "country_of_origin": payload.country_of_origin,
            "country_of_final_destination": payload.country_of_final_destination,
            "expected_shipment_date": payload.expected_shipment_date,
            "partial_shipment_allowed": payload.partial_shipment_allowed,
            "transhipment_allowed": payload.transhipment_allowed,
            "bank_details_snapshot": payload.bank_details_snapshot,
        }
        return header, line_rows, milestone_rows

    async def _build_lines(
        self,
        tenant_id: UUID,
        lines: Sequence[ProformaInvoiceLineInput],
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
            hs_code = line.hs_code or (product.hs_code if product else None)
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
                    "hs_code": hs_code,
                    "source_quotation_line_id": line.source_quotation_line_id,
                    "source_sales_order_line_id": line.source_sales_order_line_id,
                    "qty_converted": _ZERO,
                    **packing_persist(line),
                }
            )
            nets.append(net)
            taxes.append(tax_amount)
        return built, nets, taxes

    async def _update_to_create(
        self, existing: ProformaInvoice, payload: ProformaInvoiceUpdate
    ) -> ProformaInvoiceCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        lines = values.get("lines")
        line_inputs = (
            [ProformaInvoiceLineInput.model_validate(item) for item in lines]
            if lines is not None
            else [
                ProformaInvoiceLineInput(
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    discount_type=DiscountType(line.discount_type) if line.discount_type else None,
                    discount_value=line.discount_value,
                    tax_id=line.tax_id,
                    hs_code=line.hs_code,
                    source_quotation_line_id=line.source_quotation_line_id,
                )
                for line in existing.lines
            ]
        )
        milestones = values.get("milestones")
        milestone_inputs = (
            [ProformaInvoiceMilestoneInput.model_validate(item) for item in milestones]
            if milestones is not None
            else [
                ProformaInvoiceMilestoneInput(
                    sequence=item.sequence,
                    label=item.label,
                    trigger=PaymentMilestoneTrigger(item.trigger),
                    percent=item.percent,
                    amount=item.amount,
                    net_days=item.net_days,
                    due_date=item.due_date,
                    notes=item.notes,
                )
                for item in existing.milestones
            ]
        )
        return ProformaInvoiceCreate(
            customer_id=existing.customer_id,
            contact_id=values.get("contact_id", existing.contact_id),
            branch_id=values.get("branch_id", existing.branch_id),
            proforma_date=values.get("proforma_date", existing.proforma_date),
            valid_until=values.get("valid_until", existing.valid_until),
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
            source_quotation_id=existing.source_quotation_id,
            source_sales_order_id=existing.source_sales_order_id,
            incoterm=values.get(
                "incoterm", Incoterm(existing.incoterm) if existing.incoterm else None
            ),
            incoterm_place=values.get("incoterm_place", existing.incoterm_place),
            port_of_loading=values.get("port_of_loading", existing.port_of_loading),
            port_of_discharge=values.get("port_of_discharge", existing.port_of_discharge),
            country_of_origin=values.get("country_of_origin", existing.country_of_origin),
            country_of_final_destination=values.get(
                "country_of_final_destination", existing.country_of_final_destination
            ),
            expected_shipment_date=values.get(
                "expected_shipment_date", existing.expected_shipment_date
            ),
            partial_shipment_allowed=values.get(
                "partial_shipment_allowed", existing.partial_shipment_allowed
            ),
            transhipment_allowed=values.get("transhipment_allowed", existing.transhipment_allowed),
            bank_details_snapshot=values.get(
                "bank_details_snapshot", existing.bank_details_snapshot
            ),
            lines=line_inputs,
            milestones=milestone_inputs,
        )

    def _effective_status(self, row: ProformaInvoice, today: date) -> ProformaInvoiceStatus:
        status = ProformaInvoiceStatus(row.status)
        if (
            status == ProformaInvoiceStatus.SENT
            and row.valid_until is not None
            and row.valid_until < today
        ):
            return ProformaInvoiceStatus.EXPIRED
        return status

    def _available_actions(self, status: ProformaInvoiceStatus) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if has_permission(self.actor_permissions, PROFORMA_INVOICE_CREATE):
            actions.append("clone")
        if status == ProformaInvoiceStatus.DRAFT and has_permission(
            self.actor_permissions, PROFORMA_INVOICE_DELETE
        ):
            actions.append("delete")
        if status in {
            ProformaInvoiceStatus.CONFIRMED,
            ProformaInvoiceStatus.PARTIALLY_CONVERTED,
        } and has_permission(self.actor_permissions, SALES_INVOICE_CREATE):
            actions.append("create_sales_invoice")
        return actions

    def _to_response(self, row: ProformaInvoice, today: date) -> ProformaInvoiceResponse:
        status = self._effective_status(row, today)
        advance = sum(
            (
                item.computed_amount
                for item in row.milestones
                if item.trigger == PaymentMilestoneTrigger.ON_CONFIRMATION.value
            ),
            _ZERO,
        )
        return ProformaInvoiceResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            display_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=False,
            proforma_date=row.proforma_date,
            document_date=row.proforma_date,
            valid_until=row.valid_until,
            branch_id=row.branch_id,
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
            source_quotation_id=row.source_quotation_id,
            source_sales_order_id=row.source_sales_order_id,
            incoterm=Incoterm(row.incoterm) if row.incoterm else None,
            incoterm_place=row.incoterm_place,
            port_of_loading=row.port_of_loading,
            port_of_discharge=row.port_of_discharge,
            country_of_origin=row.country_of_origin,
            country_of_final_destination=row.country_of_final_destination,
            expected_shipment_date=row.expected_shipment_date,
            partial_shipment_allowed=row.partial_shipment_allowed,
            transhipment_allowed=row.transhipment_allowed,
            bank_details_snapshot=row.bank_details_snapshot,
            sent_at=row.sent_at,
            sent_by=row.sent_by,
            confirmed_at=row.confirmed_at,
            confirmed_by=row.confirmed_by,
            declined_at=row.declined_at,
            declined_by=row.declined_by,
            decline_reason=row.decline_reason,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            converted_at=row.converted_at,
            converted_document_type=row.converted_document_type,
            converted_document_id=row.converted_document_id,
            advance_required_amount=quantize_money(advance),
            advance_outstanding=quantize_money(_ZERO),
            available_actions=self._available_actions(status),
            related_documents=[],
            lines=[ProformaInvoiceLineResponse.model_validate(line) for line in row.lines],
            milestones=[
                ProformaInvoiceMilestoneResponse.model_validate(item) for item in row.milestones
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _today(self, tenant_id: UUID) -> date:
        return today_in_timezone(await self.org.get_timezone(tenant_id))

    def _assert_version(self, row: ProformaInvoice, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _related_documents(
        self, tenant_id: UUID, row: ProformaInvoice
    ) -> builtins.list[RelatedDocumentRef]:
        from app.erp.quotation.repository import QuotationRepository
        from app.erp.sales_invoices.repository import SalesInvoiceRepository
        from app.erp.sales_orders.repository import SalesOrderRepository

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
        if row.source_sales_order_id is not None:
            order = await SalesOrderRepository(self.session).get(
                tenant_id, row.source_sales_order_id
            )
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
        for item in await SalesOrderRepository(self.session).list_for_proforma_invoice(
            tenant_id, row.id
        ):
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.SALES_ORDER.value,
                    document_id=item.id,
                    document_number=item.document_number,
                    status=item.status,
                    relationship="child",
                    document_date=item.order_date,
                    quantity_summary=quantity_summary([line.quantity for line in item.lines]),
                )
            )
        for item in await SalesInvoiceRepository(self.session).list_for_proforma_invoice(
            tenant_id, row.id
        ):
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.SALES_INVOICE.value,
                    document_id=item.id,
                    document_number=item.document_number,
                    status=item.status,
                    relationship="child",
                    document_date=item.invoice_date,
                    quantity_summary=quantity_summary([line.quantity for line in item.lines]),
                )
            )
        from app.erp.accounting.customer_payments.service import CustomerPaymentService

        for payment in await CustomerPaymentService(
            self.session, actor_permissions=self.actor_permissions
        ).list_for_proforma_invoice(tenant_id, row.id):
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

    async def _snapshot(self, tenant_id: UUID, row: ProformaInvoice) -> dict[str, object]:
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
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "proforma_date": row.proforma_date,
            "valid_until": row.valid_until,
            "branch": branch_name,
            "customer": customer.name,
            "contact": contact_name,
            "tax_treatment": row.tax_treatment,
            "place_of_supply": row.place_of_supply,
            "currency": currency.code,
            "exchange_rate": row.exchange_rate,
            "price_list": price_list_name,
            "payment_terms": payment_term_name,
            "salesperson": await self.org.employee_audit_label(tenant_id, row.salesperson_id),
            "incoterm": row.incoterm,
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
            "advance_required_amount": sum(
                (
                    item.computed_amount
                    for item in row.milestones
                    if item.trigger == PaymentMilestoneTrigger.ON_CONFIRMATION.value
                ),
                _ZERO,
            ),
        }

    async def _require(
        self, tenant_id: UUID, proforma_invoice_id: UUID, *, for_update: bool = False
    ) -> ProformaInvoice:
        row = await self.repo.get(tenant_id, proforma_invoice_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Proforma invoice not found")
        return row
