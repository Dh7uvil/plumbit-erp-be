"""Quality inspection compose and approve."""

from __future__ import annotations

import builtins
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    INVENTORY_MODULE,
    PERIOD_OVERRIDE,
    QUALITY_INSPECTION_APPROVE,
    QUALITY_INSPECTION_UPDATE,
)
from app.auth.org_service import OrganizationService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_quantity
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.enums import (
    AuditAction,
    DocumentType,
    QcDisposition,
    QualityInspectionStatus,
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
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.inventory_posting import InventoryLedgerService
from app.erp.accounting.service import DocumentSequenceService
from app.inventory_management.goods_receipts.service import GoodsReceiptService
from app.inventory_management.quality_inspections.models import QualityInspection
from app.inventory_management.quality_inspections.repository import QualityInspectionRepository
from app.inventory_management.quality_inspections.schemas import (
    QualityInspectionCreate,
    QualityInspectionLineInput,
    QualityInspectionLineResponse,
    QualityInspectionResponse,
    QualityInspectionUpdate,
)
from app.inventory_management.quality_inspections.workflow import (
    assert_editable,
    assert_line_quantities,
    next_status,
    transition_actions,
)
from app.inventory_management.stock.service import SOURCE_QUALITY_INSPECTION, StockService

_ZERO = Decimal("0")
_SERIES = "QCR"
_ACTION_PERMISSIONS: dict[str, str] = {
    "approve": QUALITY_INSPECTION_APPROVE,
    "cancel": QUALITY_INSPECTION_UPDATE,
}


class QualityInspectionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = QualityInspectionRepository(session)
        self.receipts = GoodsReceiptService(session, actor_permissions=actor_permissions)
        self.stock = StockService(session)
        self.org = OrganizationService(session)
        self.sequences = DocumentSequenceService(session)
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
        inspection_date_from: date | None = None,
        inspection_date_to: date | None = None,
    ) -> tuple[builtins.list[QualityInspectionResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if goods_receipt_id is not None:
            filters["goods_receipt_id"] = goods_receipt_id
        extra: list[Any] = []
        if inspection_date_from is not None:
            extra.append(QualityInspection.inspection_date >= inspection_date_from)
        if inspection_date_to is not None:
            extra.append(QualityInspection.inspection_date <= inspection_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, inspection_id: UUID) -> QualityInspectionResponse:
        row = await self._require(tenant_id, inspection_id)
        await self._ensure_policy(tenant_id)
        return self._to_response(row)

    async def create(
        self, tenant_id: UUID, payload: QualityInspectionCreate, *, actor_user_id: UUID
    ) -> QualityInspectionResponse:
        async with transaction(self.session):
            return await self._create_unlocked(tenant_id, payload, actor_user_id=actor_user_id)

    async def create_draft_for_goods_receipt(
        self, tenant_id: UUID, receipt_id: UUID, *, actor_user_id: UUID
    ) -> QualityInspectionResponse | None:
        receipt = await self.receipts.get(tenant_id, receipt_id)
        hold_lines = [line for line in receipt.lines if line.qty_on_hold > _ZERO]
        if not hold_lines:
            return None
        payload = QualityInspectionCreate(
            goods_receipt_id=receipt.id,
            lines=[
                QualityInspectionLineInput(
                    goods_receipt_line_id=line.id,
                    qty_inspected=line.qty_on_hold,
                    qty_accepted=line.qty_on_hold,
                    qty_rejected=_ZERO,
                    qty_rework=_ZERO,
                )
                for line in hold_lines
            ],
        )
        return await self._create_unlocked(tenant_id, payload, actor_user_id=actor_user_id)

    async def update(
        self,
        tenant_id: UUID,
        inspection_id: UUID,
        payload: QualityInspectionUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> QualityInspectionResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, inspection_id, for_update=True)
            assert_editable(QualityInspectionStatus(existing.status))
            self._assert_version(existing, expected_version)
            old_values = await self._snapshot(existing)
            create_payload = self._update_to_create(existing, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(header["inspection_date"], can_override=self._can_override)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            await self.repo.update(tenant_id, inspection_id, header)
            await self.repo.replace_lines(tenant_id, inspection_id, line_rows)
            loaded = await self._require(tenant_id, inspection_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="quality_inspection",
                entity_id=inspection_id,
                old_values=old_values,
                new_values=await self._snapshot(loaded),
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        inspection_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> QualityInspectionResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, inspection_id, for_update=True)
            if QualityInspectionStatus(row.status) != QualityInspectionStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft quality inspections can be deleted")
            self._assert_version(row, expected_version)
            await self._ensure_policy(tenant_id)
            response = self._to_response(row)
            old_values = await self._snapshot(row)
            await self.repo.soft_delete(tenant_id, inspection_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="quality_inspection",
                entity_id=inspection_id,
                old_values=old_values,
            )
            return response

    async def approve(
        self,
        tenant_id: UUID,
        inspection_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> QualityInspectionResponse:
        async with transaction(self.session):
            from app.common.idempotency.service import IdempotencyService

            idempotency = IdempotencyService(self.session)
            replay = await idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return QualityInspectionResponse.model_validate(replay)
            row = await self._require(tenant_id, inspection_id, for_update=True)
            if QualityInspectionStatus(row.status) == QualityInspectionStatus.APPROVED:
                await self._ensure_policy(tenant_id)
                response = self._to_response(row)
                await idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
                return response
            self._assert_version(row, expected_version)
            target = next_status(QualityInspectionStatus(row.status), "approve")
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(row.inspection_date, can_override=self._can_override)
            receipt = await self.receipts.get(tenant_id, row.goods_receipt_id)
            if receipt.status != StockDocumentStatus.POSTED:
                raise ValidationError(
                    "Goods receipt must be posted before inspection can be approved"
                )
            hold_by_line = {line.id: line.qty_on_hold for line in receipt.lines}
            product_by_grn_line = {line.id: line.product_id for line in receipt.lines}
            unit_by_grn_line = {line.id: line.unit_id for line in receipt.lines}
            old_values = await self._snapshot(row)
            occurred_at = utcnow()
            deltas: list[tuple[UUID, Decimal, Decimal, Decimal]] = []
            scrap_value = _ZERO
            for line in row.lines:
                remaining = hold_by_line.get(line.goods_receipt_line_id, _ZERO)
                disposition = QcDisposition(line.disposition) if line.disposition else None
                assert_line_quantities(
                    qty_inspected=line.qty_inspected,
                    qty_accepted=line.qty_accepted,
                    qty_rejected=line.qty_rejected,
                    qty_rework=line.qty_rework,
                    remaining_hold=remaining,
                    disposition=disposition,
                )
                product_id = product_by_grn_line.get(line.goods_receipt_line_id)
                if product_id is None:
                    raise ValidationError("Inspection line is missing a product")
                locked = await self.stock.lock_balance(
                    tenant_id,
                    warehouse_id=receipt.warehouse_id,
                    product_id=product_id,
                    document_date=row.inspection_date,
                    can_override_soft_lock=self._can_override,
                )
                if line.qty_accepted > _ZERO:
                    await self.stock.apply_quality_hold_locked(
                        tenant_id,
                        locked,
                        qty=-line.qty_accepted,
                        movement_type=StockMovementType.QC_RELEASE,
                        source_type=SOURCE_QUALITY_INSPECTION,
                        source_id=row.id,
                        source_line_id=line.id,
                        document_date=row.inspection_date,
                        notes=line.notes or row.notes,
                        occurred_at=occurred_at,
                        unit_id=unit_by_grn_line.get(line.goods_receipt_line_id),
                    )
                if line.qty_rejected > _ZERO and disposition is not None:
                    movement_type = (
                        StockMovementType.DAMAGE
                        if disposition == QcDisposition.SCRAP
                        else StockMovementType.RETURN_OUT
                    )
                    result = await self.stock.apply_locked(
                        tenant_id,
                        locked,
                        qty=-line.qty_rejected,
                        movement_type=movement_type,
                        source_type=SOURCE_QUALITY_INSPECTION,
                        source_id=row.id,
                        source_line_id=line.id,
                        document_date=row.inspection_date,
                        notes=line.notes or disposition.value,
                        occurred_at=occurred_at,
                        unit_id=unit_by_grn_line.get(line.goods_receipt_line_id),
                        quality_hold_delta=-line.qty_rejected,
                    )
                    if (
                        disposition == QcDisposition.SCRAP
                        and result.movement.value is not None
                    ):
                        scrap_value += result.movement.value
                rework_released = _ZERO
                if line.qty_rework > _ZERO and disposition == QcDisposition.REWORK_RELEASE:
                    await self.stock.apply_quality_hold_locked(
                        tenant_id,
                        locked,
                        qty=-line.qty_rework,
                        movement_type=StockMovementType.QC_RELEASE,
                        source_type=SOURCE_QUALITY_INSPECTION,
                        source_id=row.id,
                        source_line_id=line.id,
                        document_date=row.inspection_date,
                        notes=line.notes or row.notes,
                        occurred_at=occurred_at,
                        unit_id=unit_by_grn_line.get(line.goods_receipt_line_id),
                    )
                    rework_released = line.qty_rework
                deltas.append(
                    (
                        line.goods_receipt_line_id,
                        line.qty_accepted,
                        line.qty_rejected,
                        rework_released,
                    )
                )
            await self.receipts.apply_inspection_quantities(tenant_id, row.goods_receipt_id, deltas)
            row.status = target.value
            row.approved_at = occurred_at
            row.approved_by = actor_user_id
            row.inspector_user_id = row.inspector_user_id or actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.inventory_ledger.post_quality_scrap(
                tenant_id,
                source_id=row.id,
                entry_date=row.inspection_date,
                amount=scrap_value,
                actor_id=actor_user_id,
                document_number=row.document_number,
            )
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, inspection_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.APPROVE,
                module=INVENTORY_MODULE,
                entity_type="quality_inspection",
                entity_id=inspection_id,
                old_values=old_values,
                new_values=await self._snapshot(loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="inventory.quality_inspection.approved",
                aggregate_type="quality_inspection",
                aggregate_id=inspection_id,
                payload={"quality_inspection_id": str(inspection_id)},
                dedupe_key=f"quality-inspection-approved:{inspection_id}",
            )
            response = self._to_response(loaded)
            await idempotency.store(tenant_id, idempotency_key, response.model_dump(mode="json"))
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        inspection_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> QualityInspectionResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, inspection_id, for_update=True)
            self._assert_version(row, expected_version)
            old_values = await self._snapshot(row)
            target = next_status(QualityInspectionStatus(row.status), "cancel")
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
                entity_type="quality_inspection",
                entity_id=inspection_id,
                old_values=old_values,
                new_values=await self._snapshot(row),
            )
            return self._to_response(row)

    async def has_approved(self, tenant_id: UUID, goods_receipt_id: UUID) -> bool:
        return await self.repo.has_approved_for_goods_receipt(tenant_id, goods_receipt_id)

    async def cancel_drafts_for_goods_receipt(
        self, tenant_id: UUID, goods_receipt_id: UUID, *, actor_user_id: UUID
    ) -> None:
        rows = await self.repo.list_for_goods_receipt(tenant_id, goods_receipt_id)
        now = utcnow()
        for row in rows:
            if QualityInspectionStatus(row.status) != QualityInspectionStatus.DRAFT:
                continue
            row.status = QualityInspectionStatus.CANCELLED.value
            row.cancelled_at = now
            row.cancelled_by = actor_user_id
            row.cancel_reason = "Cancelled with goods receipt"
            row.version += 1
            row.updated_by = actor_user_id
        await self.session.flush()

    async def _create_unlocked(
        self, tenant_id: UUID, payload: QualityInspectionCreate, *, actor_user_id: UUID
    ) -> QualityInspectionResponse:
        header, line_rows = await self._build_draft(tenant_id, payload)
        policy = await self._ensure_policy(tenant_id)
        policy.assert_open(header["inspection_date"], can_override=self._can_override)
        number = await self.sequences.allocate(
            tenant_id,
            document_type=DocumentType.QUALITY_INSPECTION,
            series=_SERIES,
            fiscal_year=await year_for(self.session, tenant_id, header["inspection_date"]),
            prefix=_SERIES,
        )
        row = await self.repo.create(
            tenant_id,
            {
                **header,
                "document_number": number,
                "status": QualityInspectionStatus.DRAFT.value,
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
            entity_type="quality_inspection",
            entity_id=row.id,
            new_values=await self._snapshot(loaded),
        )
        return self._to_response(loaded)

    async def _build_draft(
        self, tenant_id: UUID, payload: QualityInspectionCreate
    ) -> tuple[dict[str, Any], builtins.list[dict[str, Any]]]:
        receipt = await self.receipts.get(tenant_id, payload.goods_receipt_id)
        if receipt.status != StockDocumentStatus.POSTED:
            raise ValidationError(
                "Quality inspections can only be created for a posted goods receipt"
            )
        hold_by_line = {line.id: line.qty_on_hold for line in receipt.lines}
        inspection_date = payload.inspection_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        if not payload.lines:
            raise ValidationError("At least one line is required")
        seen: set[UUID] = set()
        built: builtins.list[dict[str, Any]] = []
        for index, line in enumerate(payload.lines, start=1):
            if line.goods_receipt_line_id in seen:
                raise ValidationError("Duplicate goods receipt line on the inspection")
            seen.add(line.goods_receipt_line_id)
            if line.goods_receipt_line_id not in hold_by_line:
                raise ValidationError("Goods receipt line does not belong to this receipt")
            remaining = hold_by_line[line.goods_receipt_line_id]
            assert_line_quantities(
                qty_inspected=quantize_quantity(line.qty_inspected),
                qty_accepted=quantize_quantity(line.qty_accepted),
                qty_rejected=quantize_quantity(line.qty_rejected),
                qty_rework=quantize_quantity(line.qty_rework),
                remaining_hold=remaining,
                disposition=line.disposition,
            )
            built.append(
                {
                    "line_number": index,
                    "goods_receipt_line_id": line.goods_receipt_line_id,
                    "qty_inspected": quantize_quantity(line.qty_inspected),
                    "qty_accepted": quantize_quantity(line.qty_accepted),
                    "qty_rejected": quantize_quantity(line.qty_rejected),
                    "qty_rework": quantize_quantity(line.qty_rework),
                    "disposition": line.disposition.value if line.disposition else None,
                    "notes": line.notes,
                }
            )
        header: dict[str, Any] = {
            "goods_receipt_id": payload.goods_receipt_id,
            "inspection_date": inspection_date,
            "inspector_user_id": payload.inspector_user_id,
            "notes": payload.notes,
        }
        return header, built

    def _update_to_create(
        self, existing: QualityInspection, payload: QualityInspectionUpdate
    ) -> QualityInspectionCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                QualityInspectionLineInput(
                    goods_receipt_line_id=line.goods_receipt_line_id,
                    qty_inspected=line.qty_inspected,
                    qty_accepted=line.qty_accepted,
                    qty_rejected=line.qty_rejected,
                    qty_rework=line.qty_rework,
                    disposition=QcDisposition(line.disposition) if line.disposition else None,
                    notes=line.notes,
                )
                for line in existing.lines
            ]
        return QualityInspectionCreate(
            goods_receipt_id=existing.goods_receipt_id,
            inspection_date=values.get("inspection_date", existing.inspection_date),
            inspector_user_id=values.get("inspector_user_id", existing.inspector_user_id),
            notes=values.get("notes", existing.notes),
            lines=lines,
        )

    def _available_actions(
        self, status: QualityInspectionStatus, *, period_locked: bool
    ) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            if action == "approve" and period_locked:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == QualityInspectionStatus.DRAFT and has_permission(
            self.actor_permissions, QUALITY_INSPECTION_UPDATE
        ):
            actions.append("delete")
        return actions

    def _to_response(self, row: QualityInspection) -> QualityInspectionResponse:
        status = QualityInspectionStatus(row.status)
        date_locked = self._date_in_locked_period(row.inspection_date)
        post_blocked = self._post_blocked(row.inspection_date)
        return QualityInspectionResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            goods_receipt_id=row.goods_receipt_id,
            inspection_date=row.inspection_date,
            inspector_user_id=row.inspector_user_id,
            notes=row.notes,
            approved_at=row.approved_at,
            approved_by=row.approved_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            available_actions=self._available_actions(status, period_locked=post_blocked),
            period_locked=date_locked,
            lines=[
                QualityInspectionLineResponse(
                    id=line.id,
                    line_number=line.line_number,
                    goods_receipt_line_id=line.goods_receipt_line_id,
                    qty_inspected=line.qty_inspected,
                    qty_accepted=line.qty_accepted,
                    qty_rejected=line.qty_rejected,
                    qty_rework=line.qty_rework,
                    disposition=QcDisposition(line.disposition) if line.disposition else None,
                    notes=line.notes,
                )
                for line in row.lines
            ],
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

    def _assert_version(self, row: QualityInspection, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, row: QualityInspection) -> dict[str, object]:
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "inspection_date": row.inspection_date,
            "line_count": len(row.lines),
        }

    async def _require(
        self, tenant_id: UUID, inspection_id: UUID, *, for_update: bool = False
    ) -> QualityInspection:
        row = await self.repo.get(tenant_id, inspection_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Quality inspection not found")
        return row
