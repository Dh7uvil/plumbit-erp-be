"""Goods receipt compose, post, and constrained cancel."""

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    GOODS_RECEIPT_DELETE,
    GOODS_RECEIPT_POST,
    GOODS_RECEIPT_UPDATE,
    LANDED_COST_CREATE,
    PERIOD_OVERRIDE,
    PURCHASE_MODULE,
    PURCHASE_RETURN_CREATE,
    QUALITY_INSPECTION_CREATE,
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
from app.common.utils.document_totals import format_address_snapshot, place_of_supply_from_address
from app.core.enums import (
    AuditAction,
    DocumentType,
    ItemType,
    PlaceOfSupply,
    PurchaseOrderStatus,
    QcStatus,
    StockDocumentStatus,
    StockMovementType,
    TaxTreatment,
)
from app.core.exceptions import (
    DocumentStaleError,
    GrnCannotCancelError,
    GrnOverReceiptError,
    InvalidStatusTransitionError,
    ResourceNotFoundError,
    SupplierSkuNotMappedError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.inventory_posting import InventoryLedgerService
from app.erp.accounting.service import DocumentSequenceService
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService
from app.erp.purchase_orders.service import PurchaseOrderService
from app.erp.supplier_products.schemas import SupplierSkuResolveStatus
from app.erp.supplier_products.service import SupplierProductService
from app.erp.suppliers.service import SupplierService
from app.inventory_management.goods_receipts.models import GoodsReceipt, GoodsReceiptLine
from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository
from app.inventory_management.goods_receipts.schemas import (
    GoodsReceiptCreate,
    GoodsReceiptCreateFromPurchaseOrder,
    GoodsReceiptLineInput,
    GoodsReceiptLineResponse,
    GoodsReceiptResponse,
    GoodsReceiptUpdate,
)
from app.inventory_management.goods_receipts.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)
from app.inventory_management.products.service import ProductService
from app.inventory_management.stock.service import SOURCE_GOODS_RECEIPT, StockService
from app.inventory_management.warehouses.service import WarehouseService

_ZERO = Decimal("0")
_SERIES = "GRN"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": GOODS_RECEIPT_POST,
    "cancel": GOODS_RECEIPT_UPDATE,
}


class GoodsReceiptService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = GoodsReceiptRepository(session)
        self.stock = StockService(session)
        self.products = ProductService(session)
        self.warehouses = WarehouseService(session)
        self.org = OrganizationService(session)
        self.suppliers = SupplierService(session)
        self.supplier_products = SupplierProductService(session)
        self.purchase_orders = PurchaseOrderService(session, actor_permissions=actor_permissions)
        self.currencies = CurrencyService(session)
        self.fx = ExchangeRateService(session)
        self.sequences = DocumentSequenceService(session)
        self.idempotency = IdempotencyService(session)
        self.outbox = OutboxService(session)
        self.audit = AuditWriter(session)
        self.inventory_ledger = InventoryLedgerService(session, actor_permissions=actor_permissions)
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
        supplier_id: UUID | None = None,
        purchase_order_id: UUID | None = None,
        qc_status: str | None = None,
        product_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[builtins.list[GoodsReceiptResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if warehouse_id is not None:
            filters["warehouse_id"] = warehouse_id
        if supplier_id is not None:
            filters["supplier_id"] = supplier_id
        if purchase_order_id is not None:
            filters["purchase_order_id"] = purchase_order_id
        if qc_status is not None:
            filters["qc_status"] = qc_status
        extra: list[Any] = []
        if product_id is not None:
            extra.append(self.repo.has_product_clause(product_id))
        if document_date_from is not None:
            extra.append(GoodsReceipt.document_date >= document_date_from)
        if document_date_to is not None:
            extra.append(GoodsReceipt.document_date <= document_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, receipt_id: UUID) -> GoodsReceiptResponse:
        row = await self._require(tenant_id, receipt_id)
        await self._ensure_policy(tenant_id)
        response = self._to_response(row)
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def print_document(
        self,
        tenant_id: UUID,
        receipt_id: UUID,
        *,
        template_family: str = "uae",
    ) -> PrintDocumentResponse:
        row = await self.get(tenant_id, receipt_id)
        supplier = await self.suppliers.get(tenant_id, row.supplier_id)
        currency = await self.currencies.get(tenant_id, row.currency_id)
        printer = PrintService(self.session)
        family = template_family if template_family in {"uae", "china"} else "uae"
        return await printer.assemble(
            tenant_id,
            document_type=DocumentType.GOODS_RECEIPT.value,
            document_id=row.id,
            document_number=row.document_number,
            document_date=row.document_date,
            template_family=family,
            customer_code=supplier.code,
            customer_name=supplier.name,
            customer_address=format_address_snapshot(supplier.billing_address),
            customer_trn=supplier.trn,
            bl_number=row.bl_number,
            container_number=row.container_number,
            currency_code=currency.code,
            notes=row.notes,
            lines=[
                printer.commercial_line(line, index=index)
                for index, line in enumerate(row.lines, start=1)
            ],
        )

    async def create(
        self, tenant_id: UUID, payload: GoodsReceiptCreate, *, actor_user_id: UUID
    ) -> GoodsReceiptResponse:
        async with transaction(self.session):
            return await self._create_unlocked(tenant_id, payload, actor_user_id=actor_user_id)

    async def _create_unlocked(
        self, tenant_id: UUID, payload: GoodsReceiptCreate, *, actor_user_id: UUID
    ) -> GoodsReceiptResponse:
        header, line_rows = await self._build_draft(tenant_id, payload)
        document_date = cast(date, header["document_date"])
        policy = await self._ensure_policy(tenant_id)
        policy.assert_open(document_date, can_override=self._can_override)
        number = await self.sequences.allocate(
            tenant_id,
            document_type=DocumentType.GOODS_RECEIPT,
            series=_SERIES,
            fiscal_year=await year_for(self.session, tenant_id, document_date),
            prefix=_SERIES,
        )
        row = await self.repo.create(
            tenant_id,
            {
                **header,
                "document_number": number,
                "status": StockDocumentStatus.DRAFT.value,
                "is_posted": False,
                "version": 1,
                "qc_status": QcStatus.NOT_REQUIRED.value,
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
            entity_type="goods_receipt",
            entity_id=row.id,
            new_values=await self._snapshot(tenant_id, loaded),
        )
        return self._to_response(loaded)

    async def create_from_purchase_order(
        self,
        tenant_id: UUID,
        payload: GoodsReceiptCreateFromPurchaseOrder,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> GoodsReceiptResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return GoodsReceiptResponse.model_validate(replay)
            order = await self.purchase_orders.get(tenant_id, payload.purchase_order_id)
            if order.status != PurchaseOrderStatus.ISSUED:
                raise ValidationError(
                    "Goods receipts can only be created from an issued purchase order"
                )
            lines: list[GoodsReceiptLineInput] = []
            for line in order.lines:
                outstanding = quantize_quantity(line.quantity - line.qty_received)
                if outstanding <= _ZERO:
                    continue
                lines.append(
                    GoodsReceiptLineInput(
                        purchase_order_line_id=line.id,
                        product_id=line.product_id,
                        supplier_product_id=line.supplier_product_id,
                        supplier_sku=line.supplier_sku,
                        description=line.description,
                        quantity=outstanding,
                        unit_id=line.unit_id,
                        rate=line.rate,
                    )
                )
            if not lines:
                raise ValidationError("This purchase order has no remaining quantity to receive")
            warehouse_id = payload.warehouse_id or order.warehouse_id
            if warehouse_id is None:
                raise ValidationError("A warehouse is required to create a goods receipt")
            create_payload = GoodsReceiptCreate(
                supplier_id=order.supplier_id,
                warehouse_id=warehouse_id,
                document_date=payload.document_date,
                purchase_order_id=order.id,
                branch_id=order.branch_id,
                currency_id=order.currency_id,
                notes=payload.notes,
                lines=lines,
            )
            response = await self._create_unlocked(
                tenant_id, create_payload, actor_user_id=actor_user_id
            )
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def update(
        self,
        tenant_id: UUID,
        receipt_id: UUID,
        payload: GoodsReceiptUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> GoodsReceiptResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, receipt_id, for_update=True)
            assert_editable(StockDocumentStatus(existing.status))
            self._assert_version(existing, expected_version)
            old_values = await self._snapshot(tenant_id, existing)
            create_payload = await self._update_to_create(existing, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(cast(date, header["document_date"]), can_override=self._can_override)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            await self.repo.update(tenant_id, receipt_id, header)
            await self.repo.replace_lines(tenant_id, receipt_id, line_rows)
            loaded = await self._require(tenant_id, receipt_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=PURCHASE_MODULE,
                entity_type="goods_receipt",
                entity_id=receipt_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        receipt_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> GoodsReceiptResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, receipt_id, for_update=True)
            if StockDocumentStatus(row.status) != StockDocumentStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft goods receipts can be deleted")
            self._assert_version(row, expected_version)
            await self._ensure_policy(tenant_id)
            response = self._to_response(row)
            old_values = await self._snapshot(tenant_id, row)
            await self.repo.soft_delete(tenant_id, receipt_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=PURCHASE_MODULE,
                entity_type="goods_receipt",
                entity_id=receipt_id,
                old_values=old_values,
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        receipt_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> GoodsReceiptResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return GoodsReceiptResponse.model_validate(replay)
            row = await self._require(tenant_id, receipt_id, for_update=True)
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
            inbound = await self.org.get_inbound_settings(tenant_id)
            outstanding: dict[UUID, Decimal] = {}
            if row.purchase_order_id is not None:
                outstanding = await self.purchase_orders.outstanding_by_line(
                    tenant_id, row.purchase_order_id
                )
            po_receipts: dict[UUID, Decimal] = {}
            needs_qc = False
            occurred_at = utcnow()
            movement_type = self._movement_type(row)
            received_this_doc: dict[UUID, Decimal] = {}
            inventory_value = _ZERO
            for line in row.lines:
                await self._assert_supplier_sku_mapped(tenant_id, row.supplier_id, line)
                stockable = await self._is_stockable(tenant_id, line.product_id)
                if line.purchase_order_line_id is not None:
                    previous = received_this_doc.get(line.purchase_order_line_id, _ZERO)
                    remaining = outstanding.get(line.purchase_order_line_id, _ZERO)
                    self._assert_over_receipt_qty(
                        line,
                        remaining=remaining - previous,
                        allow_over=inbound.allow_over_receipt,
                        tolerance_pct=inbound.over_receipt_tolerance_pct,
                    )
                    received_this_doc[line.purchase_order_line_id] = previous + line.quantity
                    po_receipts[line.purchase_order_line_id] = received_this_doc[
                        line.purchase_order_line_id
                    ]
                if not stockable or line.product_id is None:
                    continue
                product = await self.products.get(tenant_id, line.product_id)
                unit_cost = quantize_money(line.rate * row.exchange_rate)
                hold_delta = line.quantity if product.requires_qc else _ZERO
                if product.requires_qc:
                    needs_qc = True
                    line.qty_on_hold = line.quantity
                locked = await self.stock.lock_balance(
                    tenant_id,
                    warehouse_id=row.warehouse_id,
                    product_id=line.product_id,
                    document_date=row.document_date,
                    can_override_soft_lock=self._can_override,
                )
                result = await self.stock.apply_locked(
                    tenant_id,
                    locked,
                    qty=line.quantity,
                    movement_type=movement_type,
                    source_type=SOURCE_GOODS_RECEIPT,
                    source_id=row.id,
                    source_line_id=line.id,
                    document_date=row.document_date,
                    notes=line.description or row.notes,
                    occurred_at=occurred_at,
                    unit_id=line.unit_id,
                    unit_cost=unit_cost,
                    quality_hold_delta=hold_delta,
                )
                if result.movement.value is not None:
                    inventory_value += result.movement.value
                if row.purchase_order_id is not None:
                    await self.stock.adjust_incoming_locked(
                        locked, qty=-min(locked.row.qty_incoming, line.quantity)
                    )
            if po_receipts:
                if row.purchase_order_id is None:
                    raise ValidationError("Purchase order is required to apply receipts")
                await self.purchase_orders.apply_line_receipts(
                    tenant_id, row.purchase_order_id, po_receipts
                )
            row.status = target.value
            row.is_posted = True
            row.posted_at = occurred_at
            row.posted_by = actor_user_id
            row.qc_status = QcStatus.PENDING.value if needs_qc else QcStatus.NOT_REQUIRED.value
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.inventory_ledger.post_goods_receipt(
                tenant_id,
                source_id=row.id,
                entry_date=row.document_date,
                amount=inventory_value,
                actor_id=actor_user_id,
                branch_id=row.branch_id,
                document_number=row.document_number,
            )
            if needs_qc:
                from app.inventory_management.quality_inspections.service import (
                    QualityInspectionService,
                )

                await QualityInspectionService(
                    self.session, actor_permissions=self.actor_permissions
                ).create_draft_for_goods_receipt(tenant_id, row.id, actor_user_id=actor_user_id)
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, receipt_id)
            await self._ensure_policy(tenant_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=PURCHASE_MODULE,
                entity_type="goods_receipt",
                entity_id=receipt_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="purchase.goods_receipt.posted",
                aggregate_type="goods_receipt",
                aggregate_id=receipt_id,
                payload={"goods_receipt_id": str(receipt_id)},
                dedupe_key=f"goods-receipt-posted:{receipt_id}",
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        receipt_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        endpoint: str | None = None,
    ) -> GoodsReceiptResponse:
        async with transaction(self.session):
            if idempotency_key and request_hash and endpoint:
                replay = await self.idempotency.begin(
                    tenant_id, idempotency_key, request_hash, endpoint=endpoint
                )
                if replay is not None:
                    return GoodsReceiptResponse.model_validate(replay)
            row = await self._require(tenant_id, receipt_id, for_update=True)
            self._assert_version(row, expected_version)
            current = StockDocumentStatus(row.status)
            old_values = await self._snapshot(tenant_id, row)
            if current == StockDocumentStatus.POSTED:
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
                entity_type="goods_receipt",
                entity_id=receipt_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            if current == StockDocumentStatus.POSTED:
                await self.outbox.enqueue(
                    tenant_id,
                    event_type="purchase.goods_receipt.cancelled",
                    aggregate_type="goods_receipt",
                    aggregate_id=receipt_id,
                    payload={"goods_receipt_id": str(receipt_id)},
                    dedupe_key=f"goods-receipt-cancelled:{receipt_id}",
                )
            response = self._to_response(row)
            if idempotency_key and request_hash and endpoint:
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
            return response

    async def apply_inspection_quantities(
        self,
        tenant_id: UUID,
        receipt_id: UUID,
        deltas: Sequence[tuple[UUID, Decimal, Decimal, Decimal]],
    ) -> GoodsReceipt:
        """Caller owns the transaction.

        Tuple is (grn_line_id, accepted, rejected, rework_released).
        """

        row = await self._require(tenant_id, receipt_id, for_update=True)
        by_id = {line.id: line for line in row.lines}
        for line_id, accepted, rejected, rework_released in deltas:
            line = by_id.get(line_id)
            if line is None:
                raise ValidationError("Goods receipt line not found on this receipt")
            released = quantize_quantity(accepted + rejected + rework_released)
            if released > line.qty_on_hold:
                raise ValidationError("Inspection quantities exceed remaining hold")
            line.qty_accepted = quantize_quantity(line.qty_accepted + accepted)
            line.qty_rejected = quantize_quantity(line.qty_rejected + rejected)
            line.qty_on_hold = quantize_quantity(line.qty_on_hold - released)
        row.qc_status = self._qc_status_from_lines(row.lines).value
        await self.session.flush()
        return row

    async def apply_line_bills(
        self,
        tenant_id: UUID,
        receipt_id: UUID,
        bills: Mapping[UUID, Decimal],
    ) -> None:
        """Caller owns the transaction. qty may be negative to reverse a bill."""

        row = await self._require(tenant_id, receipt_id, for_update=True)
        by_id = {line.id: line for line in row.lines}
        for line_id, qty in bills.items():
            line = by_id.get(line_id)
            if line is None:
                raise ValidationError("Goods receipt line not found on this receipt")
            line.qty_billed = quantize_quantity(line.qty_billed + qty)
            if line.qty_billed < _ZERO:
                raise ValidationError("Billed quantity cannot be negative")
        await self.session.flush()

    async def apply_line_returns(
        self,
        tenant_id: UUID,
        receipt_id: UUID,
        returns: Mapping[UUID, Decimal],
    ) -> None:
        """Caller owns the transaction. qty may be negative to reverse a return."""

        row = await self._require(tenant_id, receipt_id, for_update=True)
        by_id = {line.id: line for line in row.lines}
        for line_id, qty in returns.items():
            line = by_id.get(line_id)
            if line is None:
                raise ValidationError("Goods receipt line not found on this receipt")
            line.qty_returned = quantize_quantity(line.qty_returned + qty)
            if line.qty_returned < _ZERO:
                raise ValidationError("Returned quantity cannot be negative")
        await self.session.flush()

    async def _cancel_posted(
        self, tenant_id: UUID, row: GoodsReceipt, *, actor_user_id: UUID
    ) -> None:
        policy = await self._ensure_policy(tenant_id)
        if policy.is_locked(row.document_date, can_override=self._can_override):
            raise GrnCannotCancelError("The period is locked")
        from app.inventory_management.quality_inspections.service import QualityInspectionService

        inspections = QualityInspectionService(
            self.session, actor_permissions=self.actor_permissions
        )
        if await inspections.has_approved(tenant_id, row.id):
            raise GrnCannotCancelError("An approved quality inspection exists for this receipt")
        from app.inventory_management.purchase_returns.service import PurchaseReturnService

        if await PurchaseReturnService(
            self.session, actor_permissions=self.actor_permissions
        ).has_live_for_goods_receipt(tenant_id, row.id):
            raise GrnCannotCancelError("A purchase return exists for this receipt")
        if any(line.qty_accepted > _ZERO or line.qty_rejected > _ZERO for line in row.lines):
            raise GrnCannotCancelError("Quantity has already been QC-released or scrapped")
        if not await self.stock.costing.layers_fully_remaining(
            tenant_id, SOURCE_GOODS_RECEIPT, row.id
        ):
            raise GrnCannotCancelError("Cost layers from this receipt have been consumed")
        if any(line.qty_billed > _ZERO for line in row.lines):
            raise GrnCannotCancelError("This goods receipt has already been billed")
        if row.purchase_order_id is not None:
            billed = await self.purchase_orders.line_qty_billed_total(
                tenant_id, row.purchase_order_id
            )
            if billed > _ZERO:
                raise GrnCannotCancelError("Purchase order lines have already been billed")
        occurred_at = utcnow()
        movement_type = self._movement_type(row)
        po_reversals: dict[UUID, Decimal] = {}
        for line in row.lines:
            stockable = await self._is_stockable(tenant_id, line.product_id)
            if line.purchase_order_line_id is not None:
                po_reversals[line.purchase_order_line_id] = (
                    po_reversals.get(line.purchase_order_line_id, _ZERO) + line.quantity
                )
            if stockable and line.product_id is not None:
                locked = await self.stock.lock_balance(
                    tenant_id,
                    warehouse_id=row.warehouse_id,
                    product_id=line.product_id,
                    document_date=row.document_date,
                    can_override_soft_lock=self._can_override,
                )
                await self.stock.reverse_inbound_locked(
                    tenant_id,
                    locked,
                    qty=line.quantity,
                    movement_type=movement_type,
                    source_type=SOURCE_GOODS_RECEIPT,
                    source_id=row.id,
                    source_line_id=line.id,
                    document_date=row.document_date,
                    notes=row.cancel_reason or "GRN cancel",
                    quality_hold_delta=line.qty_on_hold,
                    occurred_at=occurred_at,
                    unit_id=line.unit_id,
                )
                outstanding_before = line.quantity
                incoming_restore = min(line.quantity, outstanding_before)
                await self.stock.adjust_incoming_locked(locked, qty=incoming_restore)
            line.qty_on_hold = _ZERO
            line.qty_accepted = _ZERO
            line.qty_rejected = _ZERO
        if po_reversals and row.purchase_order_id is not None:
            negated = {line_id: -qty for line_id, qty in po_reversals.items()}
            await self.purchase_orders.apply_line_receipts(
                tenant_id, row.purchase_order_id, negated
            )
        await inspections.cancel_drafts_for_goods_receipt(
            tenant_id, row.id, actor_user_id=actor_user_id
        )
        await self.inventory_ledger.reverse(
            tenant_id,
            source_type=SOURCE_GOODS_RECEIPT,
            source_id=row.id,
            reversal_date=row.document_date,
            reason=row.cancel_reason or "Goods receipt cancel",
            actor_id=actor_user_id,
        )
        row.qc_status = QcStatus.NOT_REQUIRED.value
        row.is_posted = False

    async def _build_draft(
        self, tenant_id: UUID, payload: GoodsReceiptCreate
    ) -> tuple[dict[str, Any], builtins.list[dict[str, Any]]]:
        supplier = await self.suppliers.get(tenant_id, payload.supplier_id)
        await self.warehouses.require_id(tenant_id, payload.warehouse_id)
        if payload.branch_id is not None:
            await self.org.require_branch(tenant_id, payload.branch_id)
        if payload.purchase_order_id is not None:
            order = await self.purchase_orders.get(tenant_id, payload.purchase_order_id)
            if order.supplier_id != payload.supplier_id:
                raise ValidationError("Supplier does not match the purchase order")
            tax_treatment = order.tax_treatment
            place = order.place_of_supply
            currency_id = payload.currency_id or order.currency_id
        else:
            tax_treatment = supplier.tax_treatment
            place = place_of_supply_from_address(
                supplier.shipping_address or supplier.billing_address
            )
            currency_id = payload.currency_id or supplier.currency_id
        document_date = payload.document_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        await self.currencies.require_id(tenant_id, currency_id)
        base = await self.currencies.get_base(tenant_id)
        resolved = await self.fx.resolve(
            tenant_id,
            from_currency_id=currency_id,
            to_currency_id=base.id,
            on_date=document_date,
        )
        line_rows = await self._build_lines(tenant_id, payload.lines)
        header: dict[str, Any] = {
            "document_date": document_date,
            "supplier_id": payload.supplier_id,
            "warehouse_id": payload.warehouse_id,
            "purchase_order_id": payload.purchase_order_id,
            "branch_id": payload.branch_id,
            "tax_treatment": tax_treatment.value,
            "place_of_supply": place.value,
            "currency_id": currency_id,
            "base_currency_id": base.id,
            "exchange_rate": resolved.rate,
            "supplier_invoice_number": payload.supplier_invoice_number,
            "delivery_challan_number": payload.delivery_challan_number,
            "bill_of_entry_number": payload.bill_of_entry_number,
            "bill_of_entry_date": payload.bill_of_entry_date,
            "container_number": payload.container_number,
            "bl_number": payload.bl_number,
            "notes": payload.notes,
        }
        return header, line_rows

    async def _build_lines(
        self, tenant_id: UUID, lines: Sequence[GoodsReceiptLineInput]
    ) -> builtins.list[dict[str, Any]]:
        if not lines:
            raise ValidationError("At least one line is required")
        built: builtins.list[dict[str, Any]] = []
        for index, line in enumerate(lines, start=1):
            if (
                line.product_id is None
                and not line.supplier_sku
                and line.purchase_order_line_id is None
            ):
                raise ValidationError(
                    "Each line needs a product, supplier SKU, or purchase order line"
                )
            description = line.description
            unit_id = line.unit_id
            if line.product_id is not None:
                product = await self.products.get(tenant_id, line.product_id)
                description = description or product.name
                unit_id = unit_id if unit_id is not None else product.unit_id
            if not description:
                raise ValidationError("Line description is required")
            built.append(
                {
                    "line_number": index,
                    "purchase_order_line_id": line.purchase_order_line_id,
                    "product_id": line.product_id,
                    "supplier_product_id": line.supplier_product_id,
                    "supplier_sku": line.supplier_sku,
                    "description": description,
                    "quantity": quantize_quantity(line.quantity),
                    "unit_id": unit_id,
                    "rate": quantize_money(line.rate),
                    "net_weight": line.net_weight,
                    "gross_weight": line.gross_weight,
                    "qty_accepted": _ZERO,
                    "qty_rejected": _ZERO,
                    "qty_on_hold": _ZERO,
                }
            )
        return built

    async def _update_to_create(
        self, existing: GoodsReceipt, payload: GoodsReceiptUpdate
    ) -> GoodsReceiptCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                GoodsReceiptLineInput(
                    purchase_order_line_id=line.purchase_order_line_id,
                    product_id=line.product_id,
                    supplier_product_id=line.supplier_product_id,
                    supplier_sku=line.supplier_sku,
                    description=line.description,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    net_weight=line.net_weight,
                    gross_weight=line.gross_weight,
                )
                for line in existing.lines
            ]
        return GoodsReceiptCreate(
            supplier_id=existing.supplier_id,
            warehouse_id=values.get("warehouse_id", existing.warehouse_id),
            document_date=values.get("document_date", existing.document_date),
            purchase_order_id=existing.purchase_order_id,
            branch_id=values.get("branch_id", existing.branch_id),
            currency_id=values.get("currency_id", existing.currency_id),
            supplier_invoice_number=values.get(
                "supplier_invoice_number", existing.supplier_invoice_number
            ),
            delivery_challan_number=values.get(
                "delivery_challan_number", existing.delivery_challan_number
            ),
            bill_of_entry_number=values.get("bill_of_entry_number", existing.bill_of_entry_number),
            bill_of_entry_date=values.get("bill_of_entry_date", existing.bill_of_entry_date),
            container_number=values.get("container_number", existing.container_number),
            bl_number=values.get("bl_number", existing.bl_number),
            notes=values.get("notes", existing.notes),
            lines=lines,
        )

    async def _assert_supplier_sku_mapped(
        self, tenant_id: UUID, supplier_id: UUID, line: GoodsReceiptLine
    ) -> None:
        if not line.supplier_sku:
            return
        resolved = await self.supplier_products.resolve(
            tenant_id, supplier_id=supplier_id, supplier_sku=line.supplier_sku
        )
        if resolved.status != SupplierSkuResolveStatus.MAPPED:
            raise SupplierSkuNotMappedError(
                details={
                    "supplier_sku": line.supplier_sku,
                    "status": resolved.status.value,
                    "line_number": line.line_number,
                }
            )
        if line.product_id is not None and resolved.product_id != line.product_id:
            raise ValidationError("Supplier SKU is mapped to a different product")

    def _assert_over_receipt_qty(
        self,
        line: GoodsReceiptLine,
        *,
        remaining: Decimal,
        allow_over: bool,
        tolerance_pct: Decimal | None,
    ) -> None:
        if remaining < _ZERO:
            remaining = _ZERO
        if allow_over and tolerance_pct is None:
            return
        allowed = remaining
        if allow_over and tolerance_pct is not None:
            allowed = quantize_quantity(remaining * (Decimal("1") + tolerance_pct / Decimal("100")))
        if line.quantity > allowed:
            raise GrnOverReceiptError(
                details={
                    "line_number": line.line_number,
                    "received_qty": str(line.quantity),
                    "outstanding_qty": str(remaining),
                    "allowed_qty": str(allowed),
                }
            )

    async def _is_stockable(self, tenant_id: UUID, product_id: UUID | None) -> bool:
        if product_id is None:
            return False
        product = await self.products.get(tenant_id, product_id)
        return product.item_type != ItemType.SERVICE and product.track_inventory

    def _movement_type(self, row: GoodsReceipt) -> StockMovementType:
        treatment = TaxTreatment(row.tax_treatment)
        place = PlaceOfSupply(row.place_of_supply)
        if treatment == TaxTreatment.EXPORT or place == PlaceOfSupply.OUTSIDE_UAE:
            return StockMovementType.IMPORT
        return StockMovementType.PURCHASE

    def _qc_status_from_lines(self, lines: Sequence[GoodsReceiptLine]) -> QcStatus:
        hold = sum((line.qty_on_hold for line in lines), _ZERO)
        accepted = sum((line.qty_accepted for line in lines), _ZERO)
        rejected = sum((line.qty_rejected for line in lines), _ZERO)
        if hold > _ZERO and accepted == _ZERO and rejected == _ZERO:
            return QcStatus.PENDING
        if hold > _ZERO:
            return QcStatus.PARTIAL
        if accepted > _ZERO or rejected > _ZERO:
            return QcStatus.CLEARED
        return QcStatus.NOT_REQUIRED

    def _available_actions(
        self, row: GoodsReceipt, status: StockDocumentStatus, *, period_locked: bool
    ) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            if action == "post" and period_locked:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == StockDocumentStatus.DRAFT and has_permission(
            self.actor_permissions, GOODS_RECEIPT_DELETE
        ):
            actions.append("delete")
        if (
            status == StockDocumentStatus.POSTED
            and QcStatus(row.qc_status) in {QcStatus.PENDING, QcStatus.PARTIAL}
            and has_permission(self.actor_permissions, QUALITY_INSPECTION_CREATE)
        ):
            actions.append("create_inspection")
        if status == StockDocumentStatus.POSTED and has_permission(
            self.actor_permissions, LANDED_COST_CREATE
        ):
            actions.append("create_landed_cost")
        if status == StockDocumentStatus.POSTED and has_permission(
            self.actor_permissions, PURCHASE_RETURN_CREATE
        ):
            actions.append("create_purchase_return")
        return actions

    def _to_response(self, row: GoodsReceipt) -> GoodsReceiptResponse:
        status = StockDocumentStatus(row.status)
        date_locked = self._date_in_locked_period(row.document_date)
        post_blocked = self._post_blocked(row.document_date)
        return GoodsReceiptResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=status == StockDocumentStatus.POSTED,
            document_date=row.document_date,
            supplier_id=row.supplier_id,
            warehouse_id=row.warehouse_id,
            purchase_order_id=row.purchase_order_id,
            branch_id=row.branch_id,
            tax_treatment=TaxTreatment(row.tax_treatment),
            place_of_supply=PlaceOfSupply(row.place_of_supply),
            currency_id=row.currency_id,
            base_currency_id=row.base_currency_id,
            exchange_rate=row.exchange_rate,
            supplier_invoice_number=row.supplier_invoice_number,
            delivery_challan_number=row.delivery_challan_number,
            bill_of_entry_number=row.bill_of_entry_number,
            bill_of_entry_date=row.bill_of_entry_date,
            container_number=row.container_number,
            bl_number=row.bl_number,
            notes=row.notes,
            qc_status=QcStatus(row.qc_status),
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            available_actions=self._available_actions(row, status, period_locked=post_blocked),
            period_locked=date_locked,
            lines=[GoodsReceiptLineResponse.model_validate(line) for line in row.lines],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _related_documents(
        self, tenant_id: UUID, row: GoodsReceipt
    ) -> builtins.list[RelatedDocumentRef]:
        from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository
        from app.erp.purchase_orders.repository import PurchaseOrderRepository
        from app.inventory_management.quality_inspections.repository import (
            QualityInspectionRepository,
        )

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
        for item in await PurchaseInvoiceRepository(self.session).list_for_goods_receipt(
            tenant_id, row.id
        ):
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
        for item in await QualityInspectionRepository(self.session).list_for_goods_receipt(
            tenant_id, row.id
        ):
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.QUALITY_INSPECTION.value,
                    document_id=item.id,
                    document_number=item.document_number,
                    status=item.status,
                    relationship="child",
                    document_date=item.inspection_date,
                )
            )
        from app.erp.landed_costs.repository import LandedCostRepository

        for item in await LandedCostRepository(self.session).list_for_goods_receipt(
            tenant_id, row.id
        ):
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.LANDED_COST.value,
                    document_id=item.id,
                    document_number=item.document_number,
                    status=item.status,
                    relationship="child",
                    document_date=item.document_date,
                )
            )
        return related

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

    def _assert_version(self, row: GoodsReceipt, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, tenant_id: UUID, row: GoodsReceipt) -> dict[str, object]:
        warehouse = await self.warehouses.get(tenant_id, row.warehouse_id)
        supplier = await self.suppliers.get(tenant_id, row.supplier_id)
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "document_date": row.document_date,
            "warehouse": warehouse.code,
            "supplier": supplier.name,
            "qc_status": row.qc_status,
            "line_count": len(row.lines),
        }

    async def _require(
        self, tenant_id: UUID, receipt_id: UUID, *, for_update: bool = False
    ) -> GoodsReceipt:
        row = await self.repo.get(tenant_id, receipt_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Goods receipt not found")
        return row
