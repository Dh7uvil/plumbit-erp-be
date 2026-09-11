"""Purchase return compose and post. Consumes original GRN layers; no AP posting."""

from __future__ import annotations

import builtins
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    DEBIT_NOTE_CREATE,
    PERIOD_OVERRIDE,
    PURCHASE_MODULE,
    PURCHASE_RETURN_CANCEL,
    PURCHASE_RETURN_DELETE,
    PURCHASE_RETURN_POST,
    PURCHASE_RETURN_UPDATE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.registries.purchase_return_dependents import registered_probes
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.services.audit import AuditWriter
from app.common.utils.conversion import quantity_summary
from app.common.utils.currency import quantize_money, quantize_quantity
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.enums import (
    AuditAction,
    DocumentType,
    ItemType,
    PurchaseReturnDisposition,
    PurchaseReturnReason,
    StockDocumentStatus,
    StockMovementType,
)
from app.core.exceptions import (
    DocumentStaleError,
    InvalidStatusTransitionError,
    ResourceNotFoundError,
    PurchaseReturnCannotCancelError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.inventory_posting import InventoryLedgerService
from app.erp.accounting.service import DocumentSequenceService
from app.erp.purchase_orders.service import PurchaseOrderService
from app.inventory_management.goods_receipts.service import GoodsReceiptService
from app.inventory_management.products.service import ProductService
from app.inventory_management.purchase_returns.models import PurchaseReturn
from app.inventory_management.purchase_returns.repository import PurchaseReturnRepository
from app.inventory_management.purchase_returns.schemas import (
    PurchaseReturnCreate,
    PurchaseReturnLineInput,
    PurchaseReturnLineResponse,
    PurchaseReturnResponse,
    PurchaseReturnUpdate,
)
from app.inventory_management.purchase_returns.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)
from app.inventory_management.stock.service import (
    SOURCE_GOODS_RECEIPT,
    SOURCE_PURCHASE_RETURN,
    StockService,
)

_ZERO = Decimal("0")
_SERIES = "PR"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": PURCHASE_RETURN_POST,
    "cancel": PURCHASE_RETURN_CANCEL,
}


def _as_return_reason(value: object) -> PurchaseReturnReason:
    if isinstance(value, PurchaseReturnReason):
        return value
    return PurchaseReturnReason(str(value))


class PurchaseReturnService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = PurchaseReturnRepository(session)
        self.stock = StockService(session)
        self.products = ProductService(session)
        self.org = OrganizationService(session)
        self.goods_receipts = GoodsReceiptService(session, actor_permissions=actor_permissions)
        self.purchase_orders = PurchaseOrderService(session, actor_permissions=actor_permissions)
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
        goods_receipt_id: UUID | None = None,
        purchase_order_id: UUID | None = None,
        supplier_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[list[PurchaseReturnResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if goods_receipt_id is not None:
            filters["goods_receipt_id"] = goods_receipt_id
        if purchase_order_id is not None:
            filters["purchase_order_id"] = purchase_order_id
        if supplier_id is not None:
            filters["supplier_id"] = supplier_id
        if warehouse_id is not None:
            filters["warehouse_id"] = warehouse_id
        extra = []
        if document_date_from is not None:
            extra.append(PurchaseReturn.document_date >= document_date_from)
        if document_date_to is not None:
            extra.append(PurchaseReturn.document_date <= document_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, return_id: UUID) -> PurchaseReturnResponse:
        row = await self._require(tenant_id, return_id)
        await self._ensure_policy(tenant_id)
        response = self._to_response(row)
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def has_live_for_goods_receipt(self, tenant_id: UUID, goods_receipt_id: UUID) -> bool:
        return await self.repo.has_live_for_goods_receipt(tenant_id, goods_receipt_id)

    async def create(
        self, tenant_id: UUID, payload: PurchaseReturnCreate, *, actor_user_id: UUID
    ) -> PurchaseReturnResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(header["document_date"], can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.PURCHASE_RETURN,
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
                module=PURCHASE_MODULE,
                entity_type="purchase_return",
                entity_id=row.id,
                new_values={"document_number": loaded.document_number},
            )
            return self._to_response(loaded)

    async def update(
        self,
        tenant_id: UUID,
        return_id: UUID,
        payload: PurchaseReturnUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PurchaseReturnResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, return_id, for_update=True)
            assert_editable(StockDocumentStatus(existing.status))
            self._assert_version(existing, expected_version)
            create_payload = await self._update_to_create(existing, payload)
            header, line_rows = await self._build_draft(
                tenant_id, create_payload, exclude_return_id=return_id
            )
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(header["document_date"], can_override=self._can_override)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            await self.repo.update(tenant_id, return_id, header)
            await self.repo.replace_lines(tenant_id, return_id, line_rows)
            loaded = await self._require(tenant_id, return_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=PURCHASE_MODULE,
                entity_type="purchase_return",
                entity_id=return_id,
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        return_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> PurchaseReturnResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, return_id, for_update=True)
            if StockDocumentStatus(row.status) != StockDocumentStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft purchase returns can be deleted")
            self._assert_version(row, expected_version)
            await self._ensure_policy(tenant_id)
            response = self._to_response(row)
            await self.repo.soft_delete(tenant_id, return_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=PURCHASE_MODULE,
                entity_type="purchase_return",
                entity_id=return_id,
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        return_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> PurchaseReturnResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return PurchaseReturnResponse.model_validate(replay)
            row = await self._require(tenant_id, return_id, for_update=True)
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
            note = await self.goods_receipts.get(tenant_id, row.goods_receipt_id)
            if note.status != StockDocumentStatus.POSTED:
                raise ValidationError(
                    "Purchase returns can only be posted against a posted goods receipt"
                )
            dn_lines = {line.id: line for line in note.lines}
            occurred_at = utcnow()
            po_returns: dict[UUID, Decimal] = {}
            grn_returns: dict[UUID, Decimal] = {}
            returned_value = _ZERO
            for line in row.lines:
                dn_line = dn_lines.get(line.goods_receipt_line_id)
                if dn_line is None:
                    raise ValidationError("Goods receipt line not found on this note")
                already = await self.repo.posted_qty_for_goods_receipt_line(
                    tenant_id, line.goods_receipt_line_id, exclude_return_id=row.id
                )
                returnable = quantize_quantity(dn_line.quantity - already)
                if line.quantity > returnable:
                    raise ValidationError("Return quantity exceeds returnable quantity")
                stockable = await self._is_stockable(tenant_id, line.product_id)
                if stockable and line.product_id is not None:
                    locked = await self.stock.lock_balance(
                        tenant_id,
                        warehouse_id=row.warehouse_id,
                        product_id=line.product_id,
                        document_date=row.document_date,
                        can_override_soft_lock=self._can_override,
                    )
                    hold_release = min(line.quantity, locked.row.qty_quality_hold)
                    result = await self.stock.consume_source_locked(
                        tenant_id,
                        locked,
                        qty=line.quantity,
                        movement_type=StockMovementType.RETURN_OUT,
                        source_type=SOURCE_PURCHASE_RETURN,
                        source_id=row.id,
                        source_line_id=line.id,
                        document_date=row.document_date,
                        notes=line.notes or row.notes,
                        original_source_type=SOURCE_GOODS_RECEIPT,
                        original_source_id=row.goods_receipt_id,
                        original_source_line_id=dn_line.id,
                        quality_hold_delta=-hold_release,
                        occurred_at=occurred_at,
                        unit_id=line.unit_id,
                    )
                    if result.movement.value is not None:
                        returned_value += abs(result.movement.value)
                grn_returns[dn_line.id] = grn_returns.get(dn_line.id, _ZERO) + line.quantity
                if dn_line.purchase_order_line_id is not None:
                    po_returns[dn_line.purchase_order_line_id] = (
                        po_returns.get(dn_line.purchase_order_line_id, _ZERO) + line.quantity
                    )
            await self.goods_receipts.apply_line_returns(tenant_id, row.goods_receipt_id, grn_returns)
            if row.purchase_order_id is not None and po_returns:
                await self.purchase_orders.apply_line_returns(
                    tenant_id, row.purchase_order_id, po_returns
                )
            row.status = target.value
            row.is_posted = True
            row.posted_at = occurred_at
            row.posted_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.inventory_ledger.post_purchase_return(
                tenant_id,
                source_id=row.id,
                entry_date=row.document_date,
                amount=returned_value,
                actor_id=actor_user_id,
                document_number=row.document_number,
            )
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, return_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=PURCHASE_MODULE,
                entity_type="purchase_return",
                entity_id=return_id,
                new_values={"status": loaded.status},
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="purchase.purchase_return.posted",
                aggregate_type="purchase_return",
                aggregate_id=return_id,
                payload={"purchase_return_id": str(return_id)},
                dedupe_key=f"purchase-return-posted:{return_id}",
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        return_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> PurchaseReturnResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, return_id, for_update=True)
            self._assert_version(row, expected_version)
            current = StockDocumentStatus(row.status)
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
                entity_type="purchase_return",
                entity_id=return_id,
            )
            if current == StockDocumentStatus.POSTED:
                await self.outbox.enqueue(
                    tenant_id,
                    event_type="purchase.purchase_return.cancelled",
                    aggregate_type="purchase_return",
                    aggregate_id=return_id,
                    payload={"purchase_return_id": str(return_id)},
                    dedupe_key=f"purchase-return-cancelled:{return_id}",
                )
            return self._to_response(row)

    async def _cancel_posted(
        self, tenant_id: UUID, row: PurchaseReturn, *, actor_user_id: UUID
    ) -> None:
        policy = await self._ensure_policy(tenant_id)
        if policy.is_locked(row.document_date, can_override=self._can_override):
            raise PurchaseReturnCannotCancelError("The period is locked")
        for probe in registered_probes():
            if await probe(self.session, tenant_id, row.id):
                raise PurchaseReturnCannotCancelError(
                    "A debit note exists for this purchase return"
                )
        occurred_at = utcnow()
        po_returns: dict[UUID, Decimal] = {}
        grn_returns: dict[UUID, Decimal] = {}
        note = await self.goods_receipts.get(tenant_id, row.goods_receipt_id)
        dn_lines = {line.id: line for line in note.lines}
        for line in row.lines:
            dn_line = dn_lines.get(line.goods_receipt_line_id)
            if dn_line is None:
                raise ValidationError("Goods receipt line not found on this note")
            grn_returns[dn_line.id] = grn_returns.get(dn_line.id, _ZERO) + line.quantity
            if dn_line.purchase_order_line_id is not None:
                po_returns[dn_line.purchase_order_line_id] = (
                    po_returns.get(dn_line.purchase_order_line_id, _ZERO) + line.quantity
                )
            stockable = await self._is_stockable(tenant_id, line.product_id)
            if not stockable or line.product_id is None:
                continue
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
                movement_type=StockMovementType.RETURN_IN,
                source_type=SOURCE_PURCHASE_RETURN,
                source_id=row.id,
                source_line_id=line.id,
                document_date=row.document_date,
                notes=row.cancel_reason or "Purchase return cancel",
                original_source_type=SOURCE_PURCHASE_RETURN,
                original_source_id=row.id,
                original_source_line_id=line.id,
                occurred_at=occurred_at,
                unit_id=line.unit_id,
            )
        await self.goods_receipts.apply_line_returns(
            tenant_id, row.goods_receipt_id, {key: -qty for key, qty in grn_returns.items()}
        )
        if row.purchase_order_id is not None and po_returns:
            await self.purchase_orders.apply_line_returns(
                tenant_id, row.purchase_order_id, {key: -qty for key, qty in po_returns.items()}
            )
        await self.inventory_ledger.reverse(
            tenant_id,
            source_type=SOURCE_PURCHASE_RETURN,
            source_id=row.id,
            reversal_date=row.document_date,
            reason=row.cancel_reason or "Purchase return cancel",
            actor_id=actor_user_id,
        )
        row.is_posted = False

    async def _build_draft(
        self,
        tenant_id: UUID,
        payload: PurchaseReturnCreate,
        *,
        exclude_return_id: UUID | None = None,
    ) -> tuple[dict[str, Any], builtins.list[dict[str, Any]]]:
        note = await self.goods_receipts.get(tenant_id, payload.goods_receipt_id)
        if note.status != StockDocumentStatus.POSTED:
            raise ValidationError("Purchase returns require a posted goods receipt")
        document_date = payload.document_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        dn_lines = {line.id: line for line in note.lines}
        line_rows: builtins.list[dict[str, Any]] = []
        for index, line in enumerate(payload.lines, start=1):
            dn_line = dn_lines.get(line.goods_receipt_line_id)
            if dn_line is None:
                raise ValidationError("Goods receipt line not found on this note")
            already = await self.repo.posted_qty_for_goods_receipt_line(
                tenant_id, line.goods_receipt_line_id, exclude_return_id=exclude_return_id
            )
            returnable = quantize_quantity(dn_line.quantity - already)
            if line.quantity > returnable:
                raise ValidationError("Return quantity exceeds returnable quantity")
            product_id = line.product_id if line.product_id is not None else dn_line.product_id
            unit_id = line.unit_id if line.unit_id is not None else dn_line.unit_id
            line_rows.append(
                {
                    "line_number": index,
                    "goods_receipt_line_id": line.goods_receipt_line_id,
                    "product_id": product_id,
                    "quantity": quantize_quantity(line.quantity),
                    "unit_id": unit_id,
                    "rate": quantize_money(line.rate if line.rate else dn_line.rate),
                    "disposition": line.disposition.value,
                    "notes": line.notes,
                }
            )
        header: dict[str, Any] = {
            "document_date": document_date,
            "goods_receipt_id": note.id,
            "purchase_order_id": note.purchase_order_id,
            "supplier_id": note.supplier_id,
            "warehouse_id": note.warehouse_id,
            "reason_code": payload.reason_code.value,
            "notes": payload.notes,
        }
        return header, line_rows

    async def _update_to_create(
        self, existing: PurchaseReturn, payload: PurchaseReturnUpdate
    ) -> PurchaseReturnCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                PurchaseReturnLineInput(
                    goods_receipt_line_id=line.goods_receipt_line_id,
                    product_id=line.product_id,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    disposition=PurchaseReturnDisposition(line.disposition),
                    notes=line.notes,
                )
                for line in existing.lines
            ]
        return PurchaseReturnCreate(
            goods_receipt_id=existing.goods_receipt_id,
            document_date=values.get("document_date", existing.document_date),
            reason_code=_as_return_reason(values.get("reason_code", existing.reason_code)),
            notes=values.get("notes", existing.notes),
            lines=lines,
        )

    async def _is_stockable(self, tenant_id: UUID, product_id: UUID | None) -> bool:
        if product_id is None:
            return False
        product = await self.products.get(tenant_id, product_id)
        return product.item_type != ItemType.SERVICE and product.track_inventory

    def _to_response(self, row: PurchaseReturn) -> PurchaseReturnResponse:
        status = StockDocumentStatus(row.status)
        date_locked = self._date_in_locked_period(row.document_date)
        post_blocked = self._post_blocked(row.document_date)
        return PurchaseReturnResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=status == StockDocumentStatus.POSTED,
            document_date=row.document_date,
            goods_receipt_id=row.goods_receipt_id,
            purchase_order_id=row.purchase_order_id,
            supplier_id=row.supplier_id,
            warehouse_id=row.warehouse_id,
            reason_code=PurchaseReturnReason(row.reason_code),
            notes=row.notes,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            available_actions=self._available_actions(status, period_locked=post_blocked),
            period_locked=date_locked,
            related_documents=[],
            lines=[PurchaseReturnLineResponse.model_validate(line) for line in row.lines],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _available_actions(
        self, status: StockDocumentStatus, *, period_locked: bool
    ) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            if action == "post" and period_locked:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == StockDocumentStatus.DRAFT and has_permission(
            self.actor_permissions, PURCHASE_RETURN_DELETE
        ):
            actions.append("delete")
        if status == StockDocumentStatus.POSTED and has_permission(
            self.actor_permissions, DEBIT_NOTE_CREATE
        ):
            actions.append("create_debit_note")
        return actions

    async def _ensure_policy(self, tenant_id: UUID) -> PeriodLockPolicy:
        if self._period_policy is None:
            _, self._period_policy = await self.org.get_inventory_controls(tenant_id)
        return self._period_policy

    def _date_in_locked_period(self, document_date: date) -> bool:
        if self._period_policy is None:
            return False
        return self._period_policy.is_locked(document_date, can_override=False)

    async def _related_documents(
        self, tenant_id: UUID, row: PurchaseReturn
    ) -> builtins.list[RelatedDocumentRef]:
        from app.erp.debit_notes.repository import DebitNoteRepository
        from app.erp.purchase_orders.repository import PurchaseOrderRepository
        from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository

        related: builtins.list[RelatedDocumentRef] = []
        receipt = await GoodsReceiptRepository(self.session).get(tenant_id, row.goods_receipt_id)
        if receipt is not None:
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.GOODS_RECEIPT.value,
                    document_id=receipt.id,
                    document_number=receipt.document_number,
                    status=receipt.status,
                    relationship="source",
                    document_date=receipt.document_date,
                    quantity_summary=quantity_summary([line.quantity for line in receipt.lines]),
                )
            )
        if row.purchase_order_id is not None:
            order = await PurchaseOrderRepository(self.session).get(tenant_id, row.purchase_order_id)
            if order is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.PURCHASE_ORDER.value,
                        document_id=order.id,
                        document_number=order.document_number,
                        status=order.status,
                        relationship="source",
                        document_date=order.order_date,
                        quantity_summary=quantity_summary([line.quantity for line in order.lines]),
                    )
                )
        notes = await DebitNoteRepository(self.session).list_for_purchase_return(tenant_id, row.id)
        for note in notes:
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.DEBIT_NOTE.value,
                    document_id=note.id,
                    document_number=note.document_number,
                    status=note.status,
                    relationship="derived",
                    document_date=note.debit_note_date,
                    amount_summary=str(note.grand_total),
                )
            )
        return related

    def _post_blocked(self, document_date: date) -> bool:
        if self._period_policy is None:
            return False
        return self._period_policy.is_locked(document_date, can_override=self._can_override)

    def _assert_version(self, row: PurchaseReturn, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={"current_version": row.version, "provided_version": expected_version}
            )

    async def _require(
        self, tenant_id: UUID, return_id: UUID, *, for_update: bool = False
    ) -> PurchaseReturn:
        row = await self.repo.get(tenant_id, return_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Purchase return not found")
        return row
