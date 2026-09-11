"""Purchase order compose, totals, FX snapshot, and status transitions."""

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
    GOODS_RECEIPT_CREATE,
    PURCHASE_ORDER_APPROVE,
    PURCHASE_ORDER_CLOSE,
    PURCHASE_ORDER_CREATE,
    PURCHASE_ORDER_DELETE,
    PURCHASE_ORDER_ISSUE,
    PURCHASE_ORDER_UPDATE,
)
from app.auth.org_service import OrganizationService
from app.auth.schemas import AddressResponse
from app.common.idempotency.service import IdempotencyService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import QuantityProgress, RelatedDocumentRef
from app.common.services.audit import AuditWriter
from app.common.utils.conversion import quantity_summary, remaining_qty
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
    ItemType,
    PlaceOfSupply,
    PurchaseOrderStatus,
    ReceiptStatus,
    SalesOrderStatus,
    TaxCategory,
    TaxTreatment,
)
from app.core.exceptions import (
    DocumentStaleError,
    InvalidStatusTransitionError,
    PoCoverageExceededError,
    ResourceNotFoundError,
    SalesOrderNotConfirmedError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.crm.contacts.service import ContactService
from app.db.session import transaction
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.service import (
    DocumentSequenceService,
    PaymentTermService,
    TaxService,
    TermsTemplateService,
)
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService
from app.erp.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from app.erp.purchase_orders.repository import PurchaseOrderRepository
from app.erp.purchase_orders.schemas import (
    CoveragePurchaseOrderRef,
    PurchaseOrderComposeDefaults,
    PurchaseOrderCreate,
    PurchaseOrderFromSalesOrderRequest,
    PurchaseOrderLineInput,
    PurchaseOrderLineResponse,
    PurchaseOrderPlanGroup,
    PurchaseOrderPlanLine,
    PurchaseOrderPlanResponse,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
    SalesOrderCoverageLine,
    SalesOrderCoverageResponse,
)
from app.erp.purchase_orders.workflow import assert_editable, next_status, transition_actions
from app.erp.supplier_products.service import SupplierProductService
from app.erp.suppliers.service import SupplierService
from app.inventory_management.products.service import ProductService
from app.inventory_management.stock.service import StockService
from app.inventory_management.units.service import UnitService
from app.inventory_management.warehouses.service import WarehouseService

_ZERO = Decimal("0")
_ORDER_SERIES = "PO"
_ACTION_PERMISSIONS: dict[str, str] = {
    "submit": PURCHASE_ORDER_UPDATE,
    "approve": PURCHASE_ORDER_APPROVE,
    "reject": PURCHASE_ORDER_APPROVE,
    "reopen": PURCHASE_ORDER_UPDATE,
    "issue": PURCHASE_ORDER_ISSUE,
    "close": PURCHASE_ORDER_CLOSE,
    "cancel": PURCHASE_ORDER_UPDATE,
}


class PurchaseOrderService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = PurchaseOrderRepository(session)
        self.org = OrganizationService(session)
        self.suppliers = SupplierService(session)
        self.supplier_products = SupplierProductService(session)
        self.contacts = ContactService(session)
        self.products = ProductService(session)
        self.units = UnitService(session)
        self.warehouses = WarehouseService(session)
        self.stock = StockService(session)
        self.taxes = TaxService(session)
        self.payment_terms = PaymentTermService(session)
        self.terms = TermsTemplateService(session)
        self.sequences = DocumentSequenceService(session)
        self.currencies = CurrencyService(session)
        self.fx = ExchangeRateService(session)
        self.audit = AuditWriter(session)
        self.idempotency = IdempotencyService(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        receipt_status: str | None = None,
        billing_status: str | None = None,
        supplier_id: UUID | None = None,
        branch_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        currency_id: UUID | None = None,
        source_sales_order_id: UUID | None = None,
    ) -> tuple[list[PurchaseOrderResponse], int]:
        requires_approval = await self.org.purchase_order_requires_approval(tenant_id)
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if receipt_status is not None:
            filters["receipt_status"] = receipt_status
        if billing_status is not None:
            filters["billing_status"] = billing_status
        if supplier_id is not None:
            filters["supplier_id"] = supplier_id
        if branch_id is not None:
            filters["branch_id"] = branch_id
        if warehouse_id is not None:
            filters["warehouse_id"] = warehouse_id
        if currency_id is not None:
            filters["currency_id"] = currency_id
        if source_sales_order_id is not None:
            filters["source_sales_order_id"] = source_sales_order_id
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
        )
        return [self._to_response(row, requires_approval=requires_approval) for row in rows], total

    async def get(self, tenant_id: UUID, purchase_order_id: UUID) -> PurchaseOrderResponse:
        requires_approval = await self.org.purchase_order_requires_approval(tenant_id)
        row = await self._require(tenant_id, purchase_order_id)
        response = self._to_response(row, requires_approval=requires_approval)
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def compose_defaults(
        self, tenant_id: UUID, supplier_id: UUID
    ) -> PurchaseOrderComposeDefaults:
        supplier = await self.suppliers.get(tenant_id, supplier_id)
        primary = await self.contacts.get_primary(tenant_id, supplier_id)
        default_terms = await self.terms.get_default(tenant_id)
        default_warehouse = await self.warehouses.get_default(tenant_id)
        place = place_of_supply_from_address(supplier.shipping_address or supplier.billing_address)
        deliver_to = None
        if default_warehouse is not None:
            deliver_to = format_address_snapshot(default_warehouse.address)
        return PurchaseOrderComposeDefaults(
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            supplier_trn=supplier.trn,
            tax_treatment=supplier.tax_treatment,
            currency_id=supplier.currency_id,
            payment_terms_id=supplier.payment_terms_id,
            contact_id=primary.id if primary else None,
            warehouse_id=default_warehouse.id if default_warehouse else None,
            place_of_supply=place,
            supplier_address_snapshot=format_address_snapshot(
                supplier.billing_address or supplier.shipping_address
            ),
            deliver_to_snapshot=deliver_to,
            terms_and_conditions=default_terms.body if default_terms else None,
        )

    async def create(
        self, tenant_id: UUID, payload: PurchaseOrderCreate, *, actor_user_id: UUID
    ) -> PurchaseOrderResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            order_date = cast(date, header["order_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.PURCHASE_ORDER,
                series=_ORDER_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, order_date),
                prefix=_ORDER_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": PurchaseOrderStatus.DRAFT.value,
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
                entity_type="purchase_order",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, row),
            )
            loaded = await self._require(tenant_id, row.id)
            requires_approval = await self.org.purchase_order_requires_approval(tenant_id)
            return self._to_response(loaded, requires_approval=requires_approval)

    async def update(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        payload: PurchaseOrderUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PurchaseOrderResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, purchase_order_id, for_update=True)
            old_values = await self._snapshot(tenant_id, existing)
            requires_approval = await self.org.purchase_order_requires_approval(tenant_id)
            assert_editable(PurchaseOrderStatus(existing.status))
            self._assert_version(existing, expected_version)
            create_payload = await self._update_to_create(existing, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            header["source_sales_order_id"] = existing.source_sales_order_id
            if payload.lines is None:
                for built, existing_line in zip(line_rows, existing.lines, strict=True):
                    built["source_sales_order_line_id"] = existing_line.source_sales_order_line_id
            await self.repo.update(tenant_id, purchase_order_id, header)
            await self.repo.replace_lines(tenant_id, purchase_order_id, line_rows)
            loaded = await self._require(tenant_id, purchase_order_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ERP_MODULE,
                entity_type="purchase_order",
                entity_id=purchase_order_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded, requires_approval=requires_approval)

    async def submit(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PurchaseOrderResponse:
        return await self._transition(
            tenant_id, purchase_order_id, "submit", actor_user_id, expected_version=expected_version
        )

    async def approve(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PurchaseOrderResponse:
        return await self._transition(
            tenant_id,
            purchase_order_id,
            "approve",
            actor_user_id,
            expected_version=expected_version,
        )

    async def reject(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> PurchaseOrderResponse:
        return await self._transition(
            tenant_id,
            purchase_order_id,
            "reject",
            actor_user_id,
            expected_version=expected_version,
            reason=reason,
        )

    async def reopen(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PurchaseOrderResponse:
        return await self._transition(
            tenant_id, purchase_order_id, "reopen", actor_user_id, expected_version=expected_version
        )

    async def issue(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PurchaseOrderResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, purchase_order_id, for_update=True)
            old_values = await self._snapshot(tenant_id, row)
            requires_approval = await self.org.purchase_order_requires_approval(tenant_id)
            current = PurchaseOrderStatus(row.status)
            self._assert_version(row, expected_version)
            if current == PurchaseOrderStatus.DRAFT and requires_approval:
                raise ValidationError(
                    "This organization requires approval before a purchase order can be issued"
                )
            target = next_status(current, "issue")
            row.status = target.value
            row.issued_at = utcnow()
            row.issued_by = actor_user_id
            await self._apply_incoming_on_issue(tenant_id, row)
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.ISSUE,
                module=ERP_MODULE,
                entity_type="purchase_order",
                entity_id=row.id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            return self._to_response(row, requires_approval=requires_approval)

    async def close(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PurchaseOrderResponse:
        return await self._transition(
            tenant_id,
            purchase_order_id,
            "close",
            actor_user_id,
            expected_version=expected_version,
            extra={"closed_at": utcnow(), "closed_by": actor_user_id},
        )

    async def cancel(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> PurchaseOrderResponse:
        return await self._transition(
            tenant_id,
            purchase_order_id,
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
        self, tenant_id: UUID, purchase_order_id: UUID, *, actor_user_id: UUID
    ) -> PurchaseOrderResponse:
        async with transaction(self.session):
            source = await self._require(tenant_id, purchase_order_id)
            payload = PurchaseOrderCreate(
                supplier_id=source.supplier_id,
                contact_id=source.contact_id,
                branch_id=source.branch_id,
                warehouse_id=source.warehouse_id,
                order_date=None,
                expected_delivery_date=source.expected_delivery_date,
                reference_number=source.reference_number,
                currency_id=source.currency_id,
                payment_terms_id=source.payment_terms_id,
                notes=source.notes,
                terms_and_conditions=source.terms_and_conditions,
                discount_type=DiscountType(source.discount_type) if source.discount_type else None,
                discount_value=source.discount_value,
                shipping_amount=source.shipping_amount,
                adjustment_amount=source.adjustment_amount,
                place_of_supply=PlaceOfSupply(source.place_of_supply),
                lines=[
                    PurchaseOrderLineInput(
                        product_id=line.product_id,
                        supplier_product_id=line.supplier_product_id,
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
                document_type=DocumentType.PURCHASE_ORDER,
                series=_ORDER_SERIES,
                fiscal_year=await year_for(self.session, tenant_id, order_date),
                prefix=_ORDER_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": PurchaseOrderStatus.DRAFT.value,
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
                entity_type="purchase_order",
                entity_id=row.id,
                new_values=new_values,
            )
            loaded = await self._require(tenant_id, row.id)
            requires_approval = await self.org.purchase_order_requires_approval(tenant_id)
            return self._to_response(loaded, requires_approval=requires_approval)

    async def coverage_for_sales_order(
        self, tenant_id: UUID, sales_order_id: UUID
    ) -> SalesOrderCoverageResponse:
        from app.erp.sales_orders.service import SalesOrderService

        sales_orders = SalesOrderService(self.session, actor_permissions=self.actor_permissions)
        order = await sales_orders.get(tenant_id, sales_order_id)
        covering = await self.repo.list_covering_lines(tenant_id, [line.id for line in order.lines])
        by_line: dict[UUID, list[PurchaseOrderLine]] = {}
        for row in covering:
            if row.source_sales_order_line_id is None:
                continue
            by_line.setdefault(row.source_sales_order_line_id, []).append(row)

        lines: builtins.list[SalesOrderCoverageLine] = []
        for so_line in order.lines:
            po_lines = by_line.get(so_line.id, [])
            qty_covered = sum((item.quantity for item in po_lines), _ZERO)
            qty_received = sum((item.qty_received for item in po_lines), _ZERO)
            qty_uncovered = so_line.quantity - qty_covered
            if qty_uncovered < _ZERO:
                qty_uncovered = _ZERO
            lines.append(
                SalesOrderCoverageLine(
                    sales_order_line_id=so_line.id,
                    product_id=so_line.product_id,
                    description=so_line.description,
                    quantity=so_line.quantity,
                    qty_covered=qty_covered,
                    qty_uncovered=qty_uncovered,
                    qty_received=qty_received,
                    qty_reserved=so_line.qty_reserved,
                    qty_delivered=so_line.qty_delivered,
                    qty_returned=so_line.qty_returned,
                    purchase_orders=[
                        CoveragePurchaseOrderRef(
                            id=item.purchase_order.id,
                            document_number=item.purchase_order.document_number,
                            status=PurchaseOrderStatus(item.purchase_order.status),
                            quantity=item.quantity,
                            qty_received=item.qty_received,
                        )
                        for item in po_lines
                    ],
                )
            )
        return SalesOrderCoverageResponse(sales_order_id=order.id, lines=lines)

    async def plan_from_sales_order(
        self, tenant_id: UUID, sales_order_id: UUID
    ) -> PurchaseOrderPlanResponse:
        from app.erp.sales_orders.service import SalesOrderService

        sales_orders = SalesOrderService(self.session, actor_permissions=self.actor_permissions)
        order = await sales_orders.get(tenant_id, sales_order_id)
        if order.status != SalesOrderStatus.CONFIRMED:
            raise SalesOrderNotConfirmedError()
        coverage = await self.coverage_for_sales_order(tenant_id, sales_order_id)
        groups: dict[UUID, PurchaseOrderPlanGroup] = {}
        unassigned: builtins.list[PurchaseOrderPlanLine] = []
        for line in coverage.lines:
            if line.qty_uncovered <= _ZERO:
                continue
            if line.product_id is None:
                unassigned.append(
                    PurchaseOrderPlanLine(
                        sales_order_line_id=line.sales_order_line_id,
                        product_id=None,
                        description=line.description,
                        qty_uncovered=line.qty_uncovered,
                    )
                )
                continue
            catalogs, _ = await self.supplier_products.list(
                tenant_id,
                page=PageParams(page=1, page_size=1),
                product_id=line.product_id,
                is_preferred_supplier=True,
                is_active=True,
            )
            if not catalogs:
                unassigned.append(
                    PurchaseOrderPlanLine(
                        sales_order_line_id=line.sales_order_line_id,
                        product_id=line.product_id,
                        description=line.description,
                        qty_uncovered=line.qty_uncovered,
                    )
                )
                continue
            catalog = catalogs[0]
            group = groups.get(catalog.supplier_id)
            if group is None:
                group = PurchaseOrderPlanGroup(
                    supplier_id=catalog.supplier_id,
                    supplier_name=catalog.supplier_name or "",
                    currency_id=catalog.currency_id,
                    lines=[],
                )
                groups[catalog.supplier_id] = group
            group.lines.append(
                PurchaseOrderPlanLine(
                    sales_order_line_id=line.sales_order_line_id,
                    product_id=line.product_id,
                    description=line.description,
                    qty_uncovered=line.qty_uncovered,
                    supplier_product_id=catalog.id,
                    supplier_sku=catalog.supplier_sku,
                    catalog_price=catalog.price,
                    catalog_currency_id=catalog.currency_id,
                )
            )
        return PurchaseOrderPlanResponse(groups=list(groups.values()), unassigned=unassigned)

    async def create_from_sales_order(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        payload: PurchaseOrderFromSalesOrderRequest,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> builtins.list[PurchaseOrderResponse]:
        from app.erp.sales_orders.service import SalesOrderService

        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return [PurchaseOrderResponse.model_validate(item) for item in replay["orders"]]
            sales_orders = SalesOrderService(self.session, actor_permissions=self.actor_permissions)
            order = await sales_orders.get(tenant_id, sales_order_id)
            if order.status != SalesOrderStatus.CONFIRMED:
                raise SalesOrderNotConfirmedError()
            so_lines = {line.id: line for line in order.lines}
            coverage = await self.coverage_for_sales_order(tenant_id, sales_order_id)
            uncovered = {line.sales_order_line_id: line.qty_uncovered for line in coverage.lines}
            requested: dict[UUID, Decimal] = {}
            for group in payload.groups:
                for line in group.lines:
                    if line.sales_order_line_id not in so_lines:
                        raise ValidationError(
                            "sales_order_line_id does not belong to this sales order",
                            details={"field": "sales_order_line_id"},
                        )
                    requested[line.sales_order_line_id] = (
                        requested.get(line.sales_order_line_id, _ZERO) + line.quantity
                    )
            if not payload.allow_overcommit:
                for line_id, qty in requested.items():
                    available = uncovered.get(line_id, _ZERO)
                    if qty > available:
                        raise PoCoverageExceededError(
                            details={
                                "sales_order_line_id": str(line_id),
                                "qty_uncovered": str(available),
                                "qty_requested": str(qty),
                            }
                        )

            requires_approval = await self.org.purchase_order_requires_approval(tenant_id)
            responses: builtins.list[PurchaseOrderResponse] = []
            for group in payload.groups:
                create = PurchaseOrderCreate(
                    supplier_id=group.supplier_id,
                    branch_id=order.branch_id,
                    warehouse_id=group.warehouse_id or order.warehouse_id,
                    expected_delivery_date=group.expected_delivery_date,
                    currency_id=group.currency_id,
                    lines=[
                        PurchaseOrderLineInput(
                            product_id=so_lines[line.sales_order_line_id].product_id,
                            supplier_product_id=line.supplier_product_id,
                            description=so_lines[line.sales_order_line_id].description,
                            quantity=line.quantity,
                            unit_id=so_lines[line.sales_order_line_id].unit_id,
                            rate=line.rate,
                        )
                        for line in group.lines
                    ],
                )
                header, line_rows = await self._build_draft(tenant_id, create)
                header["source_sales_order_id"] = sales_order_id
                for built, input_line in zip(line_rows, group.lines, strict=True):
                    built["source_sales_order_line_id"] = input_line.sales_order_line_id
                order_date = cast(date, header["order_date"])
                number = await self.sequences.allocate(
                    tenant_id,
                    document_type=DocumentType.PURCHASE_ORDER,
                    series=_ORDER_SERIES,
                    fiscal_year=await year_for(self.session, tenant_id, order_date),
                    prefix=_ORDER_SERIES,
                )
                row = await self.repo.create(
                    tenant_id,
                    {
                        **header,
                        "document_number": number,
                        "status": PurchaseOrderStatus.DRAFT.value,
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
                    entity_type="purchase_order",
                    entity_id=row.id,
                    new_values=await self._snapshot(tenant_id, row),
                )
                loaded = await self._require(tenant_id, row.id)
                responses.append(self._to_response(loaded, requires_approval=requires_approval))

            await self.idempotency.store(
                tenant_id,
                idempotency_key,
                {"orders": [item.model_dump(mode="json") for item in responses]},
            )
            return responses

    async def delete(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PurchaseOrderResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, purchase_order_id, for_update=True)
            requires_approval = await self.org.purchase_order_requires_approval(tenant_id)
            current = PurchaseOrderStatus(row.status)
            if current != PurchaseOrderStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft purchase orders can be deleted")
            self._assert_version(row, expected_version)
            response = self._to_response(row, requires_approval=requires_approval)
            old_values = await self._snapshot(tenant_id, row)
            await self.repo.soft_delete(tenant_id, purchase_order_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ERP_MODULE,
                entity_type="purchase_order",
                entity_id=purchase_order_id,
                old_values=old_values,
            )
            return response

    async def _transition(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        action: str,
        actor_user_id: UUID,
        *,
        expected_version: int,
        reason: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> PurchaseOrderResponse:
        action_map = {
            "submit": AuditAction.SUBMIT,
            "approve": AuditAction.APPROVE,
            "reject": AuditAction.REJECT,
            "reopen": AuditAction.UPDATE,
            "close": AuditAction.CLOSE,
            "cancel": AuditAction.CANCEL,
        }
        async with transaction(self.session):
            row = await self._require(tenant_id, purchase_order_id, for_update=True)
            old_values = await self._snapshot(tenant_id, row)
            requires_approval = await self.org.purchase_order_requires_approval(tenant_id)
            current = PurchaseOrderStatus(row.status)
            self._assert_version(row, expected_version)
            if action == "cancel":
                self._assert_cancellable(row, current)
                if current == PurchaseOrderStatus.ISSUED:
                    await self._reverse_incoming_on_cancel(tenant_id, row)
            target = next_status(current, action)
            row.status = target.value
            row.version += 1
            row.updated_by = actor_user_id
            for name, value in (extra or {}).items():
                setattr(row, name, value)
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            new_values = await self._snapshot(tenant_id, row)
            if action == "reject" and reason:
                new_values["reason"] = reason
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=action_map[action],
                module=ERP_MODULE,
                entity_type="purchase_order",
                entity_id=row.id,
                old_values=old_values,
                new_values=new_values,
            )
            return self._to_response(row, requires_approval=requires_approval)

    def _assert_cancellable(self, row: PurchaseOrder, current: PurchaseOrderStatus) -> None:
        if current != PurchaseOrderStatus.ISSUED:
            return
        if (
            row.receipt_status != ReceiptStatus.NOT_RECEIVED.value
            or row.billing_status != BillingStatus.NOT_INVOICED.value
        ):
            raise InvalidStatusTransitionError(
                "An issued purchase order cannot be cancelled after receipt or billing has started"
            )

    async def apply_line_receipts(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        receipts: Mapping[UUID, Decimal],
    ) -> None:
        """Caller owns the transaction. qty may be negative to reverse a GRN."""

        row = await self._require(tenant_id, purchase_order_id, for_update=True)
        by_id = {line.id: line for line in row.lines}
        for line_id, qty in receipts.items():
            line = by_id.get(line_id)
            if line is None:
                raise ValidationError("Purchase order line not found on this order")
            line.qty_received = quantize_quantity(line.qty_received + qty)
            if line.qty_received < _ZERO:
                raise ValidationError("Received quantity cannot be negative")
        self._refresh_receipt_status(row)
        await self.session.flush()

    async def outstanding_by_line(
        self, tenant_id: UUID, purchase_order_id: UUID
    ) -> dict[UUID, Decimal]:
        row = await self._require(tenant_id, purchase_order_id)
        return {line.id: quantize_quantity(line.quantity - line.qty_received) for line in row.lines}

    async def line_qty_billed_total(self, tenant_id: UUID, purchase_order_id: UUID) -> Decimal:
        row = await self._require(tenant_id, purchase_order_id)
        return sum((line.qty_billed for line in row.lines), _ZERO)

    def _refresh_receipt_status(self, row: PurchaseOrder) -> None:
        if not row.lines:
            row.receipt_status = ReceiptStatus.NOT_RECEIVED.value
            return
        states: list[str] = []
        for line in row.lines:
            if line.qty_received <= _ZERO:
                states.append("none")
            elif line.qty_received >= line.quantity:
                states.append("full")
            else:
                states.append("partial")
        if all(item == "none" for item in states):
            row.receipt_status = ReceiptStatus.NOT_RECEIVED.value
        elif all(item == "full" for item in states):
            row.receipt_status = ReceiptStatus.RECEIVED.value
        else:
            row.receipt_status = ReceiptStatus.PARTIALLY_RECEIVED.value

    async def apply_line_bills(
        self,
        tenant_id: UUID,
        purchase_order_id: UUID,
        bills: Mapping[UUID, Decimal],
    ) -> None:
        """Caller owns the transaction. qty may be negative to reverse a bill."""

        row = await self._require(tenant_id, purchase_order_id, for_update=True)
        by_id = {line.id: line for line in row.lines}
        for line_id, qty in bills.items():
            line = by_id.get(line_id)
            if line is None:
                raise ValidationError("Purchase order line not found on this order")
            line.qty_billed = quantize_quantity(line.qty_billed + qty)
            if line.qty_billed < _ZERO:
                raise ValidationError("Billed quantity cannot be negative")
        self._refresh_billing_status(row)
        await self.session.flush()

    def _refresh_billing_status(self, row: PurchaseOrder) -> None:
        if not row.lines:
            row.billing_status = BillingStatus.NOT_INVOICED.value
            return
        states: list[str] = []
        for line in row.lines:
            if line.qty_billed <= _ZERO:
                states.append("none")
            elif line.qty_billed >= line.quantity:
                states.append("full")
            else:
                states.append("partial")
        if all(item == "none" for item in states):
            row.billing_status = BillingStatus.NOT_INVOICED.value
        elif all(item == "full" for item in states):
            row.billing_status = BillingStatus.INVOICED.value
        else:
            row.billing_status = BillingStatus.PARTIALLY_INVOICED.value

    async def _tracked_outstanding(
        self, tenant_id: UUID, row: PurchaseOrder
    ) -> builtins.list[tuple[PurchaseOrderLine, Decimal]]:
        tracked: builtins.list[tuple[PurchaseOrderLine, Decimal]] = []
        for line in row.lines:
            if line.product_id is None:
                continue
            product = await self.products.get(tenant_id, line.product_id)
            if product.item_type == ItemType.SERVICE or not product.track_inventory:
                continue
            outstanding = quantize_quantity(line.quantity - line.qty_received)
            if outstanding > _ZERO:
                tracked.append((line, outstanding))
        return tracked

    async def _apply_incoming_on_issue(self, tenant_id: UUID, row: PurchaseOrder) -> None:
        tracked = await self._tracked_outstanding(tenant_id, row)
        if not tracked:
            return
        warehouse_id = row.warehouse_id
        if warehouse_id is None:
            default_warehouse = await self.warehouses.get_default(tenant_id)
            if default_warehouse is None:
                raise ValidationError(
                    "A warehouse is required to issue a purchase order with tracked items"
                )
            row.warehouse_id = default_warehouse.id
            warehouse_id = default_warehouse.id
            if not row.deliver_to_snapshot:
                row.deliver_to_snapshot = format_address_snapshot(default_warehouse.address)
        for line, outstanding in tracked:
            if line.product_id is None:
                continue
            locked = await self.stock.lock_balance(
                tenant_id,
                warehouse_id=warehouse_id,
                product_id=line.product_id,
                document_date=row.order_date,
                assert_period=False,
            )
            await self.stock.adjust_incoming_locked(locked, qty=outstanding)

    async def _reverse_incoming_on_cancel(self, tenant_id: UUID, row: PurchaseOrder) -> None:
        tracked = await self._tracked_outstanding(tenant_id, row)
        if not tracked or row.warehouse_id is None:
            return
        for line, outstanding in tracked:
            if line.product_id is None:
                continue
            locked = await self.stock.lock_balance(
                tenant_id,
                warehouse_id=row.warehouse_id,
                product_id=line.product_id,
                document_date=row.order_date,
                assert_period=False,
            )
            await self.stock.adjust_incoming_locked(locked, qty=-outstanding)

    async def _resolve_warehouse(
        self, tenant_id: UUID, warehouse_id: UUID | None
    ) -> tuple[UUID | None, str | None]:
        if warehouse_id is None:
            default_warehouse = await self.warehouses.get_default(tenant_id)
            if default_warehouse is None:
                return None, None
            return default_warehouse.id, format_address_snapshot(default_warehouse.address)
        warehouse = await self.warehouses.get(tenant_id, warehouse_id)
        return warehouse.id, format_address_snapshot(warehouse.address)

    def _supplier_place_address(
        self, shipping: AddressResponse | None, billing: AddressResponse | None
    ) -> AddressResponse | None:
        return shipping or billing

    async def _build_draft(
        self, tenant_id: UUID, payload: PurchaseOrderCreate
    ) -> tuple[dict[str, object], builtins.list[dict[str, object]]]:
        supplier = await self.suppliers.get(tenant_id, payload.supplier_id)
        if payload.branch_id is not None:
            await self.org.require_branch(tenant_id, payload.branch_id)
        if payload.contact_id is not None:
            contact = await self.contacts.get(tenant_id, payload.contact_id)
            if contact.customer_id != supplier.id:
                raise ValidationError("Contact does not belong to this supplier")
        if payload.payment_terms_id is not None:
            await self.payment_terms.require_id(tenant_id, payload.payment_terms_id)

        warehouse_id, deliver_to = await self._resolve_warehouse(tenant_id, payload.warehouse_id)

        currency_id = payload.currency_id or supplier.currency_id
        await self.currencies.require_id(tenant_id, currency_id)
        base = await self.currencies.get_base(tenant_id)
        order_date = payload.order_date or await self._today(tenant_id)
        resolved = await self.fx.resolve(
            tenant_id,
            from_currency_id=currency_id,
            to_currency_id=base.id,
            on_date=order_date,
        )

        place = payload.place_of_supply or place_of_supply_from_address(
            self._supplier_place_address(supplier.shipping_address, supplier.billing_address)
        )
        terms_body = payload.terms_and_conditions
        if terms_body is None and payload.terms_template_id is not None:
            template = await self.terms.get(tenant_id, payload.terms_template_id)
            terms_body = template.body
        if terms_body is None:
            default_terms = await self.terms.get_default(tenant_id)
            terms_body = default_terms.body if default_terms else None

        line_rows, line_nets, line_taxes = await self._build_lines(
            tenant_id,
            payload.lines,
            supplier_id=supplier.id,
            currency_id=currency_id,
            tax_treatment=supplier.tax_treatment,
            place_of_supply=place,
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
            "expected_delivery_date": payload.expected_delivery_date,
            "reference_number": payload.reference_number,
            "branch_id": payload.branch_id,
            "warehouse_id": warehouse_id,
            "supplier_id": supplier.id,
            "contact_id": payload.contact_id,
            "supplier_trn": supplier.trn,
            "tax_treatment": supplier.tax_treatment.value,
            "place_of_supply": place.value,
            "currency_id": currency_id,
            "base_currency_id": base.id,
            "exchange_rate": resolved.rate,
            "payment_terms_id": payload.payment_terms_id or supplier.payment_terms_id,
            "notes": payload.notes,
            "terms_and_conditions": terms_body,
            "supplier_address_snapshot": format_address_snapshot(
                supplier.billing_address or supplier.shipping_address
            ),
            "deliver_to_snapshot": deliver_to,
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
            "receipt_status": ReceiptStatus.NOT_RECEIVED.value,
            "billing_status": BillingStatus.NOT_INVOICED.value,
        }
        return header, line_rows

    async def _build_lines(
        self,
        tenant_id: UUID,
        lines: Sequence[PurchaseOrderLineInput],
        *,
        supplier_id: UUID,
        currency_id: UUID,
        tax_treatment: TaxTreatment,
        place_of_supply: PlaceOfSupply,
    ) -> tuple[builtins.list[dict[str, object]], builtins.list[Decimal], builtins.list[Decimal]]:
        built: builtins.list[dict[str, object]] = []
        nets: builtins.list[Decimal] = []
        taxes: builtins.list[Decimal] = []
        default_tax = await self.taxes.get_default(tenant_id)
        for index, line in enumerate(lines, start=1):
            catalog = None
            if line.supplier_product_id is not None:
                catalog = await self.supplier_products.get(tenant_id, line.supplier_product_id)
                if catalog.supplier_id != supplier_id:
                    raise ValidationError(
                        "supplier_product_id does not belong to this purchase order's supplier",
                        details={"field": "supplier_product_id"},
                    )
                if (
                    catalog.product_id is not None
                    and line.product_id is not None
                    and catalog.product_id != line.product_id
                ):
                    raise ValidationError(
                        "product_id does not match the mapped supplier catalog product",
                        details={"field": "product_id"},
                    )
            product = None
            product_id = line.product_id or (catalog.product_id if catalog is not None else None)
            if product_id is not None:
                product = await self.products.get(tenant_id, product_id)
            description = (
                line.description
                or (catalog.supplier_item_name if catalog is not None else None)
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
            elif (
                catalog is not None
                and catalog.price is not None
                and catalog.currency_id == currency_id
            ):
                rate = quantize_money(catalog.price)
            elif product is not None:
                rate = quantize_money(product.purchase_rate)
            else:
                raise ValidationError("Custom lines require a rate")

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
                    "supplier_product_id": catalog.id if catalog is not None else None,
                    "supplier_sku": catalog.supplier_sku if catalog is not None else None,
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
                    "qty_received": _ZERO,
                    "qty_billed": _ZERO,
                }
            )
            nets.append(net)
            taxes.append(tax_amount)
        return built, nets, taxes

    async def _update_to_create(
        self, existing: PurchaseOrder, payload: PurchaseOrderUpdate
    ) -> PurchaseOrderCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        lines = values.get("lines")
        line_inputs = (
            [PurchaseOrderLineInput.model_validate(item) for item in lines]
            if lines is not None
            else [
                PurchaseOrderLineInput(
                    product_id=line.product_id,
                    supplier_product_id=line.supplier_product_id,
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
        return PurchaseOrderCreate(
            supplier_id=existing.supplier_id,
            contact_id=values.get("contact_id", existing.contact_id),
            branch_id=values.get("branch_id", existing.branch_id),
            warehouse_id=values.get("warehouse_id", existing.warehouse_id),
            order_date=values.get("order_date", existing.order_date),
            expected_delivery_date=values.get(
                "expected_delivery_date", existing.expected_delivery_date
            ),
            reference_number=values.get("reference_number", existing.reference_number),
            currency_id=values.get("currency_id", existing.currency_id),
            payment_terms_id=values.get("payment_terms_id", existing.payment_terms_id),
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

    def _available_actions(
        self,
        row: PurchaseOrder,
        status: PurchaseOrderStatus,
        *,
        requires_approval: bool,
    ) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            if action == "issue" and status == PurchaseOrderStatus.DRAFT and requires_approval:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if has_permission(self.actor_permissions, PURCHASE_ORDER_CREATE):
            actions.append("clone")
        if status == PurchaseOrderStatus.DRAFT and has_permission(
            self.actor_permissions, PURCHASE_ORDER_DELETE
        ):
            actions.append("delete")
        if (
            status == PurchaseOrderStatus.ISSUED
            and row.receipt_status != ReceiptStatus.RECEIVED.value
            and has_permission(self.actor_permissions, GOODS_RECEIPT_CREATE)
        ):
            actions.append("create_goods_receipt")
        return actions

    def _to_response(self, row: PurchaseOrder, *, requires_approval: bool) -> PurchaseOrderResponse:
        status = PurchaseOrderStatus(row.status)
        return PurchaseOrderResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=False,
            reference_number=row.reference_number,
            order_date=row.order_date,
            document_date=row.order_date,
            expected_delivery_date=row.expected_delivery_date,
            branch_id=row.branch_id,
            warehouse_id=row.warehouse_id,
            supplier_id=row.supplier_id,
            contact_id=row.contact_id,
            supplier_trn=row.supplier_trn,
            tax_treatment=TaxTreatment(row.tax_treatment),
            place_of_supply=PlaceOfSupply(row.place_of_supply),
            currency_id=row.currency_id,
            base_currency_id=row.base_currency_id,
            exchange_rate=row.exchange_rate,
            payment_terms_id=row.payment_terms_id,
            notes=row.notes,
            terms_and_conditions=row.terms_and_conditions,
            supplier_address_snapshot=row.supplier_address_snapshot,
            deliver_to_snapshot=row.deliver_to_snapshot,
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
            receipt_status=ReceiptStatus(row.receipt_status),
            billing_status=BillingStatus(row.billing_status),
            issued_at=row.issued_at,
            issued_by=row.issued_by,
            closed_at=row.closed_at,
            closed_by=row.closed_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            source_sales_order_id=row.source_sales_order_id,
            available_actions=self._available_actions(
                row, status, requires_approval=requires_approval
            ),
            quantity_progress=self._quantity_progress(row),
            related_documents=[],
            lines=[PurchaseOrderLineResponse.model_validate(line) for line in row.lines],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _quantity_progress(self, row: PurchaseOrder) -> QuantityProgress:
        ordered = sum((line.quantity for line in row.lines), _ZERO)
        received = sum((line.qty_received for line in row.lines), _ZERO)
        billed = sum((line.qty_billed for line in row.lines), _ZERO)
        return QuantityProgress(
            ordered=ordered,
            fulfilled=received,
            invoiced=billed,
            remaining_to_fulfill=remaining_qty(ordered, received),
            remaining_to_invoice=remaining_qty(ordered, billed),
        )

    async def _related_documents(
        self, tenant_id: UUID, row: PurchaseOrder
    ) -> builtins.list[RelatedDocumentRef]:
        from app.erp.debit_notes.repository import DebitNoteRepository
        from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository
        from app.erp.sales_orders.repository import SalesOrderRepository
        from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository

        related: builtins.list[RelatedDocumentRef] = []
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
        receipts = await GoodsReceiptRepository(self.session).list_for_purchase_orders(
            tenant_id, [row.id]
        )
        for item in receipts:
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.GOODS_RECEIPT.value,
                    document_id=item.id,
                    document_number=item.document_number,
                    status=item.status,
                    relationship="child",
                    document_date=item.document_date,
                    quantity_summary=quantity_summary([line.quantity for line in item.lines]),
                )
            )
        invoices = await PurchaseInvoiceRepository(self.session).list_for_purchase_order(
            tenant_id, row.id
        )
        dn_repo = DebitNoteRepository(self.session)
        for item in invoices:
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.PURCHASE_INVOICE.value,
                    document_id=item.id,
                    document_number=item.document_number,
                    status=item.status,
                    relationship="child",
                    document_date=item.invoice_date,
                    quantity_summary=quantity_summary([line.quantity for line in item.lines]),
                )
            )
            for note in await dn_repo.list_for_purchase_invoice(tenant_id, item.id):
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.DEBIT_NOTE.value,
                        document_id=note.id,
                        document_number=note.document_number,
                        status=note.status,
                        relationship="child",
                        document_date=note.debit_note_date,
                        quantity_summary=quantity_summary([line.quantity for line in note.lines]),
                    )
                )
        return related

    async def _today(self, tenant_id: UUID) -> date:
        return today_in_timezone(await self.org.get_timezone(tenant_id))

    def _assert_version(self, row: PurchaseOrder, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, tenant_id: UUID, row: PurchaseOrder) -> dict[str, object]:
        branch_name: str | None = None
        if row.branch_id is not None:
            branch_name = (await self.org.get_branch(tenant_id, row.branch_id)).name
        supplier = await self.suppliers.get(tenant_id, row.supplier_id)
        contact_name: str | None = None
        if row.contact_id is not None:
            contact_name = (await self.contacts.get(tenant_id, row.contact_id)).name
        currency = await self.currencies.get(tenant_id, row.currency_id)
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
            "supplier": supplier.name,
            "contact": contact_name,
            "tax_treatment": row.tax_treatment,
            "place_of_supply": row.place_of_supply,
            "currency": currency.code,
            "exchange_rate": row.exchange_rate,
            "payment_terms": payment_term_name,
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
            "receipt_status": row.receipt_status,
            "billing_status": row.billing_status,
        }

    async def _require(
        self, tenant_id: UUID, purchase_order_id: UUID, *, for_update: bool = False
    ) -> PurchaseOrder:
        row = await self.repo.get(tenant_id, purchase_order_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Purchase order not found")
        return row
