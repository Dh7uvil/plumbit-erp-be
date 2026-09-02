"""Quotation compose, totals, FX snapshot, and status transitions."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    ERP_MODULE,
    QUOTATION_APPROVE,
    QUOTATION_CREATE,
    QUOTATION_DELETE,
    QUOTATION_SEND,
    QUOTATION_UPDATE,
)
from app.auth.org_service import OrganizationService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money
from app.common.utils.datetime import today_in_timezone
from app.core.enums import (
    AuditAction,
    DiscountType,
    DocumentType,
    PlaceOfSupply,
    QuotationStatus,
    TaxCategory,
    TaxTreatment,
)
from app.core.exceptions import (
    DocumentStaleError,
    InvalidStatusTransitionError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.crm.contacts.service import ContactService
from app.crm.customers.service import CustomerService
from app.db.session import transaction
from app.erp.accounting.service import (
    DocumentSequenceService,
    PaymentTermService,
    TaxService,
    TermsTemplateService,
)
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService
from app.erp.quotation.models import Quotation
from app.erp.quotation.repository import QuotationRepository
from app.erp.quotation.schemas import (
    QuotationComposeDefaults,
    QuotationCreate,
    QuotationLineInput,
    QuotationLineResponse,
    QuotationResponse,
    QuotationUpdate,
)
from app.erp.quotation.totals import (
    compute_header_totals,
    compute_line_amounts,
    format_address_snapshot,
    place_of_supply_from_address,
    resolve_line_tax_category,
)
from app.erp.quotation.workflow import assert_editable, next_status, transition_actions
from app.inventory_management.price_lists.service import PriceListService
from app.inventory_management.products.service import ProductService
from app.inventory_management.units.service import UnitService

_ZERO = Decimal("0")
_QUOTE_SERIES = "QUO"
_ACTION_PERMISSIONS: dict[str, str] = {
    "submit": QUOTATION_UPDATE,
    "approve": QUOTATION_APPROVE,
    "reject": QUOTATION_APPROVE,
    "reopen": QUOTATION_UPDATE,
    "send": QUOTATION_SEND,
    "accept": QUOTATION_UPDATE,
    "decline": QUOTATION_UPDATE,
    "cancel": QUOTATION_UPDATE,
}


class QuotationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = QuotationRepository(session)
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
    ) -> tuple[list[QuotationResponse], int]:
        today = await self._today(tenant_id)
        requires_approval = await self.org.quotation_requires_approval(tenant_id)
        filters: dict[str, object] = {}
        if customer_id is not None:
            filters["customer_id"] = customer_id
        if branch_id is not None:
            filters["branch_id"] = branch_id
        if currency_id is not None:
            filters["currency_id"] = currency_id
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            status=status,
            today=today,
        )
        return [
            self._to_response(row, today, requires_approval=requires_approval) for row in rows
        ], total

    async def get(self, tenant_id: UUID, quotation_id: UUID) -> QuotationResponse:
        today, requires_approval = await self._response_context(tenant_id)
        return self._to_response(
            await self._require(tenant_id, quotation_id),
            today,
            requires_approval=requires_approval,
        )

    async def compose_defaults(
        self, tenant_id: UUID, customer_id: UUID
    ) -> QuotationComposeDefaults:
        customer = await self.customers.get(tenant_id, customer_id)
        primary = await self.contacts.get_primary(tenant_id, customer_id)
        default_terms = await self.terms.get_default(tenant_id)
        place = place_of_supply_from_address(customer.shipping_address)
        return QuotationComposeDefaults(
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
        self, tenant_id: UUID, payload: QuotationCreate, *, actor_user_id: UUID
    ) -> QuotationResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            quote_date = cast(date, header["quote_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.QUOTATION,
                series=_QUOTE_SERIES,
                fiscal_year=quote_date.year,
                prefix=_QUOTE_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "quote_number": number,
                    "status": QuotationStatus.DRAFT.value,
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
                entity_type="quotation",
                entity_id=row.id,
                new_values=await self._quotation_snapshot(tenant_id, row),
            )
            loaded = await self._require(tenant_id, row.id)
            today, requires_approval = await self._response_context(tenant_id)
            return self._to_response(loaded, today, requires_approval=requires_approval)

    async def update(
        self,
        tenant_id: UUID,
        quotation_id: UUID,
        payload: QuotationUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> QuotationResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, quotation_id, for_update=True)
            old_values = await self._quotation_snapshot(tenant_id, existing)
            today, requires_approval = await self._response_context(tenant_id)
            assert_editable(self._effective_status(existing, today))
            self._assert_version(existing, expected_version)
            create_payload = await self._update_to_create(tenant_id, existing, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            await self.repo.update(tenant_id, quotation_id, header)
            await self.repo.replace_lines(tenant_id, quotation_id, line_rows)
            loaded = await self._require(tenant_id, quotation_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ERP_MODULE,
                entity_type="quotation",
                entity_id=quotation_id,
                old_values=old_values,
                new_values=await self._quotation_snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded, today, requires_approval=requires_approval)

    async def submit(
        self, tenant_id: UUID, quotation_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> QuotationResponse:
        return await self._transition(
            tenant_id, quotation_id, "submit", actor_user_id, expected_version=expected_version
        )

    async def approve(
        self, tenant_id: UUID, quotation_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> QuotationResponse:
        return await self._transition(
            tenant_id, quotation_id, "approve", actor_user_id, expected_version=expected_version
        )

    async def reject(
        self,
        tenant_id: UUID,
        quotation_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> QuotationResponse:
        return await self._transition(
            tenant_id,
            quotation_id,
            "reject",
            actor_user_id,
            expected_version=expected_version,
            reason=reason,
        )

    async def reopen(
        self, tenant_id: UUID, quotation_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> QuotationResponse:
        return await self._transition(
            tenant_id, quotation_id, "reopen", actor_user_id, expected_version=expected_version
        )

    async def send(
        self, tenant_id: UUID, quotation_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> QuotationResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, quotation_id, for_update=True)
            old_values = await self._quotation_snapshot(tenant_id, row)
            today, requires_approval = await self._response_context(tenant_id)
            current = self._effective_status(row, today)
            self._assert_version(row, expected_version)
            if current == QuotationStatus.DRAFT and requires_approval:
                raise ValidationError(
                    "This organization requires approval before a quotation can be sent"
                )
            target = next_status(current, "send")
            row.status = target.value
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.SEND,
                module=ERP_MODULE,
                entity_type="quotation",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._quotation_snapshot(tenant_id, row),
            )
            return self._to_response(row, today, requires_approval=requires_approval)

    async def accept(
        self, tenant_id: UUID, quotation_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> QuotationResponse:
        return await self._transition(
            tenant_id, quotation_id, "accept", actor_user_id, expected_version=expected_version
        )

    async def decline(
        self, tenant_id: UUID, quotation_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> QuotationResponse:
        return await self._transition(
            tenant_id, quotation_id, "decline", actor_user_id, expected_version=expected_version
        )

    async def cancel(
        self, tenant_id: UUID, quotation_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> QuotationResponse:
        return await self._transition(
            tenant_id, quotation_id, "cancel", actor_user_id, expected_version=expected_version
        )

    async def clone(
        self, tenant_id: UUID, quotation_id: UUID, *, actor_user_id: UUID
    ) -> QuotationResponse:
        async with transaction(self.session):
            source = await self._require(tenant_id, quotation_id)
            payload = QuotationCreate(
                customer_id=source.customer_id,
                contact_id=source.contact_id,
                branch_id=source.branch_id,
                quote_date=None,
                valid_until=source.valid_until,
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
                    QuotationLineInput(
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
            quote_date = cast(date, header["quote_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.QUOTATION,
                series=_QUOTE_SERIES,
                fiscal_year=quote_date.year,
                prefix=_QUOTE_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "quote_number": number,
                    "status": QuotationStatus.DRAFT.value,
                    "version": 1,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.repo.replace_lines(tenant_id, row.id, line_rows)
            new_values = await self._quotation_snapshot(tenant_id, row)
            new_values["cloned_from"] = source.quote_number
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CLONE,
                module=ERP_MODULE,
                entity_type="quotation",
                entity_id=row.id,
                new_values=new_values,
            )
            loaded = await self._require(tenant_id, row.id)
            today, requires_approval = await self._response_context(tenant_id)
            return self._to_response(loaded, today, requires_approval=requires_approval)

    async def delete(
        self,
        tenant_id: UUID,
        quotation_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> QuotationResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, quotation_id, for_update=True)
            today, requires_approval = await self._response_context(tenant_id)
            current = self._effective_status(row, today)
            if current != QuotationStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft quotations can be deleted")
            self._assert_version(row, expected_version)
            response = self._to_response(row, today, requires_approval=requires_approval)
            old_values = await self._quotation_snapshot(tenant_id, row)
            await self.repo.soft_delete(tenant_id, quotation_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="quotation",
                entity_id=quotation_id,
                old_values=old_values,
            )
            return response

    async def _transition(
        self,
        tenant_id: UUID,
        quotation_id: UUID,
        action: str,
        actor_user_id: UUID,
        *,
        expected_version: int,
        reason: str | None = None,
    ) -> QuotationResponse:
        action_map = {
            "submit": AuditAction.SUBMIT,
            "approve": AuditAction.APPROVE,
            "reject": AuditAction.REJECT,
            "reopen": AuditAction.UPDATE,
            "accept": AuditAction.ACCEPT,
            "decline": AuditAction.DECLINE,
            "cancel": AuditAction.CANCEL,
        }
        async with transaction(self.session):
            row = await self._require(tenant_id, quotation_id, for_update=True)
            old_values = await self._quotation_snapshot(tenant_id, row)
            today, requires_approval = await self._response_context(tenant_id)
            current = self._effective_status(row, today)
            self._assert_version(row, expected_version)
            target = next_status(current, action)
            row.status = target.value
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            new_values = await self._quotation_snapshot(tenant_id, row)
            if action == "reject" and reason:
                new_values["reason"] = reason
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=action_map[action],
                module=ERP_MODULE,
                entity_type="quotation",
                entity_id=row.id,
                old_values=old_values,
                new_values=new_values,
            )
            return self._to_response(row, today, requires_approval=requires_approval)

    async def _build_draft(
        self, tenant_id: UUID, payload: QuotationCreate
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

        currency_id = payload.currency_id or customer.currency_id
        await self.currencies.require_id(tenant_id, currency_id)
        base = await self.currencies.get_base(tenant_id)
        quote_date = payload.quote_date or await self._today(tenant_id)
        resolved = await self.fx.resolve(
            tenant_id,
            from_currency_id=currency_id,
            to_currency_id=base.id,
            on_date=quote_date,
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
            "quote_date": quote_date,
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
        }
        return header, line_rows

    async def _build_lines(
        self,
        tenant_id: UUID,
        lines: Sequence[QuotationLineInput],
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
                }
            )
            nets.append(net)
            taxes.append(tax_amount)
        return built, nets, taxes

    async def _update_to_create(
        self, tenant_id: UUID, existing: Quotation, payload: QuotationUpdate
    ) -> QuotationCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        lines = values.get("lines")
        line_inputs = (
            [QuotationLineInput.model_validate(item) for item in lines]
            if lines is not None
            else [
                QuotationLineInput(
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
        return QuotationCreate(
            customer_id=existing.customer_id,
            contact_id=values.get("contact_id", existing.contact_id),
            branch_id=values.get("branch_id", existing.branch_id),
            quote_date=values.get("quote_date", existing.quote_date),
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
            lines=line_inputs,
        )

    def _effective_status(self, row: Quotation, today: date) -> QuotationStatus:
        status = QuotationStatus(row.status)
        if (
            status == QuotationStatus.SENT
            and row.valid_until is not None
            and row.valid_until < today
        ):
            return QuotationStatus.EXPIRED
        return status

    def _available_actions(
        self, status: QuotationStatus, *, requires_approval: bool
    ) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            if action == "send" and status == QuotationStatus.DRAFT and requires_approval:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if has_permission(self.actor_permissions, QUOTATION_CREATE):
            actions.append("clone")
        if status == QuotationStatus.DRAFT and has_permission(
            self.actor_permissions, QUOTATION_DELETE
        ):
            actions.append("delete")
        return actions

    def _to_response(
        self, row: Quotation, today: date, *, requires_approval: bool
    ) -> QuotationResponse:
        status = self._effective_status(row, today)
        return QuotationResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            quote_number=row.quote_number,
            document_number=row.quote_number,
            status=status,
            version=row.version,
            is_posted=False,
            quote_date=row.quote_date,
            document_date=row.quote_date,
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
            converted_at=row.converted_at,
            converted_document_type=row.converted_document_type,
            converted_document_id=row.converted_document_id,
            available_actions=self._available_actions(status, requires_approval=requires_approval),
            lines=[QuotationLineResponse.model_validate(line) for line in row.lines],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _response_context(self, tenant_id: UUID) -> tuple[date, bool]:
        today = await self._today(tenant_id)
        requires_approval = await self.org.quotation_requires_approval(tenant_id)
        return today, requires_approval

    async def _today(self, tenant_id: UUID) -> date:
        return today_in_timezone(await self.org.get_timezone(tenant_id))

    def _assert_version(self, row: Quotation, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _quotation_snapshot(self, tenant_id: UUID, row: Quotation) -> dict[str, object]:
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
            "quote_number": row.quote_number,
            "status": row.status,
            "version": row.version,
            "quote_date": row.quote_date,
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
        }

    async def _require(
        self, tenant_id: UUID, quotation_id: UUID, *, for_update: bool = False
    ) -> Quotation:
        row = await self.repo.get(tenant_id, quotation_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Quotation not found")
        return row
