"""Sales return compose and post. Restores original cost; no GL posting."""

from __future__ import annotations

import builtins
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    INVENTORY_MODULE,
    PERIOD_OVERRIDE,
    SALES_RETURN_DELETE,
    SALES_RETURN_POST,
    SALES_RETURN_UPDATE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money, quantize_quantity
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.enums import (
    AuditAction,
    DocumentType,
    ItemType,
    ReturnDisposition,
    SalesReturnReason,
    StockDocumentStatus,
    StockMovementType,
)
from app.core.exceptions import (
    DocumentStaleError,
    InvalidStatusTransitionError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.service import DocumentSequenceService
from app.erp.sales_orders.service import SalesOrderService
from app.inventory_management.delivery_notes.service import DeliveryNoteService
from app.inventory_management.products.service import ProductService
from app.inventory_management.sales_returns.models import SalesReturn
from app.inventory_management.sales_returns.repository import SalesReturnRepository
from app.inventory_management.sales_returns.schemas import (
    SalesReturnCreate,
    SalesReturnLineInput,
    SalesReturnLineResponse,
    SalesReturnResponse,
    SalesReturnUpdate,
)
from app.inventory_management.sales_returns.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)
from app.inventory_management.stock.service import (
    SOURCE_DELIVERY_NOTE,
    SOURCE_SALES_RETURN,
    StockService,
)

_ZERO = Decimal("0")
_SERIES = "SR"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": SALES_RETURN_POST,
    "cancel": SALES_RETURN_UPDATE,
}


def _as_return_reason(value: object) -> SalesReturnReason:
    if isinstance(value, SalesReturnReason):
        return value
    return SalesReturnReason(str(value))


class SalesReturnService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = SalesReturnRepository(session)
        self.stock = StockService(session)
        self.products = ProductService(session)
        self.org = OrganizationService(session)
        self.delivery_notes = DeliveryNoteService(session, actor_permissions=actor_permissions)
        self.sales_orders = SalesOrderService(session, actor_permissions=actor_permissions)
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
        delivery_note_id: UUID | None = None,
        sales_order_id: UUID | None = None,
        customer_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[list[SalesReturnResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if delivery_note_id is not None:
            filters["delivery_note_id"] = delivery_note_id
        if sales_order_id is not None:
            filters["sales_order_id"] = sales_order_id
        if customer_id is not None:
            filters["customer_id"] = customer_id
        if warehouse_id is not None:
            filters["warehouse_id"] = warehouse_id
        extra = []
        if document_date_from is not None:
            extra.append(SalesReturn.document_date >= document_date_from)
        if document_date_to is not None:
            extra.append(SalesReturn.document_date <= document_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, return_id: UUID) -> SalesReturnResponse:
        row = await self._require(tenant_id, return_id)
        await self._ensure_policy(tenant_id)
        return self._to_response(row)

    async def has_live_for_delivery_note(self, tenant_id: UUID, delivery_note_id: UUID) -> bool:
        return await self.repo.has_live_for_delivery_note(tenant_id, delivery_note_id)

    async def create(
        self, tenant_id: UUID, payload: SalesReturnCreate, *, actor_user_id: UUID
    ) -> SalesReturnResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(header["document_date"], can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.SALES_RETURN,
                series=_SERIES,
                fiscal_year=cast(date, header["document_date"]).year,
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
                entity_type="sales_return",
                entity_id=row.id,
                new_values={"document_number": loaded.document_number},
            )
            return self._to_response(loaded)

    async def update(
        self,
        tenant_id: UUID,
        return_id: UUID,
        payload: SalesReturnUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> SalesReturnResponse:
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
                module=INVENTORY_MODULE,
                entity_type="sales_return",
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
    ) -> SalesReturnResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, return_id, for_update=True)
            if StockDocumentStatus(row.status) != StockDocumentStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft sales returns can be deleted")
            self._assert_version(row, expected_version)
            await self._ensure_policy(tenant_id)
            response = self._to_response(row)
            await self.repo.soft_delete(tenant_id, return_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="sales_return",
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
    ) -> SalesReturnResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return SalesReturnResponse.model_validate(replay)
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
            note = await self.delivery_notes.get(tenant_id, row.delivery_note_id)
            if note.status != StockDocumentStatus.POSTED:
                raise ValidationError(
                    "Sales returns can only be posted against a posted delivery note"
                )
            dn_lines = {line.id: line for line in note.lines}
            occurred_at = utcnow()
            so_returns: dict[UUID, Decimal] = {}
            for line in row.lines:
                dn_line = dn_lines.get(line.delivery_note_line_id)
                if dn_line is None:
                    raise ValidationError("Delivery note line not found on this note")
                already = await self.repo.posted_qty_for_delivery_note_line(
                    tenant_id, line.delivery_note_line_id, exclude_return_id=row.id
                )
                returnable = quantize_quantity(dn_line.quantity - already)
                if line.quantity > returnable:
                    raise ValidationError("Return quantity exceeds returnable quantity")
                stockable = await self._is_stockable(tenant_id, line.product_id)
                disposition = ReturnDisposition(line.disposition)
                if stockable and line.product_id is not None:
                    locked = await self.stock.lock_balance(
                        tenant_id,
                        warehouse_id=row.warehouse_id,
                        product_id=line.product_id,
                        document_date=row.document_date,
                        can_override_soft_lock=self._can_override,
                    )
                    hold = line.quantity if disposition == ReturnDisposition.QC_HOLD else _ZERO
                    await self.stock.reverse_outbound_locked(
                        tenant_id,
                        locked,
                        qty=line.quantity,
                        movement_type=StockMovementType.RETURN_IN,
                        source_type=SOURCE_SALES_RETURN,
                        source_id=row.id,
                        source_line_id=line.id,
                        document_date=row.document_date,
                        notes=line.notes or row.notes,
                        original_source_type=SOURCE_DELIVERY_NOTE,
                        original_source_id=row.delivery_note_id,
                        original_source_line_id=dn_line.id,
                        quality_hold_delta=hold,
                        occurred_at=occurred_at,
                        unit_id=line.unit_id,
                    )
                    if disposition == ReturnDisposition.SCRAP:
                        await self.stock.apply_locked(
                            tenant_id,
                            locked,
                            qty=-line.quantity,
                            movement_type=StockMovementType.DAMAGE,
                            source_type=SOURCE_SALES_RETURN,
                            source_id=row.id,
                            source_line_id=line.id,
                            document_date=row.document_date,
                            notes=line.notes or "Sales return scrap",
                            occurred_at=occurred_at,
                            unit_id=line.unit_id,
                        )
                so_returns[dn_line.sales_order_line_id] = (
                    so_returns.get(dn_line.sales_order_line_id, _ZERO) + line.quantity
                )
            await self.sales_orders.apply_line_returns(tenant_id, row.sales_order_id, so_returns)
            row.status = target.value
            row.is_posted = True
            row.posted_at = occurred_at
            row.posted_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, return_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=INVENTORY_MODULE,
                entity_type="sales_return",
                entity_id=return_id,
                new_values={"status": loaded.status},
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="inventory.sales_return.posted",
                aggregate_type="sales_return",
                aggregate_id=return_id,
                payload={"sales_return_id": str(return_id)},
                dedupe_key=f"sales-return-posted:{return_id}",
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
    ) -> SalesReturnResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, return_id, for_update=True)
            self._assert_version(row, expected_version)
            target = next_status(StockDocumentStatus(row.status), "cancel")
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
                entity_type="sales_return",
                entity_id=return_id,
            )
            return self._to_response(row)

    async def _build_draft(
        self,
        tenant_id: UUID,
        payload: SalesReturnCreate,
        *,
        exclude_return_id: UUID | None = None,
    ) -> tuple[dict[str, Any], builtins.list[dict[str, Any]]]:
        note = await self.delivery_notes.get(tenant_id, payload.delivery_note_id)
        if note.status != StockDocumentStatus.POSTED:
            raise ValidationError("Sales returns require a posted delivery note")
        document_date = payload.document_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        dn_lines = {line.id: line for line in note.lines}
        line_rows: builtins.list[dict[str, Any]] = []
        for index, line in enumerate(payload.lines, start=1):
            dn_line = dn_lines.get(line.delivery_note_line_id)
            if dn_line is None:
                raise ValidationError("Delivery note line not found on this note")
            already = await self.repo.posted_qty_for_delivery_note_line(
                tenant_id, line.delivery_note_line_id, exclude_return_id=exclude_return_id
            )
            returnable = quantize_quantity(dn_line.quantity - already)
            if line.quantity > returnable:
                raise ValidationError("Return quantity exceeds returnable quantity")
            product_id = line.product_id if line.product_id is not None else dn_line.product_id
            unit_id = line.unit_id if line.unit_id is not None else dn_line.unit_id
            line_rows.append(
                {
                    "line_number": index,
                    "delivery_note_line_id": line.delivery_note_line_id,
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
            "delivery_note_id": note.id,
            "sales_order_id": note.sales_order_id,
            "customer_id": note.customer_id,
            "warehouse_id": note.warehouse_id,
            "reason_code": payload.reason_code.value,
            "notes": payload.notes,
        }
        return header, line_rows

    async def _update_to_create(
        self, existing: SalesReturn, payload: SalesReturnUpdate
    ) -> SalesReturnCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                SalesReturnLineInput(
                    delivery_note_line_id=line.delivery_note_line_id,
                    product_id=line.product_id,
                    quantity=line.quantity,
                    unit_id=line.unit_id,
                    rate=line.rate,
                    disposition=ReturnDisposition(line.disposition),
                    notes=line.notes,
                )
                for line in existing.lines
            ]
        return SalesReturnCreate(
            delivery_note_id=existing.delivery_note_id,
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

    def _to_response(self, row: SalesReturn) -> SalesReturnResponse:
        status = StockDocumentStatus(row.status)
        date_locked = self._date_in_locked_period(row.document_date)
        post_blocked = self._post_blocked(row.document_date)
        return SalesReturnResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=status == StockDocumentStatus.POSTED,
            document_date=row.document_date,
            delivery_note_id=row.delivery_note_id,
            sales_order_id=row.sales_order_id,
            customer_id=row.customer_id,
            warehouse_id=row.warehouse_id,
            reason_code=SalesReturnReason(row.reason_code),
            notes=row.notes,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            available_actions=self._available_actions(status, period_locked=post_blocked),
            period_locked=date_locked,
            lines=[SalesReturnLineResponse.model_validate(line) for line in row.lines],
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
            self.actor_permissions, SALES_RETURN_DELETE
        ):
            actions.append("delete")
        return actions

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

    def _assert_version(self, row: SalesReturn, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={"current_version": row.version, "provided_version": expected_version}
            )

    async def _require(
        self, tenant_id: UUID, return_id: UUID, *, for_update: bool = False
    ) -> SalesReturn:
        row = await self.repo.get(tenant_id, return_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Sales return not found")
        return row
