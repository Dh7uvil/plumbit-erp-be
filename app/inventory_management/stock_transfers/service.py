"""Stock transfer compose, draft saves, and posting."""

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
    STOCK_TRANSFER_CREATE,
    STOCK_TRANSFER_DELETE,
    STOCK_TRANSFER_POST,
    STOCK_TRANSFER_UPDATE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.enums import AuditAction, DocumentType, StockDocumentStatus, StockMovementType
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
from app.inventory_management.stock.service import (
    SOURCE_STOCK_TRANSFER,
    LockedBalance,
    StockService,
)
from app.inventory_management.stock_transfers.models import StockTransfer
from app.inventory_management.stock_transfers.repository import StockTransferRepository
from app.inventory_management.stock_transfers.schemas import (
    StockTransferCreate,
    StockTransferLineInput,
    StockTransferLineResponse,
    StockTransferResponse,
    StockTransferUpdate,
)
from app.inventory_management.stock_transfers.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)
from app.inventory_management.warehouses.service import WarehouseService

_ZERO = Decimal("0")
_SERIES = "STR"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": STOCK_TRANSFER_POST,
    "cancel": STOCK_TRANSFER_UPDATE,
}


class StockTransferService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = StockTransferRepository(session)
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
        from_warehouse_id: UUID | None = None,
        to_warehouse_id: UUID | None = None,
        branch_id: UUID | None = None,
        product_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[builtins.list[StockTransferResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if from_warehouse_id is not None:
            filters["from_warehouse_id"] = from_warehouse_id
        if to_warehouse_id is not None:
            filters["to_warehouse_id"] = to_warehouse_id
        if branch_id is not None:
            filters["branch_id"] = branch_id
        extra: list[Any] = []
        if product_id is not None:
            extra.append(self.repo.has_product_clause(product_id))
        if document_date_from is not None:
            extra.append(StockTransfer.document_date >= document_date_from)
        if document_date_to is not None:
            extra.append(StockTransfer.document_date <= document_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, transfer_id: UUID) -> StockTransferResponse:
        return self._to_response(await self._require(tenant_id, transfer_id))

    async def create(
        self, tenant_id: UUID, payload: StockTransferCreate, *, actor_user_id: UUID
    ) -> StockTransferResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            document_date = cast(date, header["document_date"])
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.STOCK_TRANSFER,
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
                entity_type="stock_transfer",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def update(
        self,
        tenant_id: UUID,
        transfer_id: UUID,
        payload: StockTransferUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> StockTransferResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, transfer_id, for_update=True)
            assert_editable(StockDocumentStatus(existing.status))
            self._assert_version(existing, expected_version)
            old_values = await self._snapshot(tenant_id, existing)
            create_payload = self._update_to_create(existing, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            await self.repo.update(tenant_id, transfer_id, header)
            await self.repo.replace_lines(tenant_id, transfer_id, line_rows)
            loaded = await self._require(tenant_id, transfer_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="stock_transfer",
                entity_id=transfer_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        transfer_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> StockTransferResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, transfer_id, for_update=True)
            if StockDocumentStatus(row.status) != StockDocumentStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft stock transfers can be deleted")
            self._assert_version(row, expected_version)
            response = self._to_response(row)
            old_values = await self._snapshot(tenant_id, row)
            await self.repo.soft_delete(tenant_id, transfer_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="stock_transfer",
                entity_id=transfer_id,
                old_values=old_values,
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        transfer_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> StockTransferResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return StockTransferResponse.model_validate(replay)
            row = await self._require(tenant_id, transfer_id, for_update=True)
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
            first_wh, second_wh = sorted(
                (row.from_warehouse_id, row.to_warehouse_id), key=lambda value: str(value)
            )
            for line in row.lines:
                locked_by_warehouse: dict[UUID, LockedBalance] = {}
                for warehouse_id in (first_wh, second_wh):
                    locked_by_warehouse[warehouse_id] = await self.stock.lock_balance(
                        tenant_id,
                        warehouse_id=warehouse_id,
                        product_id=line.product_id,
                        document_date=row.document_date,
                    )
                source = locked_by_warehouse[row.from_warehouse_id]
                dest = locked_by_warehouse[row.to_warehouse_id]
                line.qty_source_before = source.row.qty_on_hand
                line.qty_dest_before = dest.row.qty_on_hand
                line.qty_transferred = line.qty
                await self.stock.apply_locked(
                    tenant_id,
                    source,
                    qty=-line.qty,
                    movement_type=StockMovementType.TRANSFER_OUT,
                    source_type=SOURCE_STOCK_TRANSFER,
                    source_id=row.id,
                    source_line_id=line.id,
                    document_date=row.document_date,
                    notes=line.notes or row.notes or row.reason,
                    occurred_at=occurred_at,
                    unit_id=line.unit_id,
                )
                await self.stock.apply_locked(
                    tenant_id,
                    dest,
                    qty=line.qty,
                    movement_type=StockMovementType.TRANSFER_IN,
                    source_type=SOURCE_STOCK_TRANSFER,
                    source_id=row.id,
                    source_line_id=line.id,
                    document_date=row.document_date,
                    notes=line.notes or row.notes or row.reason,
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
            loaded = await self._require(tenant_id, transfer_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=INVENTORY_MODULE,
                entity_type="stock_transfer",
                entity_id=transfer_id,
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
        transfer_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
    ) -> StockTransferResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, transfer_id, for_update=True)
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
                entity_type="stock_transfer",
                entity_id=transfer_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, row),
            )
            return self._to_response(row)

    async def clone(
        self, tenant_id: UUID, transfer_id: UUID, *, actor_user_id: UUID
    ) -> StockTransferResponse:
        source = await self._require(tenant_id, transfer_id)
        payload = StockTransferCreate(
            from_warehouse_id=source.from_warehouse_id,
            to_warehouse_id=source.to_warehouse_id,
            document_date=None,
            branch_id=source.branch_id,
            reason=source.reason,
            reference=source.reference,
            notes=source.notes,
            lines=[
                StockTransferLineInput(
                    product_id=line.product_id,
                    unit_id=line.unit_id,
                    qty=line.qty,
                    notes=line.notes,
                )
                for line in source.lines
            ],
        )
        return await self.create(tenant_id, payload, actor_user_id=actor_user_id)

    async def _build_draft(
        self, tenant_id: UUID, payload: StockTransferCreate
    ) -> tuple[dict[str, Any], builtins.list[dict[str, Any]]]:
        if payload.from_warehouse_id == payload.to_warehouse_id:
            raise ValidationError("Source and destination warehouses must differ")
        await self.warehouses.require_id(tenant_id, payload.from_warehouse_id)
        await self.warehouses.require_id(tenant_id, payload.to_warehouse_id)
        if payload.branch_id is not None:
            await self.org.require_branch(tenant_id, payload.branch_id)
        document_date = payload.document_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        line_rows = await self._build_lines(tenant_id, payload.lines)
        header: dict[str, Any] = {
            "document_date": document_date,
            "from_warehouse_id": payload.from_warehouse_id,
            "to_warehouse_id": payload.to_warehouse_id,
            "branch_id": payload.branch_id,
            "reason": payload.reason,
            "reference": payload.reference,
            "notes": payload.notes,
        }
        return header, line_rows

    async def _build_lines(
        self, tenant_id: UUID, lines: Sequence[StockTransferLineInput]
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
            built.append(
                {
                    "line_number": index,
                    "product_id": line.product_id,
                    "unit_id": unit_id,
                    "qty": line.qty,
                    "qty_transferred": _ZERO,
                    "qty_source_before": None,
                    "qty_dest_before": None,
                    "notes": line.notes,
                }
            )
        return built

    def _update_to_create(
        self, existing: StockTransfer, payload: StockTransferUpdate
    ) -> StockTransferCreate:
        values = payload.model_dump(exclude_unset=True)
        if payload.lines is not None:
            lines = payload.lines
        else:
            lines = [
                StockTransferLineInput(
                    product_id=line.product_id,
                    unit_id=line.unit_id,
                    qty=line.qty,
                    notes=line.notes,
                )
                for line in existing.lines
            ]
        return StockTransferCreate(
            from_warehouse_id=values.get("from_warehouse_id", existing.from_warehouse_id),
            to_warehouse_id=values.get("to_warehouse_id", existing.to_warehouse_id),
            document_date=values.get("document_date", existing.document_date),
            branch_id=values.get("branch_id", existing.branch_id),
            reason=values.get("reason", existing.reason),
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
        if has_permission(self.actor_permissions, STOCK_TRANSFER_CREATE):
            actions.append("clone")
        if status == StockDocumentStatus.DRAFT and has_permission(
            self.actor_permissions, STOCK_TRANSFER_DELETE
        ):
            actions.append("delete")
        return actions

    def _to_response(self, row: StockTransfer) -> StockTransferResponse:
        status = StockDocumentStatus(row.status)
        return StockTransferResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=status == StockDocumentStatus.POSTED,
            document_date=row.document_date,
            from_warehouse_id=row.from_warehouse_id,
            to_warehouse_id=row.to_warehouse_id,
            branch_id=row.branch_id,
            reason=row.reason,
            reference=row.reference,
            notes=row.notes,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            available_actions=self._available_actions(status),
            lines=[StockTransferLineResponse.model_validate(line) for line in row.lines],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _assert_version(self, row: StockTransfer, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, tenant_id: UUID, row: StockTransfer) -> dict[str, object]:
        source = await self.warehouses.get(tenant_id, row.from_warehouse_id)
        dest = await self.warehouses.get(tenant_id, row.to_warehouse_id)
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "document_date": row.document_date,
            "from_warehouse": source.code,
            "to_warehouse": dest.code,
            "reference": row.reference,
            "line_count": len(row.lines),
        }

    async def _require(
        self, tenant_id: UUID, transfer_id: UUID, *, for_update: bool = False
    ) -> StockTransfer:
        row = await self.repo.get(tenant_id, transfer_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Stock transfer not found")
        return row
