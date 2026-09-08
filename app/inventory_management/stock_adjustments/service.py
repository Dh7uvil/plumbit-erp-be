"""Stock adjustment compose, draft saves, and posting."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    INVENTORY_MODULE,
    STOCK_ADJUSTMENT_CREATE,
    STOCK_ADJUSTMENT_DELETE,
    STOCK_ADJUSTMENT_POST,
    STOCK_ADJUSTMENT_UPDATE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.enums import (
    AuditAction,
    DocumentType,
    StockAdjustmentReason,
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
from app.inventory_management.products.service import ProductService
from app.inventory_management.stock.service import SOURCE_STOCK_ADJUSTMENT, StockService
from app.inventory_management.stock_adjustments.models import StockAdjustment
from app.inventory_management.stock_adjustments.repository import StockAdjustmentRepository
from app.inventory_management.stock_adjustments.schemas import (
    StockAdjustmentCreate,
    StockAdjustmentLineInput,
    StockAdjustmentLineResponse,
    StockAdjustmentResponse,
    StockAdjustmentUpdate,
)
from app.inventory_management.stock_adjustments.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)
from app.inventory_management.warehouses.service import WarehouseService

_ZERO = Decimal("0")
_SERIES = "STA"
_REASON_MOVEMENT: dict[StockAdjustmentReason, StockMovementType] = {
    StockAdjustmentReason.OPENING_STOCK: StockMovementType.OPENING_STOCK,
    StockAdjustmentReason.DAMAGE: StockMovementType.DAMAGE,
    StockAdjustmentReason.COUNT: StockMovementType.ADJUSTMENT,
    StockAdjustmentReason.FOUND: StockMovementType.ADJUSTMENT,
    StockAdjustmentReason.OTHER: StockMovementType.ADJUSTMENT,
}
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": STOCK_ADJUSTMENT_POST,
    "cancel": STOCK_ADJUSTMENT_UPDATE,
}


class StockAdjustmentService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = StockAdjustmentRepository(session)
        self.stock = StockService(session)
        self.products = ProductService(session)
        self.warehouses = WarehouseService(session)
        self.org = OrganizationService(session)
        self.sequences = DocumentSequenceService(session)
        self.idempotency = IdempotencyService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        warehouse_id: UUID | None = None,
        reason: str | None = None,
        branch_id: UUID | None = None,
        product_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[builtins.list[StockAdjustmentResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if warehouse_id is not None:
            filters["warehouse_id"] = warehouse_id
        if reason is not None:
            filters["reason"] = reason
        if branch_id is not None:
            filters["branch_id"] = branch_id
        extra: list[Any] = []
        if product_id is not None:
            extra.append(self.repo.has_product_clause(product_id))
        if document_date_from is not None:
            extra.append(StockAdjustment.document_date >= document_date_from)
        if document_date_to is not None:
            extra.append(StockAdjustment.document_date <= document_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, adjustment_id: UUID) -> StockAdjustmentResponse:
        return self._to_response(await self._require(tenant_id, adjustment_id))

    async def create(
        self, tenant_id: UUID, payload: StockAdjustmentCreate, *, actor_user_id: UUID
    ) -> StockAdjustmentResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            document_date = cast(date, header["document_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.STOCK_ADJUSTMENT,
                series=_SERIES,
                fiscal_year=document_date.year,
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
                entity_type="stock_adjustment",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def update(
        self,
        tenant_id: UUID,
        adjustment_id: UUID,
        payload: StockAdjustmentUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> StockAdjustmentResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, adjustment_id, for_update=True)
            assert_editable(StockDocumentStatus(existing.status))
            self._assert_version(existing, expected_version)
            old_values = await self._snapshot(tenant_id, existing)
            create_payload = await self._update_to_create(tenant_id, existing, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            await self.repo.update(tenant_id, adjustment_id, header)
            await self.repo.replace_lines(tenant_id, adjustment_id, line_rows)
            loaded = await self._require(tenant_id, adjustment_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="stock_adjustment",
                entity_id=adjustment_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        adjustment_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> StockAdjustmentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, adjustment_id, for_update=True)
            if StockDocumentStatus(row.status) != StockDocumentStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft stock adjustments can be deleted")
            self._assert_version(row, expected_version)
            response = self._to_response(row)
            old_values = await self._snapshot(tenant_id, row)
            await self.repo.soft_delete(tenant_id, adjustment_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="stock_adjustment",
                entity_id=adjustment_id,
                old_values=old_values,
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        adjustment_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> StockAdjustmentResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return StockAdjustmentResponse.model_validate(replay)
            row = await self._require(tenant_id, adjustment_id, for_update=True)
            if StockDocumentStatus(row.status) == StockDocumentStatus.POSTED:
                response = self._to_response(row)
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
                return response
            self._assert_version(row, expected_version)
            target = next_status(StockDocumentStatus(row.status), "post")
            if not row.lines:
                raise ValidationError("At least one line is required to post")
            old_values = await self._snapshot(tenant_id, row)
            occurred_at = utcnow()
            reason = StockAdjustmentReason(row.reason)
            movement_type = _REASON_MOVEMENT[reason]
            for line in row.lines:
                locked = await self.stock.lock_balance(
                    tenant_id,
                    warehouse_id=row.warehouse_id,
                    product_id=line.product_id,
                    document_date=row.document_date,
                )
                line.qty_booked = locked.row.qty_on_hand
                if reason == StockAdjustmentReason.COUNT:
                    if line.qty_counted is None:
                        raise ValidationError("qty_counted is required when reason is COUNT")
                    line.qty_delta = line.qty_counted - line.qty_booked
                elif line.qty_delta is None or line.qty_delta == _ZERO:
                    raise ValidationError("qty_delta must be non-zero")
                if line.qty_delta != _ZERO:
                    await self.stock.apply_locked(
                        tenant_id,
                        locked,
                        qty=line.qty_delta,
                        movement_type=movement_type,
                        source_type=SOURCE_STOCK_ADJUSTMENT,
                        source_id=row.id,
                        source_line_id=line.id,
                        document_date=row.document_date,
                        notes=line.notes or row.notes or reason.value,
                        occurred_at=occurred_at,
                        unit_id=line.unit_id,
                    )
            row.status = target.value
            row.is_posted = True
            row.posted_at = occurred_at
            row.posted_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, adjustment_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=INVENTORY_MODULE,
                entity_type="stock_adjustment",
                entity_id=adjustment_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        adjustment_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> StockAdjustmentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, adjustment_id, for_update=True)
            self._assert_version(row, expected_version)
            old_values = await self._snapshot(tenant_id, row)
            target = next_status(StockDocumentStatus(row.status), "cancel")
            row.status = target.value
            row.cancelled_at = utcnow()
            row.cancelled_by = actor_user_id
            row.cancel_reason = reason
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CANCEL,
                module=INVENTORY_MODULE,
                entity_type="stock_adjustment",
                entity_id=adjustment_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            return self._to_response(row)

    async def clone(
        self, tenant_id: UUID, adjustment_id: UUID, *, actor_user_id: UUID
    ) -> StockAdjustmentResponse:
        source = await self._require(tenant_id, adjustment_id)
        payload = StockAdjustmentCreate(
            warehouse_id=source.warehouse_id,
            document_date=None,
            reason=StockAdjustmentReason(source.reason),
            branch_id=source.branch_id,
            reference=source.reference,
            notes=source.notes,
            lines=[
                StockAdjustmentLineInput(
                    product_id=line.product_id,
                    unit_id=line.unit_id,
                    qty_delta=line.qty_delta
                    if source.reason != StockAdjustmentReason.COUNT.value
                    else None,
                    qty_counted=line.qty_counted,
                    notes=line.notes,
                )
                for line in source.lines
            ],
        )
        row = await self.create(tenant_id, payload, actor_user_id=actor_user_id)
        return row

    async def _build_draft(
        self, tenant_id: UUID, payload: StockAdjustmentCreate
    ) -> tuple[dict[str, Any], builtins.list[dict[str, Any]]]:
        await self.warehouses.require_id(tenant_id, payload.warehouse_id)
        if payload.branch_id is not None:
            await self.org.require_branch(tenant_id, payload.branch_id)
        document_date = payload.document_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        line_rows = await self._build_lines(tenant_id, payload.reason, payload.lines)
        header: dict[str, Any] = {
            "document_date": document_date,
            "warehouse_id": payload.warehouse_id,
            "reason": payload.reason.value,
            "branch_id": payload.branch_id,
            "reference": payload.reference,
            "notes": payload.notes,
        }
        return header, line_rows

    async def _build_lines(
        self,
        tenant_id: UUID,
        reason: StockAdjustmentReason,
        lines: Sequence[StockAdjustmentLineInput],
    ) -> builtins.list[dict[str, Any]]:
        if not lines:
            raise ValidationError("At least one line is required")
        seen: set[UUID] = set()
        built: builtins.list[dict[str, Any]] = []
        for index, line in enumerate(lines, start=1):
            if line.product_id in seen:
                raise ValidationError("Duplicate product on the same document")
            seen.add(line.product_id)
            product = await self.products.require_stockable(tenant_id, line.product_id)
            unit_id = line.unit_id if line.unit_id is not None else product.unit_id
            if (
                line.unit_id is not None
                and product.unit_id is not None
                and line.unit_id != product.unit_id
            ):
                raise ValidationError("Unit must match the product unit")
            qty_counted: Decimal | None = None
            qty_delta: Decimal | None = None
            if reason == StockAdjustmentReason.COUNT:
                if line.qty_counted is None:
                    raise ValidationError("qty_counted is required when reason is COUNT")
                qty_counted = line.qty_counted
            else:
                if line.qty_delta is None or line.qty_delta == _ZERO:
                    raise ValidationError("qty_delta must be non-zero")
                qty_delta = line.qty_delta
            built.append(
                {
                    "line_number": index,
                    "product_id": line.product_id,
                    "unit_id": unit_id,
                    "qty_counted": qty_counted,
                    "qty_booked": None,
                    "qty_delta": qty_delta,
                    "notes": line.notes,
                }
            )
        return built

    async def _update_to_create(
        self,
        tenant_id: UUID,
        existing: StockAdjustment,
        payload: StockAdjustmentUpdate,
    ) -> StockAdjustmentCreate:
        values = payload.model_dump(exclude_unset=True)
        reason = (
            payload.reason if payload.reason is not None else StockAdjustmentReason(existing.reason)
        )
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                StockAdjustmentLineInput(
                    product_id=line.product_id,
                    unit_id=line.unit_id,
                    qty_delta=line.qty_delta,
                    qty_counted=line.qty_counted,
                    notes=line.notes,
                )
                for line in existing.lines
            ]
        return StockAdjustmentCreate(
            warehouse_id=values.get("warehouse_id", existing.warehouse_id),
            document_date=values.get("document_date", existing.document_date),
            reason=reason,
            branch_id=values.get("branch_id", existing.branch_id),
            reference=values.get("reference", existing.reference),
            notes=values.get("notes", existing.notes),
            lines=lines,
        )

    def _available_actions(self, status: StockDocumentStatus) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if has_permission(self.actor_permissions, STOCK_ADJUSTMENT_CREATE):
            actions.append("clone")
        if status == StockDocumentStatus.DRAFT and has_permission(
            self.actor_permissions, STOCK_ADJUSTMENT_DELETE
        ):
            actions.append("delete")
        return actions

    def _to_response(self, row: StockAdjustment) -> StockAdjustmentResponse:
        status = StockDocumentStatus(row.status)
        return StockAdjustmentResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=status == StockDocumentStatus.POSTED,
            document_date=row.document_date,
            warehouse_id=row.warehouse_id,
            reason=StockAdjustmentReason(row.reason),
            branch_id=row.branch_id,
            reference=row.reference,
            notes=row.notes,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            available_actions=self._available_actions(status),
            lines=[StockAdjustmentLineResponse.model_validate(line) for line in row.lines],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _assert_version(self, row: StockAdjustment, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, tenant_id: UUID, row: StockAdjustment) -> dict[str, object]:
        warehouse = await self.warehouses.get(tenant_id, row.warehouse_id)
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "document_date": row.document_date,
            "warehouse": warehouse.code,
            "reason": row.reason,
            "reference": row.reference,
            "line_count": len(row.lines),
        }

    async def _require(
        self, tenant_id: UUID, adjustment_id: UUID, *, for_update: bool = False
    ) -> StockAdjustment:
        row = await self.repo.get(tenant_id, adjustment_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Stock adjustment not found")
        return row
