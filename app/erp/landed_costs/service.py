"""Allocate posted expense bills onto posted GRN layers and post inventory vs variance."""

from __future__ import annotations

import builtins
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    PURCHASE_MODULE,
    LANDED_COST_CANCEL,
    LANDED_COST_POST,
    LANDED_COST_UPDATE,
    PERIOD_OVERRIDE,
)
from app.auth.org_service import OrganizationService
from app.common.idempotency.service import IdempotencyService
from app.common.outbox.service import OutboxService
from app.common.period_lock import PeriodLockPolicy
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money, quantize_quantity
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.enums import (
    AccountSystemRole,
    AuditAction,
    DocumentType,
    ExpenseCategory,
    InvoiceDocumentStatus,
    LandedCostAllocationMethod,
    PurchaseInvoiceLineType,
    StockDocumentStatus,
)
from app.core.exceptions import (
    DocumentStaleError,
    LandedCostCannotCancelError,
    LandedCostLineOverAllocatedError,
    LandedCostWeightRequiredError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.permissions import has_permission
from app.db.session import transaction
from app.erp.accounting.accounts.service import AccountResolver
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.ledger.inventory_posting import InventoryLedgerService
from app.erp.accounting.ledger.schemas import JournalLineInput
from app.erp.accounting.ledger.service import JournalEntryService
from app.erp.accounting.service import DocumentSequenceService
from app.erp.landed_costs.models import LandedCost
from app.erp.landed_costs.repository import LandedCostRepository
from app.erp.landed_costs.schemas import (
    LandedCostAllocationInput,
    LandedCostAllocationResponse,
    LandedCostChargeInput,
    LandedCostChargeResponse,
    LandedCostCreate,
    LandedCostCreateFromBills,
    LandedCostEligibleLine,
    LandedCostEligibleResponse,
    LandedCostResponse,
    LandedCostUpdate,
)
from app.erp.landed_costs.workflow import assert_editable, next_status, transition_actions
from app.erp.purchase_invoices.models import PurchaseInvoiceLine
from app.inventory_management.costing.service import CostingService
from app.inventory_management.goods_receipts.models import GoodsReceiptLine
from app.inventory_management.stock.service import SOURCE_GOODS_RECEIPT

_ZERO = Decimal("0")
_SERIES = "LC"
_ACTION_PERMISSIONS: dict[str, str] = {
    "post": LANDED_COST_POST,
    "cancel": LANDED_COST_CANCEL,
}


class LandedCostService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = LandedCostRepository(session)
        self.costing = CostingService(session)
        self.inventory_ledger = InventoryLedgerService(session, actor_permissions=actor_permissions)
        self.journals = JournalEntryService(session, actor_permissions=actor_permissions)
        self.resolver = AccountResolver(session)
        self.org = OrganizationService(session)
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
        shipment_id: UUID | None = None,
        goods_receipt_id: UUID | None = None,
        purchase_invoice_id: UUID | None = None,
        document_date_from: date | None = None,
        document_date_to: date | None = None,
    ) -> tuple[list[LandedCostResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if shipment_id is not None:
            filters["shipment_id"] = shipment_id
        extra: list[Any] = []
        if goods_receipt_id is not None:
            extra.append(self.repo.has_goods_receipt_clause(goods_receipt_id))
        if purchase_invoice_id is not None:
            extra.append(self.repo.has_purchase_invoice_clause(purchase_invoice_id))
        if document_date_from is not None:
            extra.append(LandedCost.document_date >= document_date_from)
        if document_date_to is not None:
            extra.append(LandedCost.document_date <= document_date_to)
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
            extra_criteria=extra or None,
        )
        await self._ensure_policy(tenant_id)
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, landed_cost_id: UUID) -> LandedCostResponse:
        row = await self._require(tenant_id, landed_cost_id)
        await self._ensure_policy(tenant_id)
        response = self._to_response(row)
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def create(
        self, tenant_id: UUID, payload: LandedCostCreate, *, actor_user_id: UUID
    ) -> LandedCostResponse:
        async with transaction(self.session):
            return await self._persist_composed(tenant_id, payload, actor_user_id=actor_user_id)

    async def create_from_bills(
        self,
        tenant_id: UUID,
        payload: LandedCostCreateFromBills,
        *,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> LandedCostResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return LandedCostResponse.model_validate(replay)
            receipt_ids = list(payload.goods_receipt_ids)
            if payload.shipment_id is not None and not receipt_ids:
                receipt_ids = await self._grns_for_shipment(tenant_id, payload.shipment_id)
            allocations = await self._allocations_for_receipts(tenant_id, receipt_ids)
            if not allocations:
                raise ValidationError("Select at least one posted goods receipt line to allocate")
            create = LandedCostCreate(
                document_date=payload.document_date,
                allocation_method=payload.allocation_method,
                shipment_id=payload.shipment_id,
                branch_id=payload.branch_id,
                notes=payload.notes,
                charges=[
                    LandedCostChargeInput(purchase_invoice_line_id=line_id)
                    for line_id in payload.purchase_invoice_line_ids
                ],
                allocations=allocations,
            )
            response = await self._persist_composed(tenant_id, create, actor_user_id=actor_user_id)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def update(
        self,
        tenant_id: UUID,
        landed_cost_id: UUID,
        payload: LandedCostUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> LandedCostResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, landed_cost_id, for_update=True)
            assert_editable(StockDocumentStatus(existing.status))
            self._assert_version(existing, expected_version)
            old_values = await self._snapshot(existing)
            create_payload = self._update_to_create(existing, payload)
            header, charges, allocations = await self._build_draft(
                tenant_id, create_payload, exclude_id=landed_cost_id
            )
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(cast(date, header["document_date"]), can_override=self._can_override)
            header["updated_by"] = actor_user_id
            header["version"] = existing.version + 1
            await self.repo.update(tenant_id, landed_cost_id, header)
            await self.repo.replace_children(
                tenant_id, landed_cost_id, charges=charges, allocations=allocations
            )
            loaded = await self._require(tenant_id, landed_cost_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=PURCHASE_MODULE,
                entity_type="landed_cost",
                entity_id=landed_cost_id,
                old_values=old_values,
                new_values=await self._snapshot(loaded),
            )
            return self._to_response(loaded)

    async def delete(
        self,
        tenant_id: UUID,
        landed_cost_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> LandedCostResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, landed_cost_id, for_update=True)
            assert_editable(StockDocumentStatus(row.status))
            self._assert_version(row, expected_version)
            response = self._to_response(row)
            await self.repo.soft_delete(tenant_id, landed_cost_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=PURCHASE_MODULE,
                entity_type="landed_cost",
                entity_id=landed_cost_id,
                old_values=await self._snapshot(row),
            )
            return response

    async def post(
        self,
        tenant_id: UUID,
        landed_cost_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        endpoint: str,
    ) -> LandedCostResponse:
        async with transaction(self.session):
            replay = await self.idempotency.begin(
                tenant_id, idempotency_key, request_hash, endpoint=endpoint
            )
            if replay is not None:
                return LandedCostResponse.model_validate(replay)
            row = await self._require(tenant_id, landed_cost_id, for_update=True)
            if StockDocumentStatus(row.status) == StockDocumentStatus.POSTED:
                response = self._to_response(row)
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
                return response
            self._assert_version(row, expected_version)
            target = next_status(StockDocumentStatus(row.status), "post")
            if not row.charges or not row.allocations:
                raise ValidationError("Charges and allocations are required to post")
            policy = await self._ensure_policy(tenant_id)
            policy.assert_open(row.document_date, can_override=self._can_override)
            old_values = await self._snapshot(row)
            journal_lines, inventory_total = await self._apply_post(tenant_id, row)
            journal = await self.inventory_ledger.post_landed_cost(
                tenant_id,
                source_id=row.id,
                entry_date=row.document_date,
                lines=journal_lines,
                actor_id=actor_user_id,
                branch_id=row.branch_id,
                document_number=row.document_number,
            )
            if journal is not None:
                row.journal_entry_id = journal.id
            row.status = target.value
            row.is_posted = True
            row.posted_at = utcnow()
            row.posted_by = actor_user_id
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            loaded = await self._require(tenant_id, landed_cost_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.POST,
                module=PURCHASE_MODULE,
                entity_type="landed_cost",
                entity_id=landed_cost_id,
                old_values=old_values,
                new_values=await self._snapshot(loaded),
            )
            await self.outbox.enqueue(
                tenant_id,
                event_type="purchase.landed_cost.posted",
                aggregate_type="landed_cost",
                aggregate_id=landed_cost_id,
                payload={
                    "landed_cost_id": str(landed_cost_id),
                    "inventory_amount": str(inventory_total),
                },
                dedupe_key=f"landed-cost-posted:{landed_cost_id}",
            )
            response = self._to_response(loaded)
            response.related_documents = await self._related_documents(tenant_id, loaded)
            await self.idempotency.store(
                tenant_id, idempotency_key, response.model_dump(mode="json")
            )
            return response

    async def cancel(
        self,
        tenant_id: UUID,
        landed_cost_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        reason: str | None = None,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        endpoint: str | None = None,
    ) -> LandedCostResponse:
        async with transaction(self.session):
            if idempotency_key and request_hash and endpoint:
                replay = await self.idempotency.begin(
                    tenant_id, idempotency_key, request_hash, endpoint=endpoint
                )
                if replay is not None:
                    return LandedCostResponse.model_validate(replay)
            row = await self._require(tenant_id, landed_cost_id, for_update=True)
            self._assert_version(row, expected_version)
            current = StockDocumentStatus(row.status)
            old_values = await self._snapshot(row)
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
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CANCEL,
                module=PURCHASE_MODULE,
                entity_type="landed_cost",
                entity_id=landed_cost_id,
                old_values=old_values,
                new_values=await self._snapshot(row),
            )
            if current == StockDocumentStatus.POSTED:
                await self.outbox.enqueue(
                    tenant_id,
                    event_type="purchase.landed_cost.cancelled",
                    aggregate_type="landed_cost",
                    aggregate_id=landed_cost_id,
                    payload={"landed_cost_id": str(landed_cost_id)},
                    dedupe_key=f"landed-cost-cancelled:{landed_cost_id}",
                )
            response = self._to_response(row)
            if idempotency_key and request_hash and endpoint:
                await self.idempotency.store(
                    tenant_id, idempotency_key, response.model_dump(mode="json")
                )
            return response

    async def journal(self, tenant_id: UUID, landed_cost_id: UUID):
        row = await self._require(tenant_id, landed_cost_id)
        if row.journal_entry_id is None:
            raise ResourceNotFoundError("Landed cost has no journal entry")
        return await self.journals.get(tenant_id, row.journal_entry_id)

    async def eligible_for_goods_receipt(
        self, tenant_id: UUID, goods_receipt_id: UUID
    ) -> LandedCostEligibleResponse:
        from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository

        receipt = await GoodsReceiptRepository(self.session).get(tenant_id, goods_receipt_id)
        if receipt is None:
            raise ResourceNotFoundError("Goods receipt not found")
        if StockDocumentStatus(receipt.status) != StockDocumentStatus.POSTED:
            raise ValidationError("Only posted goods receipts can receive landed cost")
        lines: list[LandedCostEligibleLine] = []
        for line in receipt.lines:
            if line.product_id is None:
                continue
            layers = await self.costing.layers_for_source(
                tenant_id, SOURCE_GOODS_RECEIPT, receipt.id, line.id
            )
            qty_remaining = sum((layer.qty_remaining for layer in layers), _ZERO)
            landed = layers[0].landed_unit_cost if layers else _ZERO
            qty = quantize_quantity(line.quantity)
            lines.append(
                LandedCostEligibleLine(
                    goods_receipt_id=receipt.id,
                    goods_receipt_line_id=line.id,
                    goods_receipt_number=receipt.document_number,
                    product_id=line.product_id,
                    description=line.description,
                    quantity=qty,
                    net_weight=line.net_weight,
                    landed_unit_cost=landed,
                    line_value=quantize_money(qty * landed),
                    qty_remaining=quantize_quantity(qty_remaining),
                )
            )
        return LandedCostEligibleResponse(goods_receipt_id=receipt.id, lines=lines)

    async def allocated_by_bill_line(
        self, tenant_id: UUID, line_ids: builtins.list[UUID]
    ) -> dict[UUID, Decimal]:
        return await self.repo.posted_allocated_by_bill_line(tenant_id, line_ids)

    async def _persist_composed(
        self, tenant_id: UUID, payload: LandedCostCreate, *, actor_user_id: UUID
    ) -> LandedCostResponse:
        header, charges, allocations = await self._build_draft(tenant_id, payload)
        document_date = cast(date, header["document_date"])
        policy = await self._ensure_policy(tenant_id)
        policy.assert_open(document_date, can_override=self._can_override)
        number = await self.sequences.allocate(
            tenant_id,
            document_type=DocumentType.LANDED_COST,
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
        await self.repo.replace_children(
            tenant_id, row.id, charges=charges, allocations=allocations
        )
        loaded = await self._require(tenant_id, row.id)
        await self.audit.write(
            tenant_id=tenant_id,
            user_id=actor_user_id,
            action=AuditAction.CREATE,
            module=PURCHASE_MODULE,
            entity_type="landed_cost",
            entity_id=row.id,
            new_values=await self._snapshot(loaded),
        )
        return self._to_response(loaded)

    async def _build_draft(
        self,
        tenant_id: UUID,
        payload: LandedCostCreate,
        *,
        exclude_id: UUID | None = None,
    ) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
        document_date = payload.document_date or today_in_timezone(
            await self.org.get_timezone(tenant_id)
        )
        method = payload.allocation_method
        charge_rows, total_charges = await self._charge_rows(
            tenant_id, payload.charges, exclude_id=exclude_id
        )
        allocation_rows = await self._allocation_rows(
            tenant_id, payload.allocations, method=method, total_charges=total_charges
        )
        return (
            {
                "document_date": document_date,
                "allocation_method": method.value,
                "shipment_id": payload.shipment_id,
                "branch_id": payload.branch_id,
                "notes": payload.notes,
            },
            charge_rows,
            allocation_rows,
        )

    async def _charge_rows(
        self,
        tenant_id: UUID,
        charges: list[LandedCostChargeInput],
        *,
        exclude_id: UUID | None,
    ) -> tuple[list[dict[str, object]], Decimal]:
        from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository

        bill_repo = PurchaseInvoiceRepository(self.session)
        line_ids = [item.purchase_invoice_line_id for item in charges]
        if len(set(line_ids)) != len(line_ids):
            raise ValidationError("Duplicate bill lines are not allowed")
        allocated_map = await self.repo.posted_allocated_by_bill_line(
            tenant_id, line_ids, exclude_landed_cost_id=exclude_id
        )
        built: list[dict[str, object]] = []
        total = _ZERO
        for index, item in enumerate(charges, start=1):
            bill_line, bill = await self._require_expense_line(
                tenant_id, bill_repo, item.purchase_invoice_line_id
            )
            remaining = quantize_money(bill_line.amount - allocated_map.get(bill_line.id, _ZERO))
            amount = quantize_money(item.amount if item.amount is not None else remaining)
            if amount <= _ZERO:
                raise LandedCostLineOverAllocatedError(
                    details={"purchase_invoice_line_id": str(bill_line.id)}
                )
            if amount > remaining:
                raise LandedCostLineOverAllocatedError(
                    details={
                        "purchase_invoice_line_id": str(bill_line.id),
                        "remaining": str(remaining),
                    }
                )
            category = ExpenseCategory(bill_line.expense_category)
            built.append(
                {
                    "line_number": index,
                    "purchase_invoice_id": bill.id,
                    "purchase_invoice_line_id": bill_line.id,
                    "expense_category": category.value,
                    "bill_number": bill.document_number,
                    "amount": amount,
                }
            )
            total += amount
        return built, quantize_money(total)

    async def _allocation_rows(
        self,
        tenant_id: UUID,
        allocations: list[LandedCostAllocationInput],
        *,
        method: LandedCostAllocationMethod,
        total_charges: Decimal,
    ) -> list[dict[str, object]]:
        from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository

        receipt_repo = GoodsReceiptRepository(self.session)
        line_ids = [item.goods_receipt_line_id for item in allocations]
        if len(set(line_ids)) != len(line_ids):
            raise ValidationError("Duplicate goods receipt lines are not allowed")
        contexts: list[tuple[GoodsReceiptLine, Decimal]] = []
        for item in allocations:
            line, receipt = await self._require_posted_grn_line(
                tenant_id, receipt_repo, item.goods_receipt_line_id
            )
            base = await self._allocation_base(tenant_id, line, receipt.id, method)
            contexts.append((line, base))
        bases = [base for _, base in contexts]
        total_base = sum(bases, _ZERO)
        if total_base <= _ZERO:
            raise ValidationError("Allocation base cannot be zero")
        shares = _spread(total_charges, bases)
        built: list[dict[str, object]] = []
        for index, ((line, base), amount) in enumerate(zip(contexts, shares, strict=True), start=1):
            built.append(
                {
                    "line_number": index,
                    "goods_receipt_id": line.goods_receipt_id,
                    "goods_receipt_line_id": line.id,
                    "allocation_base": quantize_money(base),
                    "allocated_amount": amount,
                }
            )
        return built

    async def _allocation_base(
        self,
        tenant_id: UUID,
        line: GoodsReceiptLine,
        receipt_id: UUID,
        method: LandedCostAllocationMethod,
    ) -> Decimal:
        if method == LandedCostAllocationMethod.QUANTITY:
            return line.quantity
        if method == LandedCostAllocationMethod.WEIGHT:
            if line.net_weight is None or line.net_weight <= _ZERO:
                raise LandedCostWeightRequiredError(details={"goods_receipt_line_id": str(line.id)})
            return line.net_weight
        layers = await self.costing.layers_for_source(
            tenant_id, SOURCE_GOODS_RECEIPT, receipt_id, line.id
        )
        if layers:
            return sum((layer.qty_received * layer.landed_unit_cost for layer in layers), _ZERO)
        return line.quantity * line.rate

    async def _apply_post(
        self, tenant_id: UUID, row: LandedCost
    ) -> tuple[list[JournalLineInput], Decimal]:
        method = LandedCostAllocationMethod(row.allocation_method)
        total_charges = sum((charge.amount for charge in row.charges), _ZERO)
        await self._charge_rows(
            tenant_id,
            [
                LandedCostChargeInput(
                    purchase_invoice_line_id=charge.purchase_invoice_line_id,
                    amount=charge.amount,
                )
                for charge in row.charges
            ],
            exclude_id=row.id,
        )
        inventory_total = _ZERO
        variance_total = _ZERO
        for allocation in row.allocations:
            from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository

            line, receipt = await self._require_posted_grn_line(
                tenant_id, GoodsReceiptRepository(self.session), allocation.goods_receipt_line_id
            )
            if method == LandedCostAllocationMethod.WEIGHT and (
                line.net_weight is None or line.net_weight <= _ZERO
            ):
                raise LandedCostWeightRequiredError(details={"goods_receipt_line_id": str(line.id)})
            layers = await self.costing.layers_for_source(
                tenant_id, SOURCE_GOODS_RECEIPT, receipt.id, line.id
            )
            if not layers:
                raise ValidationError("Goods receipt line has no cost layers")
            qty_received = sum((layer.qty_received for layer in layers), _ZERO)
            if qty_received <= _ZERO:
                raise ValidationError("Goods receipt line quantity cannot be zero")
            extra_unit = quantize_money(allocation.allocated_amount / qty_received)
            qty_remaining = sum((layer.qty_remaining for layer in layers), _ZERO)
            qty_consumed = quantize_quantity(qty_received - qty_remaining)
            previous = layers[0].landed_unit_cost
            allocation.qty_remaining_at_post = quantize_quantity(qty_remaining)
            allocation.qty_consumed_at_post = qty_consumed
            allocation.previous_landed_unit_cost = previous
            for layer in layers:
                await self.costing.revalue(
                    tenant_id, layer.id, quantize_money(layer.landed_unit_cost + extra_unit)
                )
            inventory_total += quantize_money(qty_remaining * extra_unit)
            variance_total += quantize_money(qty_consumed * extra_unit)
        inventory_total = quantize_money(inventory_total)
        variance_total = quantize_money(total_charges - inventory_total)
        if variance_total < _ZERO:
            inventory_total = quantize_money(inventory_total + variance_total)
            variance_total = _ZERO
        lines: list[JournalLineInput] = []
        if inventory_total > _ZERO:
            inventory = await self.resolver.require(tenant_id, AccountSystemRole.INVENTORY)
            lines.append(
                JournalLineInput(
                    account_id=inventory.id,
                    debit=inventory_total,
                    credit=_ZERO,
                    description="Landed cost remaining stock",
                )
            )
        if variance_total > _ZERO:
            variance = await self.resolver.require(
                tenant_id, AccountSystemRole.LANDED_COST_VARIANCE
            )
            lines.append(
                JournalLineInput(
                    account_id=variance.id,
                    debit=variance_total,
                    credit=_ZERO,
                    description="Landed cost consumed variance",
                )
            )
        credits: dict[UUID, Decimal] = {}
        for charge in row.charges:
            account = await self._parked_account(
                tenant_id, ExpenseCategory(charge.expense_category)
            )
            credits[account.id] = credits.get(account.id, _ZERO) + charge.amount
        for account_id, amount in credits.items():
            lines.append(
                JournalLineInput(
                    account_id=account_id,
                    debit=_ZERO,
                    credit=quantize_money(amount),
                    description="Clear landed cost charge",
                )
            )
        return lines, inventory_total

    async def _cancel_posted(
        self, tenant_id: UUID, row: LandedCost, *, actor_user_id: UUID
    ) -> None:
        policy = await self._ensure_policy(tenant_id)
        if policy.is_locked(row.document_date, can_override=self._can_override):
            raise LandedCostCannotCancelError("The period is locked")
        later = await self.repo.later_posted_touching_lines(
            tenant_id,
            goods_receipt_line_ids=[item.goods_receipt_line_id for item in row.allocations],
            document_date=row.document_date,
            created_at=row.created_at,
            exclude_id=row.id,
        )
        if later:
            raise LandedCostCannotCancelError(
                "A later landed cost already revalued the same layers"
            )
        for allocation in row.allocations:
            if allocation.previous_landed_unit_cost is None:
                continue
            layers = await self.costing.layers_for_source(
                tenant_id,
                SOURCE_GOODS_RECEIPT,
                allocation.goods_receipt_id,
                allocation.goods_receipt_line_id,
            )
            previous = allocation.previous_landed_unit_cost
            for layer in layers:
                if layer.qty_remaining <= _ZERO:
                    continue
                await self.costing.revalue(tenant_id, layer.id, previous)
        reversal = await self.inventory_ledger.reverse(
            tenant_id,
            source_type="landed_cost",
            source_id=row.id,
            reversal_date=row.document_date,
            reason=row.cancel_reason or "Landed cost cancelled",
            actor_id=actor_user_id,
        )
        if reversal is not None:
            row.reversal_journal_entry_id = reversal.id
        row.is_posted = False

    async def _parked_account(self, tenant_id: UUID, category: ExpenseCategory):
        if category == ExpenseCategory.FREIGHT:
            return await self.resolver.require(tenant_id, AccountSystemRole.FREIGHT_IN)
        if category == ExpenseCategory.CUSTOMS_DUTY:
            return await self.resolver.require(tenant_id, AccountSystemRole.CUSTOMS_DUTY)
        return await self.resolver.require(tenant_id, AccountSystemRole.OTHER_CHARGES)

    async def _require_expense_line(
        self, tenant_id: UUID, bill_repo, line_id: UUID
    ) -> tuple[PurchaseInvoiceLine, Any]:
        from app.erp.purchase_invoices.models import PurchaseInvoice

        bill = (
            await bill_repo.get_by_line_id(tenant_id, line_id)
            if hasattr(bill_repo, "get_by_line_id")
            else None
        )
        if bill is None:
            bill = await self._bill_for_line(tenant_id, line_id)
        if bill is None:
            raise ResourceNotFoundError("Purchase invoice line not found")
        line = next((item for item in bill.lines if item.id == line_id), None)
        if line is None:
            raise ResourceNotFoundError("Purchase invoice line not found")
        if InvoiceDocumentStatus(bill.status) != InvoiceDocumentStatus.POSTED:
            raise ValidationError("Only posted bills can be allocated to landed cost")
        if PurchaseInvoiceLineType(line.line_type) != PurchaseInvoiceLineType.EXPENSE:
            raise ValidationError("Landed cost charges must be expense bill lines")
        if line.expense_category is None:
            raise ValidationError("Expense lines require expense_category")
        _ = PurchaseInvoice
        return line, bill

    async def _bill_for_line(self, tenant_id: UUID, line_id: UUID):
        from sqlalchemy import select

        from app.erp.purchase_invoices.models import PurchaseInvoiceLine
        from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository

        statement = select(PurchaseInvoiceLine.purchase_invoice_id).where(
            PurchaseInvoiceLine.tenant_id == tenant_id,
            PurchaseInvoiceLine.id == line_id,
        )
        bill_id = (await self.session.execute(statement)).scalar_one_or_none()
        if bill_id is None:
            return None
        return await PurchaseInvoiceRepository(self.session).get(tenant_id, bill_id)

    async def _require_posted_grn_line(
        self, tenant_id: UUID, receipt_repo, line_id: UUID
    ) -> tuple[GoodsReceiptLine, Any]:
        from sqlalchemy import select

        from app.inventory_management.goods_receipts.models import GoodsReceipt, GoodsReceiptLine

        statement = select(GoodsReceiptLine.goods_receipt_id).where(
            GoodsReceiptLine.tenant_id == tenant_id,
            GoodsReceiptLine.id == line_id,
        )
        receipt_id = (await self.session.execute(statement)).scalar_one_or_none()
        if receipt_id is None:
            raise ResourceNotFoundError("Goods receipt line not found")
        receipt = await receipt_repo.get(tenant_id, receipt_id)
        if receipt is None:
            raise ResourceNotFoundError("Goods receipt not found")
        if StockDocumentStatus(receipt.status) != StockDocumentStatus.POSTED:
            raise ValidationError("Only posted goods receipts can receive landed cost")
        line = next((item for item in receipt.lines if item.id == line_id), None)
        if line is None:
            raise ResourceNotFoundError("Goods receipt line not found")
        _ = GoodsReceipt
        return line, receipt

    async def _grns_for_shipment(self, tenant_id: UUID, shipment_id: UUID) -> list[UUID]:
        from app.erp.purchase_orders.repository import PurchaseOrderRepository
        from app.inventory_management.delivery_notes.repository import DeliveryNoteRepository
        from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository

        notes = await DeliveryNoteRepository(self.session).list_for_shipment(tenant_id, shipment_id)
        order_ids = [note.sales_order_id for note in notes]
        orders = await PurchaseOrderRepository(self.session).list_for_source_sales_orders(
            tenant_id, order_ids
        )
        receipts = await GoodsReceiptRepository(self.session).list_for_purchase_orders(
            tenant_id, [order.id for order in orders]
        )
        posted = [
            receipt.id
            for receipt in receipts
            if StockDocumentStatus(receipt.status) == StockDocumentStatus.POSTED
        ]
        unique = list(dict.fromkeys(posted))
        if notes and order_ids and orders and not unique:
            raise ValidationError(
                "Shipment sales orders have purchase orders but no posted goods receipts"
            )
        return unique

    async def _allocations_for_receipts(
        self, tenant_id: UUID, receipt_ids: list[UUID]
    ) -> list[LandedCostAllocationInput]:
        from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository

        allocations: list[LandedCostAllocationInput] = []
        repo = GoodsReceiptRepository(self.session)
        for receipt_id in receipt_ids:
            receipt = await repo.get(tenant_id, receipt_id)
            if receipt is None:
                raise ResourceNotFoundError("Goods receipt not found")
            if StockDocumentStatus(receipt.status) != StockDocumentStatus.POSTED:
                raise ValidationError("Only posted goods receipts can receive landed cost")
            for line in receipt.lines:
                if line.product_id is None:
                    continue
                allocations.append(LandedCostAllocationInput(goods_receipt_line_id=line.id))
        return allocations

    def _update_to_create(
        self, existing: LandedCost, payload: LandedCostUpdate
    ) -> LandedCostCreate:
        values = payload.model_dump(exclude_unset=True, exclude={"version"})
        charges = payload.charges
        if charges is None:
            charges = [
                LandedCostChargeInput(
                    purchase_invoice_line_id=charge.purchase_invoice_line_id,
                    amount=charge.amount,
                )
                for charge in existing.charges
            ]
        allocations = payload.allocations
        if allocations is None:
            allocations = [
                LandedCostAllocationInput(goods_receipt_line_id=item.goods_receipt_line_id)
                for item in existing.allocations
            ]
        method = values.get(
            "allocation_method", LandedCostAllocationMethod(existing.allocation_method)
        )
        if isinstance(method, str):
            method = LandedCostAllocationMethod(method)
        return LandedCostCreate(
            document_date=values.get("document_date", existing.document_date),
            allocation_method=method,
            shipment_id=values.get("shipment_id", existing.shipment_id),
            branch_id=values.get("branch_id", existing.branch_id),
            notes=values.get("notes", existing.notes),
            charges=charges,
            allocations=allocations,
        )

    async def _related_documents(
        self, tenant_id: UUID, row: LandedCost
    ) -> builtins.list[RelatedDocumentRef]:
        from app.erp.purchase_invoices.repository import PurchaseInvoiceRepository
        from app.inventory_management.goods_receipts.repository import GoodsReceiptRepository
        from app.logistics.shipments.repository import ShipmentRepository

        related: builtins.list[RelatedDocumentRef] = []
        if row.shipment_id is not None:
            shipment = await ShipmentRepository(self.session).get(tenant_id, row.shipment_id)
            if shipment is not None:
                related.append(
                    RelatedDocumentRef(
                        document_type=DocumentType.SHIPMENT.value,
                        document_id=shipment.id,
                        document_number=shipment.document_number,
                        status=shipment.status,
                        relationship="related",
                        document_date=shipment.etd,
                    )
                )
        seen_bills: set[UUID] = set()
        bill_repo = PurchaseInvoiceRepository(self.session)
        for charge in row.charges:
            if charge.purchase_invoice_id in seen_bills:
                continue
            seen_bills.add(charge.purchase_invoice_id)
            bill = await bill_repo.get(tenant_id, charge.purchase_invoice_id)
            if bill is None:
                continue
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.PURCHASE_INVOICE.value,
                    document_id=bill.id,
                    document_number=bill.document_number,
                    status=bill.status,
                    relationship="source",
                    document_date=bill.invoice_date,
                    amount_summary=str(charge.amount),
                )
            )
        seen_receipts: set[UUID] = set()
        receipt_repo = GoodsReceiptRepository(self.session)
        for allocation in row.allocations:
            if allocation.goods_receipt_id in seen_receipts:
                continue
            seen_receipts.add(allocation.goods_receipt_id)
            receipt = await receipt_repo.get(tenant_id, allocation.goods_receipt_id)
            if receipt is None:
                continue
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.GOODS_RECEIPT.value,
                    document_id=receipt.id,
                    document_number=receipt.document_number,
                    status=receipt.status,
                    relationship="related",
                    document_date=receipt.document_date,
                )
            )
        return related

    def _to_response(self, row: LandedCost) -> LandedCostResponse:
        status = StockDocumentStatus(row.status)
        date_locked = self._date_in_locked_period(row.document_date)
        post_blocked = self._post_blocked(row.document_date)
        total_charges = quantize_money(sum((charge.amount for charge in row.charges), _ZERO))
        return LandedCostResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            is_posted=row.is_posted,
            document_date=row.document_date,
            allocation_method=LandedCostAllocationMethod(row.allocation_method),
            shipment_id=row.shipment_id,
            branch_id=row.branch_id,
            journal_entry_id=row.journal_entry_id,
            reversal_journal_entry_id=row.reversal_journal_entry_id,
            notes=row.notes,
            total_charges=total_charges,
            posted_at=row.posted_at,
            posted_by=row.posted_by,
            cancelled_at=row.cancelled_at,
            cancelled_by=row.cancelled_by,
            cancel_reason=row.cancel_reason,
            available_actions=self._available_actions(status, period_locked=post_blocked),
            period_locked=date_locked,
            charges=[
                LandedCostChargeResponse(
                    id=charge.id,
                    line_number=charge.line_number,
                    purchase_invoice_id=charge.purchase_invoice_id,
                    purchase_invoice_line_id=charge.purchase_invoice_line_id,
                    expense_category=ExpenseCategory(charge.expense_category),
                    bill_number=charge.bill_number,
                    amount=charge.amount,
                )
                for charge in row.charges
            ],
            allocations=[
                LandedCostAllocationResponse(
                    id=item.id,
                    line_number=item.line_number,
                    goods_receipt_id=item.goods_receipt_id,
                    goods_receipt_line_id=item.goods_receipt_line_id,
                    allocation_base=item.allocation_base,
                    allocated_amount=item.allocated_amount,
                    qty_remaining_at_post=item.qty_remaining_at_post,
                    qty_consumed_at_post=item.qty_consumed_at_post,
                    previous_landed_unit_cost=item.previous_landed_unit_cost,
                )
                for item in row.allocations
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _available_actions(
        self, status: StockDocumentStatus, *, period_locked: bool
    ) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            if action in {"post", "cancel"} and period_locked:
                continue
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == StockDocumentStatus.DRAFT and has_permission(
            self.actor_permissions, LANDED_COST_UPDATE
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

    def _assert_version(self, row: LandedCost, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={
                    "current_version": row.version,
                    "provided_version": expected_version,
                }
            )

    async def _snapshot(self, row: LandedCost) -> dict[str, object]:
        return {
            "document_number": row.document_number,
            "status": row.status,
            "version": row.version,
            "document_date": row.document_date,
            "allocation_method": row.allocation_method,
            "charge_count": len(row.charges),
            "allocation_count": len(row.allocations),
        }

    async def _require(
        self, tenant_id: UUID, landed_cost_id: UUID, *, for_update: bool = False
    ) -> LandedCost:
        row = await self.repo.get(tenant_id, landed_cost_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Landed cost not found")
        return row


def _spread(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    total_weight = sum(weights, _ZERO)
    if total_weight <= _ZERO:
        return [_ZERO for _ in weights]
    raw = [quantize_money(total * (weight / total_weight)) for weight in weights]
    drift = quantize_money(total - sum(raw, _ZERO))
    if raw:
        raw[-1] = quantize_money(raw[-1] + drift)
    return raw
