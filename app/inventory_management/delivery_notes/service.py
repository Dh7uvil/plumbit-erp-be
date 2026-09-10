"""Delivery note compose, post, and constrained cancel."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    DELIVERY_NOTE_DELETE,
    DELIVERY_NOTE_POST,
    DELIVERY_NOTE_UPDATE,
    INVENTORY_MODULE,
    PERIOD_OVERRIDE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.registries.delivery_note_dependents import registered_probes
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money, quantize_quantity
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.enums import (
    AuditAction,
    DocumentType,
    ItemType,
    PlaceOfSupply,
    SalesOrderStatus,
    StockDocumentStatus,
    StockMovementType,
    TaxTreatment,
)
from app.core.exceptions import (
    DeliveryNoteCannotCancelError,
    DocumentStaleError,
    InvalidStatusTransitionError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.service import DocumentSequenceService
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService
from app.erp.sales_orders.service import SalesOrderService
from app.inventory_management.delivery_notes.models import DeliveryNote
from app.inventory_management.delivery_notes.repository import DeliveryNoteRepository
from app.inventory_management.delivery_notes.schemas import (
    DeliverableLineResponse,
    DeliveryNoteCreate,
    DeliveryNoteCreateFromSalesOrder,
    DeliveryNoteLineInput,
    DeliveryNoteLineResponse,
    DeliveryNoteResponse,
    DeliveryNoteUpdate,
)
from app.inventory_management.delivery_notes.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)
from app.inventory_management.products.service import ProductService
from app.inventory_management.stock.service import SOURCE_DELIVERY_NOTE, StockService
from app.inventory_management.warehouses.service import WarehouseService

_ZERO = Decimal("0")
_SERIES = "DN"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": DELIVERY_NOTE_POST,
    "cancel": DELIVERY_NOTE_UPDATE,
}


class DeliveryNoteService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = DeliveryNoteRepository(session)
        self.stock = StockService(session)
        self.products = ProductService(session)
        self.warehouses = WarehouseService(session)
        self.org = OrganizationService(session)
        self.sales_orders = SalesOrderService(session, actor_permissions=actor_permissions)
        self.currencies = CurrencyService(session)
        self.fx = ExchangeRateService(session)
        self.sequences = DocumentSequenceService(session)
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
        warehouse_id: UUID | None = None,
        customer_id: UUID | None = None,
        sales_order_id: UUID | None = None,
        shipment_id: UUID | None = None,
        unshipped: bool | None = None,
        product_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[list[DeliveryNoteResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if warehouse_id is not None:
            filters["warehouse_id"] = warehouse_id
        if customer_id is not None:
            filters["customer_id"] = customer_id
        if sales_order_id is not None:
            filters["sales_order_id"] = sales_order_id
        if shipment_id is not None:
            filters["shipment_id"] = shipment_id
        extra: list[Any] = []
        if unshipped:
            extra.append(DeliveryNote.shipment_id.is_(None))
            extra.append(DeliveryNote.status == StockDocumentStatus.POSTED.value)
        if product_id is not None:
            extra.append(self.repo.has_product_clause(product_id))
        if document_date_from is not None:
            extra.append(DeliveryNote.document_date >= document_date_from)
        if document_date_to is not None:
            extra.append(DeliveryNote.document_date <= document_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, note_id: UUID) -> DeliveryNoteResponse:
        row = await self._require(tenant_id, note_id)
        await self._ensure_policy(tenant_id)
        return self._to_response(row)

    async def create(
        self, tenant_id: UUID, payload: DeliveryNoteCreate, *, actor_user_id: UUID
    ) -> DeliveryNoteResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(header["document_date"], can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.DELIVERY_NOTE,
                series=_SERIES,
                fiscal_year=await year_for(
                    self.session, tenant_id, cast(date, header["document_date"])
                ),
                prefix=_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": StockDocumentStatus.DRAFT.value,
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
                module=INVENTORY_MODULE,
                entity_type="delivery_note",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def create_from_sales_order(
        self,
        tenant_id: UUID,
        payload: DeliveryNoteCreateFromSalesOrder,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> DeliveryNoteResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return DeliveryNoteResponse.model_validate(replay)
            order = await self.sales_orders.get(tenant_id, payload.sales_order_id)
            if order.status != SalesOrderStatus.CONFIRMED:
                raise ValidationError(
                    "Delivery notes can only be created from a confirmed sales order"
                )
            lines: list[DeliveryNoteLineInput] = []
            for line in order.lines:
                outstanding = quantize_quantity(line.quantity - line.qty_delivered)
                if outstanding <= _ZERO:
                    continue
                lines.append(
                    DeliveryNoteLineInput(
                        sales_order_line_id=line.id,
                        product_id=line.product_id,
                        description=line.description,
                        quantity=outstanding,
                        unit_id=line.unit_id,
                        rate=line.rate,
                    )
                )
            if not lines:
                raise ValidationError("This sales order has no remaining quantity to deliver")
            warehouse_id = payload.warehouse_id or order.warehouse_id
            if warehouse_id is None:
                default_warehouse = await self.warehouses.get_default(tenant_id)
                if default_warehouse is None:
                    raise ValidationError("A warehouse is required to create a delivery note")
                warehouse_id = default_warehouse.id
            create_payload = DeliveryNoteCreate(
                sales_order_id=order.id,
                warehouse_id=warehouse_id,
                document_date=payload.document_date,
                branch_id=order.branch_id,
                currency_id=order.currency_id,
                notes=payload.notes,
                lines=lines,
            )
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(header["document_date"], can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.DELIVERY_NOTE,
                series=_SERIES,
                fiscal_year=await year_for(
                    self.session, tenant_id, cast(date, header["document_date"])
                ),
                prefix=_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **header,
                    "document_number": number,
                    "status": StockDocumentStatus.DRAFT.value,
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
                module=INVENTORY_MODULE,
                entity_type="delivery_note",
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
        note_id: UUID,
        payload: DeliveryNoteUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> DeliveryNoteResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, note_id, for_update=True)
            old_values = await self._snapshot(tenant_id, existing)
            assert_editable(StockDocumentStatus(existing.status))
            self._assert_version(existing, expected_version)
            create_payload = await self._update_to_create(existing, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(header["document_date"], can_override=self._can_override)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            await self.repo.update(tenant_id, note_id, header)
            await self.repo.replace_lines(tenant_id, note_id, line_rows)
            loaded = await self._require(tenant_id, note_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="delivery_note",
                entity_id=note_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        note_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> DeliveryNoteResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, note_id, for_update=True)
            current = StockDocumentStatus(row.status)
            if current != StockDocumentStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft delivery notes can be deleted")
            self._assert_version(row, expected_version)
            await self._ensure_policy(tenant_id)
            response = self._to_response(row)
            old_values = await self._snapshot(tenant_id, row)
            await self.repo.soft_delete(tenant_id, note_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="delivery_note",
                entity_id=note_id,
                old_values=old_values,
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        note_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> DeliveryNoteResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return DeliveryNoteResponse.model_validate(replay)
            row = await self._require(tenant_id, note_id, for_update=True)
            if StockDocumentStatus(row.status) == StockDocumentStatus.POSTED:
                await self._ensure_policy(tenant_id)
                response = self._to_response(row)
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
                return response
            self._assert_version(row, expected_version)
            target = next_status(StockDocumentStatus(row.status), "post")
            if not row.lines:
                raise ValidationError("At least one line is required to post")
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(row.document_date, can_override=self._can_override)
            old_values = await self._snapshot(tenant_id, row)
            order = await self.sales_orders._require(tenant_id, row.sales_order_id, for_update=True)
            so_lines = {line.id: line for line in order.lines}
            occurred_at = utcnow()
            movement_type = self._movement_type(row)
            deliveries: dict[UUID, Decimal] = {}
            for line in row.lines:
                so_line = so_lines.get(line.sales_order_line_id)
                if so_line is None:
                    raise ValidationError("Sales order line not found on this order")
                outstanding = self.sales_orders.outstanding_delivery(so_line)
                if line.quantity > outstanding:
                    raise ValidationError(
                        "Delivery quantity exceeds outstanding quantity on the sales order line"
                    )
                stockable = await self._is_stockable(tenant_id, line.product_id)
                if stockable and line.product_id is not None:
                    locked = await self.stock.lock_balance(
                        tenant_id,
                        warehouse_id=row.warehouse_id,
                        product_id=line.product_id,
                        document_date=row.document_date,
                        can_override_soft_lock=self._can_override,
                    )
                    release_qty = min(quantize_quantity(so_line.qty_reserved), line.quantity)
                    if release_qty > _ZERO:
                        await self.stock.release_reserved_locked(locked, qty=release_qty)
                        so_line.qty_reserved = quantize_quantity(so_line.qty_reserved - release_qty)
                    await self.stock.apply_locked(
                        tenant_id,
                        locked,
                        qty=-line.quantity,
                        movement_type=movement_type,
                        source_type=SOURCE_DELIVERY_NOTE,
                        source_id=row.id,
                        source_line_id=line.id,
                        document_date=row.document_date,
                        notes=line.description or row.notes,
                        occurred_at=occurred_at,
                        unit_id=line.unit_id,
                    )
                deliveries[line.sales_order_line_id] = (
                    deliveries.get(line.sales_order_line_id, _ZERO) + line.quantity
                )
            await self.sales_orders.apply_line_deliveries(tenant_id, row.sales_order_id, deliveries)
            row.status = target.value
            row.is_posted = True
            row.posted_at = occurred_at
            row.posted_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, note_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=INVENTORY_MODULE,
                entity_type="delivery_note",
                entity_id=note_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="inventory.delivery_note.posted",
                aggregate_type="delivery_note",
                aggregate_id=note_id,
                payload={"delivery_note_id": str(note_id)},
                dedupe_key=f"delivery-note-posted:{note_id}",
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        note_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        endpoint: str | None = None,
    ) -> DeliveryNoteResponse:
        async with transaction(self.session):
            if idempotency_key and request_hash and endpoint:
                replay = await self.idempotency.begin(
                    tenant_id, idempotency_key, request_hash, endpoint=endpoint
                )
                if replay is not None:
                    return DeliveryNoteResponse.model_validate(replay)
            row = await self._require(tenant_id, note_id, for_update=True)
            self._assert_version(row, expected_version)
            current = StockDocumentStatus(row.status)
            old_values = await self._snapshot(tenant_id, row)
            if current == StockDocumentStatus.POSTED:
                await self._cancel_posted(tenant_id, row)
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
                module=INVENTORY_MODULE,
                entity_type="delivery_note",
                entity_id=note_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            if current == StockDocumentStatus.POSTED:
                await self.outbox.enqueue(
                    tenant_id,
                    event_type="inventory.delivery_note.cancelled",
                    aggregate_type="delivery_note",
                    aggregate_id=note_id,
                    payload={"delivery_note_id": str(note_id)},
                    dedupe_key=f"delivery-note-cancelled:{note_id}",
                )
            response = self._to_response(row)
            if idempotency_key and request_hash and endpoint:
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
            return response

    async def deliverable_lines(
        self, tenant_id: UUID, sales_order_id: UUID
    ) -> builtins.list[DeliverableLineResponse]:
        lines = await self.sales_orders.deliverable_lines(tenant_id, sales_order_id)
        return [
            DeliverableLineResponse(
                sales_order_line_id=line.id,
                product_id=line.product_id,
                description=line.description,
                unit_id=line.unit_id,
                rate=line.rate,
                quantity=line.quantity,
                qty_delivered=line.qty_delivered,
                qty_returned=line.qty_returned,
                qty_reserved=line.qty_reserved,
                outstanding=self.sales_orders.outstanding_delivery(line),
            )
            for line in lines
        ]

    async def attach_shipment(
        self, tenant_id: UUID, note_id: UUID, shipment_id: UUID
    ) -> DeliveryNote:
        row = await self._require(tenant_id, note_id, for_update=True)
        if StockDocumentStatus(row.status) != StockDocumentStatus.POSTED:
            raise ValidationError("Only posted delivery notes can join a shipment")
        if row.shipment_id is not None and row.shipment_id != shipment_id:
            raise ValidationError("This delivery note is already on a shipment")
        row.shipment_id = shipment_id
        await self.session.flush()
        return row

    async def detach_shipment(self, tenant_id: UUID, note_id: UUID, shipment_id: UUID) -> None:
        row = await self._require(tenant_id, note_id, for_update=True)
        if row.shipment_id != shipment_id:
            raise ValidationError("This delivery note is not on the shipment")
        row.shipment_id = None
        await self.session.flush()

    async def _cancel_posted(self, tenant_id: UUID, row: DeliveryNote) -> None:
        policy = await self._ensure_policy(tenant_id)
        if policy.is_locked(row.document_date, can_override=self._can_override):
            raise DeliveryNoteCannotCancelError("The period is locked")
        for probe in registered_probes():
            if await probe(self.session, tenant_id, row.id):
                raise DeliveryNoteCannotCancelError(
                    "This delivery note has dependent documents and cannot be cancelled"
                )
        occurred_at = utcnow()
        movement_type = (
            StockMovementType.RETURN_IN
            if self._movement_type(row) == StockMovementType.SALE
            else StockMovementType.IMPORT
        )
        reversals: dict[UUID, Decimal] = {}
        for line in row.lines:
            stockable = await self._is_stockable(tenant_id, line.product_id)
            reversals[line.sales_order_line_id] = (
                reversals.get(line.sales_order_line_id, _ZERO) + line.quantity
            )
            if stockable and line.product_id is not None:
                locked = await self.stock.lock_balance(
                    tenant_id,
                    warehouse_id=row.warehouse_id,
                    product_id=line.product_id,
                    document_date=row.document_date,
                    can_override_soft_lock=self._can_override,
                )
                await self.stock.reverse_outbound_locked(
                    tenant_id,
                    locked,
                    qty=line.quantity,
                    movement_type=movement_type,
                    source_type=SOURCE_DELIVERY_NOTE,
                    source_id=row.id,
                    source_line_id=line.id,
                    document_date=row.document_date,
                    notes=row.cancel_reason or "Delivery note cancel",
                    occurred_at=occurred_at,
                    unit_id=line.unit_id,
                )
        await self.sales_orders.apply_line_deliveries(
            tenant_id, row.sales_order_id, {key: -qty for key, qty in reversals.items()}
        )
        row.is_posted = False

    async def _build_draft(
        self, tenant_id: UUID, payload: DeliveryNoteCreate
    ) -> tuple[dict[str, Any], builtins.list[dict[str, Any]]]:
        order = await self.sales_orders.get(tenant_id, payload.sales_order_id)
        if order.status != SalesOrderStatus.CONFIRMED:
            raise ValidationError("Delivery notes can only be created from a confirmed sales order")
        warehouse_id = payload.warehouse_id or order.warehouse_id
        if warehouse_id is None:
            default_warehouse = await self.warehouses.get_default(tenant_id)
            if default_warehouse is None:
                raise ValidationError("A warehouse is required to create a delivery note")
            warehouse_id = default_warehouse.id
        await self.warehouses.require_id(tenant_id, warehouse_id)
        if payload.branch_id is not None:
            await self.org.require_branch(tenant_id, payload.branch_id)
        document_date = payload.document_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        currency_id = payload.currency_id or order.currency_id
        await self.currencies.require_id(tenant_id, currency_id)
        base = await self.currencies.get_base(tenant_id)
        resolved = await self.fx.resolve(
            tenant_id,
            from_currency_id=currency_id,
            to_currency_id=base.id,
            on_date=document_date,
        )
        line_rows = await self._build_lines(tenant_id, order.id, payload.lines)
        header: dict[str, Any] = {
            "document_date": document_date,
            "sales_order_id": payload.sales_order_id,
            "customer_id": order.customer_id,
            "warehouse_id": warehouse_id,
            "branch_id": payload.branch_id if payload.branch_id is not None else order.branch_id,
            "tax_treatment": order.tax_treatment.value,
            "place_of_supply": order.place_of_supply.value,
            "currency_id": currency_id,
            "base_currency_id": base.id,
            "exchange_rate": resolved.rate,
            "vehicle_number": payload.vehicle_number,
            "driver_name": payload.driver_name,
            "driver_contact": payload.driver_contact,
            "notes": payload.notes,
        }
        return header, line_rows

    async def _build_lines(
        self,
        tenant_id: UUID,
        sales_order_id: UUID,
        lines: Sequence[DeliveryNoteLineInput],
    ) -> builtins.list[dict[str, Any]]:
        if not lines:
            raise ValidationError("At least one line is required")
        order = await self.sales_orders._require(tenant_id, sales_order_id)
        so_lines = {line.id: line for line in order.lines}
        built: builtins.list[dict[str, Any]] = []
        for index, line in enumerate(lines, start=1):
            so_line = so_lines.get(line.sales_order_line_id)
            if so_line is None:
                raise ValidationError("Sales order line not found on this order")
            description = line.description or so_line.description
            product_id = line.product_id if line.product_id is not None else so_line.product_id
            unit_id = line.unit_id if line.unit_id is not None else so_line.unit_id
            if product_id is not None:
                product = await self.products.get(tenant_id, product_id)
                description = description or product.name
                unit_id = unit_id if unit_id is not None else product.unit_id
            if not description:
                raise ValidationError("Line description is required")
            built.append(
                {
                    "line_number": index,
                    "sales_order_line_id": line.sales_order_line_id,
                    "product_id": product_id,
                    "description": description,
                    "quantity": quantize_quantity(line.quantity),
                    "unit_id": unit_id,
                    "rate": quantize_money(line.rate if line.rate else so_line.rate),
                }
            )
        return built

    async def _update_to_create(
        self, existing: DeliveryNote, payload: DeliveryNoteUpdate
    ) -> DeliveryNoteCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                DeliveryNoteLineInput(
                    sales_order_line_id=line.sales_order_line_id,
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                )
                for line in existing.lines
            ]
        return DeliveryNoteCreate(
            sales_order_id=existing.sales_order_id,
            warehouse_id=values.get("warehouse_id", existing.warehouse_id),
            document_date=values.get("document_date", existing.document_date),
            branch_id=values.get("branch_id", existing.branch_id),
            currency_id=values.get("currency_id", existing.currency_id),
            vehicle_number=values.get("vehicle_number", existing.vehicle_number),
            driver_name=values.get("driver_name", existing.driver_name),
            driver_contact=values.get("driver_contact", existing.driver_contact),
            notes=values.get("notes", existing.notes),
            lines=lines,
        )

    async def _is_stockable(self, tenant_id: UUID, product_id: UUID | None) -> bool:
        if product_id is None:
            return False
        product = await self.products.get(tenant_id, product_id)
        return product.item_type != ItemType.SERVICE and product.track_inventory

    def _movement_type(self, row: DeliveryNote) -> StockMovementType:
        if (
            row.tax_treatment == TaxTreatment.EXPORT.value
            or row.place_of_supply == PlaceOfSupply.OUTSIDE_UAE.value
        ):
            return StockMovementType.EXPORT
        return StockMovementType.SALE

    def _available_actions(
        self, row: DeliveryNote, status: StockDocumentStatus, *, period_locked: bool
    ) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            if action == "post" and period_locked:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == StockDocumentStatus.DRAFT and has_permission(
            self.actor_permissions, DELIVERY_NOTE_DELETE
        ):
            actions.append("delete")
        return actions

    def _to_response(self, row: DeliveryNote) -> DeliveryNoteResponse:
        status = StockDocumentStatus(row.status)
        date_locked = self._date_in_locked_period(row.document_date)
        post_blocked = self._post_blocked(row.document_date)
        return DeliveryNoteResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=status == StockDocumentStatus.POSTED,
            document_date=row.document_date,
            sales_order_id=row.sales_order_id,
            customer_id=row.customer_id,
            warehouse_id=row.warehouse_id,
            branch_id=row.branch_id,
            shipment_id=row.shipment_id,
            tax_treatment=TaxTreatment(row.tax_treatment),
            place_of_supply=PlaceOfSupply(row.place_of_supply),
            currency_id=row.currency_id,
            base_currency_id=row.base_currency_id,
            exchange_rate=row.exchange_rate,
            vehicle_number=row.vehicle_number,
            driver_name=row.driver_name,
            driver_contact=row.driver_contact,
            notes=row.notes,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            available_actions=self._available_actions(row, status, period_locked=post_blocked),
            period_locked=date_locked,
            lines=[DeliveryNoteLineResponse.model_validate(line) for line in row.lines],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _ensure_policy(self, tenant_id: UUID) -> PeriodLockPolicy:
        if self._period_policy is None:
            _, self._period_policy = await self.org.get_inventory_controls(tenant_id)
        return self._period_policy

    def _date_in_locked_period(self, document_date: date) -> bool:
        if self._period_policy is None:
            return False
        return self._period_policy.is_locked(document_date, can_override=False)

    def _post_blocked(self, document_date: date) -> bool:
        if self._period_policy is None:
            return False
        return self._period_policy.is_locked(document_date, can_override=self._can_override)

    def _assert_version(self, row: DeliveryNote, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, tenant_id: UUID, row: DeliveryNote) -> dict[str, object]:
        warehouse = await self.warehouses.get(tenant_id, row.warehouse_id)
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "warehouse_code": warehouse.code,
            "sales_order_id": str(row.sales_order_id),
        }

    async def _require(
        self, tenant_id: UUID, note_id: UUID, *, for_update: bool = False
    ) -> DeliveryNote:
        row = await self.repo.get(tenant_id, note_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Delivery note not found")
        return row
