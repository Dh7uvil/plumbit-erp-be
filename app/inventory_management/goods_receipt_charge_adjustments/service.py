"""GRN charge adjustment compose, draft saves, and posting."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    GRN_CHARGE_ADJUSTMENT_DELETE,
    GRN_CHARGE_ADJUSTMENT_POST,
    GRN_CHARGE_ADJUSTMENT_UPDATE,
    INVENTORY_MODULE,
    PERIOD_OVERRIDE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.period_lock import PeriodLockPolicy
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.charge_allocation import ChargeLineContext, allocate_charge
from app.common.utils.currency import quantize_money
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.enums import (
    AuditAction,
    ChargeAllocationMethod,
    DocumentType,
    ItemType,
    StockDocumentStatus,
)
from app.core.exceptions import (
    DocumentStaleError,
    InvalidStatusTransitionError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.charge_types.service import ChargeTypeService
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.inventory_posting import InventoryLedgerService
from app.erp.accounting.ledger.schemas import JournalEntryResponse
from app.erp.accounting.service import DocumentSequenceService
from app.inventory_management.common.journal_lookup import journal_for_source
from app.inventory_management.costing.service import CostingService
from app.inventory_management.goods_receipt_charge_adjustments.models import (
    GoodsReceiptChargeAdjustment,
)
from app.inventory_management.goods_receipt_charge_adjustments.repository import (
    GoodsReceiptChargeAdjustmentRepository,
)
from app.inventory_management.goods_receipt_charge_adjustments.schemas import (
    GoodsReceiptChargeAdjustmentCreate,
    GoodsReceiptChargeAdjustmentLineInput,
    GoodsReceiptChargeAdjustmentLineResponse,
    GoodsReceiptChargeAdjustmentResponse,
    GoodsReceiptChargeAdjustmentUpdate,
)
from app.inventory_management.goods_receipt_charge_adjustments.workflow import (
    assert_editable,
    next_status,
    transition_actions,
)
from app.inventory_management.goods_receipts.models import GoodsReceipt, GoodsReceiptLine
from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository
from app.inventory_management.goods_receipts.service import GoodsReceiptService
from app.inventory_management.products.service import ProductService
from app.inventory_management.stock.service import SOURCE_GOODS_RECEIPT

_ZERO = Decimal("0")
_SERIES = "GCA"
_SOURCE = "goods_receipt_charge_adjustment"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": GRN_CHARGE_ADJUSTMENT_POST,
    "cancel": GRN_CHARGE_ADJUSTMENT_UPDATE,
}


class GoodsReceiptChargeAdjustmentService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = GoodsReceiptChargeAdjustmentRepository(session)
        self.goods_receipts = GoodsReceiptRepository(session)
        self.charge_types = ChargeTypeService(session)
        self.costing = CostingService(session)
        self.products = ProductService(session)
        self.org = OrganizationService(session)
        self.sequences = DocumentSequenceService(session)
        self.idempotency = IdempotencyService(session)
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
        branch_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[builtins.list[GoodsReceiptChargeAdjustmentResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if goods_receipt_id is not None:
            filters["goods_receipt_id"] = goods_receipt_id
        if branch_id is not None:
            filters["branch_id"] = branch_id
        extra: list[Any] = []
        if document_date_from is not None:
            extra.append(GoodsReceiptChargeAdjustment.document_date >= document_date_from)
        if document_date_to is not None:
            extra.append(GoodsReceiptChargeAdjustment.document_date <= document_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [self._to_response(row) for row in rows], total

    async def get(
        self, tenant_id: UUID, adjustment_id: UUID
    ) -> GoodsReceiptChargeAdjustmentResponse:
        row = await self._require(tenant_id, adjustment_id)
        await self._ensure_policy(tenant_id)
        return self._to_response(row)

    async def journal(self, tenant_id: UUID, adjustment_id: UUID) -> JournalEntryResponse:
        await self._require(tenant_id, adjustment_id)
        return await journal_for_source(
            self.session,
            tenant_id,
            source_type=_SOURCE,
            source_id=adjustment_id,
            label="GRN charge adjustment",
            actor_permissions=self.actor_permissions,
        )

    async def create(
        self,
        tenant_id: UUID,
        payload: GoodsReceiptChargeAdjustmentCreate,
        *,
        actor_user_id: UUID,
    ) -> GoodsReceiptChargeAdjustmentResponse:
        async with transaction(self.session):
            header, line_rows = await self._build_draft(tenant_id, payload)
            document_date = cast(date, header["document_date"])
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(document_date, can_override=self._can_override)
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.GRN_CHARGE_ADJUSTMENT,
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
                entity_type="goods_receipt_charge_adjustment",
                entity_id=row.id,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            return self._to_response(loaded)

    async def update(
        self,
        tenant_id: UUID,
        adjustment_id: UUID,
        payload: GoodsReceiptChargeAdjustmentUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> GoodsReceiptChargeAdjustmentResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, adjustment_id, for_update=True)
            assert_editable(StockDocumentStatus(existing.status))
            self._assert_version(existing, expected_version)
            old_values = await self._snapshot(tenant_id, existing)
            create_payload = await self._update_to_create(tenant_id, existing, payload)
            header, line_rows = await self._build_draft(tenant_id, create_payload)
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(cast(date, header["document_date"]), can_override=self._can_override)
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
                entity_type="goods_receipt_charge_adjustment",
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
    ) -> GoodsReceiptChargeAdjustmentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, adjustment_id, for_update=True)
            if StockDocumentStatus(row.status) != StockDocumentStatus.DRAFT:
                raise InvalidStatusTransitionError(
                    "Only draft GRN charge adjustments can be deleted"
                )
            self._assert_version(row, expected_version)
            await self._ensure_policy(tenant_id)
            response = self._to_response(row)
            old_values = await self._snapshot(tenant_id, row)
            await self.repo.soft_delete(tenant_id, adjustment_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="goods_receipt_charge_adjustment",
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
    ) -> GoodsReceiptChargeAdjustmentResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return GoodsReceiptChargeAdjustmentResponse.model_validate(replay)
            row = await self._require(tenant_id, adjustment_id, for_update=True)
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
            grn = await self._require_posted_grn(tenant_id, row.goods_receipt_id, for_update=True)
            old_values = await self._snapshot(tenant_id, row)
            allocated_by_line, charge_credits = await self._compute_adjustment_allocations(
                tenant_id, grn, row
            )
            stockable_lines = await self._stockable_lines(tenant_id, grn)
            charge_per_unit_by_line = GoodsReceiptService._charge_per_unit_by_line(
                stockable_lines, allocated_by_line
            )
            for line in stockable_lines:
                delta = allocated_by_line.get(line.id, _ZERO)
                line.allocated_charge_amount = quantize_money(line.allocated_charge_amount + delta)
                charge_delta = charge_per_unit_by_line.get(line.id, _ZERO)
                layers = await self.costing.layers_for_source(
                    tenant_id,
                    SOURCE_GOODS_RECEIPT,
                    grn.id,
                    source_line_id=line.id,
                )
                for layer in layers:
                    if layer.qty_remaining > _ZERO:
                        await self.costing.revalue(
                            tenant_id,
                            layer.id,
                            quantize_money(layer.landed_unit_cost + charge_delta),
                        )
            row.status = target.value
            row.is_posted = True
            row.posted_at = utcnow()
            row.posted_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.inventory_ledger.post_grn_charge_adjustment(
                tenant_id,
                source_id=row.id,
                entry_date=row.document_date,
                charge_credits=charge_credits,
                actor_id=actor_user_id,
                branch_id=row.branch_id or grn.branch_id,
                document_number=row.document_number,
            )
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, adjustment_id)
            await self._ensure_policy(tenant_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=INVENTORY_MODULE,
                entity_type="goods_receipt_charge_adjustment",
                entity_id=adjustment_id,
                old_values=old_values,
                new_values=await self._snapshot(tenant_id, loaded),
            )
            response = self._to_response(loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def _build_draft(
        self,
        tenant_id: UUID,
        payload: GoodsReceiptChargeAdjustmentCreate,
    ) -> tuple[dict[str, object], builtins.list[dict[str, object]]]:
        grn = await self._require_posted_grn(tenant_id, payload.goods_receipt_id)
        document_date = payload.document_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        charge_by_id = {charge.id: charge for charge in grn.charges}
        if len({line.goods_receipt_charge_id for line in payload.lines}) != len(payload.lines):
            raise ValidationError("Duplicate goods receipt charge lines are not allowed")
        built_lines: builtins.list[dict[str, object]] = []
        for index, line in enumerate(payload.lines, start=1):
            grn_charge = charge_by_id.get(line.goods_receipt_charge_id)
            if grn_charge is None:
                raise ValidationError("Goods receipt charge not found on the selected GRN")
            base_delta = quantize_money(line.adjustment_amount * grn.exchange_rate)
            built_lines.append(
                {
                    "line_number": index,
                    "goods_receipt_charge_id": line.goods_receipt_charge_id,
                    "adjustment_amount": quantize_money(line.adjustment_amount),
                    "base_adjustment_amount": base_delta,
                    "notes": line.notes,
                }
            )
        header: dict[str, object] = {
            "goods_receipt_id": payload.goods_receipt_id,
            "document_date": document_date,
            "branch_id": payload.branch_id or grn.branch_id,
            "notes": payload.notes,
        }
        return header, built_lines

    async def _compute_adjustment_allocations(
        self,
        tenant_id: UUID,
        grn: GoodsReceipt,
        row: GoodsReceiptChargeAdjustment,
    ) -> tuple[dict[UUID, Decimal], dict[UUID, Decimal]]:
        stockable_lines = await self._stockable_lines(tenant_id, grn)
        if not stockable_lines:
            raise ValidationError("GRN charge adjustments require at least one stockable line")
        charge_by_id = {charge.id: charge for charge in grn.charges}
        contexts = [
            ChargeLineContext(
                quantity=line.quantity,
                rate=line.rate,
                net_weight=line.net_weight,
                gross_weight=line.gross_weight,
                volume=line.volume,
            )
            for line in stockable_lines
        ]
        allocated: dict[UUID, Decimal] = {line.id: _ZERO for line in stockable_lines}
        charge_credits: dict[UUID, Decimal] = {}
        for adj_line in row.lines:
            grn_charge = charge_by_id.get(adj_line.goods_receipt_charge_id)
            if grn_charge is None:
                raise ValidationError("Goods receipt charge not found on the selected GRN")
            charge_type = await self.charge_types.require_active(tenant_id, grn_charge.charge_type_id)
            method = ChargeAllocationMethod(
                grn_charge.allocation_basis
                or charge_type.allocation_basis
                or ChargeAllocationMethod.VALUE
            )
            shares = allocate_charge(
                adj_line.base_adjustment_amount,
                contexts,
                method,
                exchange_rate=grn.exchange_rate,
            )
            for line, share in zip(stockable_lines, shares, strict=True):
                allocated[line.id] = quantize_money(allocated[line.id] + share)
            account_id = charge_type.default_account_id
            charge_credits[account_id] = quantize_money(
                charge_credits.get(account_id, _ZERO) + adj_line.base_adjustment_amount
            )
        return allocated, charge_credits

    async def _stockable_lines(
        self, tenant_id: UUID, grn: GoodsReceipt
    ) -> builtins.list[GoodsReceiptLine]:
        stockable: builtins.list[GoodsReceiptLine] = []
        for line in grn.lines:
            if line.product_id is None or line.quantity <= _ZERO:
                continue
            product = await self.products.require_active(tenant_id, line.product_id)
            if product.item_type == ItemType.SERVICE or not product.track_inventory:
                continue
            stockable.append(line)
        return stockable

    async def _require_posted_grn(
        self, tenant_id: UUID, goods_receipt_id: UUID, *, for_update: bool = False
    ) -> GoodsReceipt:
        row = await self.goods_receipts.get(tenant_id, goods_receipt_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Goods receipt not found")
        if StockDocumentStatus(row.status) != StockDocumentStatus.POSTED:
            raise ValidationError("GRN charge adjustments require a posted goods receipt")
        return row

    async def _update_to_create(
        self,
        tenant_id: UUID,
        existing: GoodsReceiptChargeAdjustment,
        payload: GoodsReceiptChargeAdjustmentUpdate,
    ) -> GoodsReceiptChargeAdjustmentCreate:
        return GoodsReceiptChargeAdjustmentCreate(
            goods_receipt_id=existing.goods_receipt_id,
            document_date=payload.document_date or existing.document_date,
            branch_id=payload.branch_id if payload.branch_id is not None else existing.branch_id,
            notes=payload.notes if payload.notes is not None else existing.notes,
            lines=payload.lines
            or [
                GoodsReceiptChargeAdjustmentLineInput(
                    goods_receipt_charge_id=line.goods_receipt_charge_id,
                    adjustment_amount=line.adjustment_amount,
                    notes=line.notes,
                )
                for line in existing.lines
            ],
        )

    async def _require(
        self, tenant_id: UUID, adjustment_id: UUID, *, for_update: bool = False
    ) -> GoodsReceiptChargeAdjustment:
        row = await self.repo.get(tenant_id, adjustment_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("GRN charge adjustment not found")
        return row

    async def _ensure_policy(self, tenant_id: UUID) -> PeriodLockPolicy:
        if self._period_policy is None:
            self._period_policy = await PeriodLockPolicy.load(self.session, tenant_id)
        return self._period_policy

    def _assert_version(self, row: GoodsReceiptChargeAdjustment, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError()

    def _available_actions(self, row: GoodsReceiptChargeAdjustment, *, period_locked: bool) -> list[str]:
        actions = transition_actions(StockDocumentStatus(row.status))
        if period_locked:
            return []
        return [
            action
            for action in actions
            if has_permission(self.actor_permissions, _ACTION_PERMISSIONS.get(action, ""))
        ]

    def _to_response(self, row: GoodsReceiptChargeAdjustment) -> GoodsReceiptChargeAdjustmentResponse:
        status = StockDocumentStatus(row.status)
        period_locked = False
        if self._period_policy is not None:
            period_locked = self._period_policy.is_locked(row.document_date)
        return GoodsReceiptChargeAdjustmentResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=row.is_posted,
            document_date=row.document_date,
            goods_receipt_id=row.goods_receipt_id,
            branch_id=row.branch_id,
            notes=row.notes,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            available_actions=self._available_actions(row, period_locked=period_locked),
            period_locked=period_locked,
            lines=[
                GoodsReceiptChargeAdjustmentLineResponse.model_validate(line)
                for line in row.lines
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
            created_by=row.created_by,
            updated_by=row.updated_by,
        )

    async def _snapshot(
        self, tenant_id: UUID, row: GoodsReceiptChargeAdjustment
    ) -> dict[str, object]:
        loaded = await self._require(tenant_id, row.id)
        return cast(dict[str, object], self._to_response(loaded).model_dump(mode="json"))
