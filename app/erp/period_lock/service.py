"""Period lock get, preview, and apply use cases."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ERP_MODULE
from app.auth.org_service import OrganizationService
from app.common.period_lock import PeriodLockPolicy
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.datetime import today_in_timezone
from app.core.enums import AuditAction, StockDocumentStatus
from app.core.exceptions import PeriodLockBlockedNegativeStockError, ValidationError
from app.db.session import transaction
from app.erp.period_lock.schemas import (
    PREVIEW_CAP,
    REASON_MIN_LENGTH,
    PeriodLockNegativeBalance,
    PeriodLockPreviewResponse,
    PeriodLockResponse,
    PeriodLockUnpostedDocument,
    PeriodLockUpdate,
)
from app.inventory_management.stock.service import StockService
from app.inventory_management.stock_adjustments.service import StockAdjustmentService
from app.inventory_management.stock_transfers.service import StockTransferService

_NEGATIVE_DISALLOWED = "negative_stock_disallowed"
_ACK_REQUIRED = "acknowledgement_required"


def _is_advancing(old: date | None, new: date | None) -> bool:
    if new is None:
        return False
    if old is None:
        return True
    return new > old


def _is_retreating_or_clearing(old: date | None, new: date | None) -> bool:
    if old is None:
        return False
    if new is None:
        return True
    return new < old


def _locked_through(lock_date: date | None, hard_lock_date: date | None) -> date | None:
    dates = [value for value in (lock_date, hard_lock_date) if value is not None]
    return max(dates) if dates else None


class PeriodLockService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.org = OrganizationService(session)
        self.stock = StockService(session)
        self.adjustments = StockAdjustmentService(session)
        self.transfers = StockTransferService(session)
        self.audit = AuditWriter(session)

    async def get(self, tenant_id: UUID) -> PeriodLockResponse:
        _, policy = await self.org.get_inventory_controls(tenant_id)
        return self._to_response(policy)

    async def preview(
        self,
        tenant_id: UUID,
        *,
        lock_date: date | None = None,
        hard_lock_date: date | None = None,
    ) -> PeriodLockPreviewResponse:
        allow_negative, current = await self.org.get_inventory_controls(tenant_id)
        proposed_lock = current.lock_date if lock_date is None else lock_date
        proposed_hard = current.hard_lock_date if hard_lock_date is None else hard_lock_date
        self._assert_invariants(
            lock_date=proposed_lock,
            hard_lock_date=proposed_hard,
            timezone=await self.org.get_timezone(tenant_id),
        )
        advancing = _is_advancing(current.lock_date, proposed_lock) or _is_advancing(
            current.hard_lock_date, proposed_hard
        )
        return await self._probe(
            tenant_id,
            allow_negative_stock=allow_negative,
            advancing=advancing,
            as_of=_locked_through(proposed_lock, proposed_hard),
        )

    async def apply(
        self,
        tenant_id: UUID,
        payload: PeriodLockUpdate,
        *,
        actor_user_id: UUID,
    ) -> PeriodLockResponse:
        lock_date_set = "lock_date" in payload.model_fields_set
        hard_lock_set = "hard_lock_date" in payload.model_fields_set
        async with transaction(self.session):
            allow_negative, current = await self.org.get_inventory_controls(
                tenant_id, for_update=True
            )
            if not lock_date_set and not hard_lock_set:
                return self._to_response(current)

            proposed_lock = payload.lock_date if lock_date_set else current.lock_date
            proposed_hard = payload.hard_lock_date if hard_lock_set else current.hard_lock_date
            timezone = await self.org.get_timezone(tenant_id)
            self._assert_invariants(
                lock_date=proposed_lock,
                hard_lock_date=proposed_hard,
                timezone=timezone,
            )

            retreating = (
                lock_date_set and _is_retreating_or_clearing(current.lock_date, proposed_lock)
            ) or (
                hard_lock_set and _is_retreating_or_clearing(current.hard_lock_date, proposed_hard)
            )
            reason = payload.reason
            if retreating:
                if reason is None or len(reason) < REASON_MIN_LENGTH:
                    raise ValidationError(
                        f"A reason of at least {REASON_MIN_LENGTH} characters is required "
                        "to unlock or move a lock date backward"
                    )
            elif reason is not None and len(reason) < REASON_MIN_LENGTH:
                raise ValidationError(f"Reason must be at least {REASON_MIN_LENGTH} characters")

            advancing = _is_advancing(current.lock_date, proposed_lock) or _is_advancing(
                current.hard_lock_date, proposed_hard
            )
            if advancing:
                probe = await self._probe(
                    tenant_id,
                    allow_negative_stock=allow_negative,
                    advancing=True,
                    as_of=_locked_through(proposed_lock, proposed_hard),
                )
                if probe.negative_balances_total_count > 0:
                    if probe.blocked:
                        raise PeriodLockBlockedNegativeStockError(
                            details=self._negative_details(
                                _NEGATIVE_DISALLOWED,
                                probe.negative_balances,
                                probe.negative_balances_total_count,
                            )
                        )
                    if not payload.acknowledge_negative_stock:
                        raise PeriodLockBlockedNegativeStockError(
                            details=self._negative_details(
                                _ACK_REQUIRED,
                                probe.negative_balances,
                                probe.negative_balances_total_count,
                            )
                        )

            lock_reason = current.lock_reason
            hard_lock_reason = current.hard_lock_reason
            if reason is not None:
                if lock_date_set:
                    lock_reason = reason
                if hard_lock_set:
                    hard_lock_reason = reason

            updated = await self.org.set_period_lock(
                tenant_id,
                lock_date=proposed_lock,
                hard_lock_date=proposed_hard,
                lock_reason=lock_reason,
                hard_lock_reason=hard_lock_reason,
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ERP_MODULE,
                entity_type="period_lock",
                entity_id=tenant_id,
                old_values={
                    "lock_date": current.lock_date,
                    "hard_lock_date": current.hard_lock_date,
                    "lock_reason": current.lock_reason,
                    "hard_lock_reason": current.hard_lock_reason,
                },
                new_values={
                    "lock_date": updated.lock_date,
                    "hard_lock_date": updated.hard_lock_date,
                    "lock_reason": updated.lock_reason,
                    "hard_lock_reason": updated.hard_lock_reason,
                    "acknowledge_negative_stock": payload.acknowledge_negative_stock,
                },
            )
            return self._to_response(updated)

    async def _probe(
        self,
        tenant_id: UUID,
        *,
        allow_negative_stock: bool,
        advancing: bool,
        as_of: date | None,
    ) -> PeriodLockPreviewResponse:
        page = PageParams(page=1, page_size=PREVIEW_CAP)
        negative_rows, negative_total = await self.stock.list_balances(
            tenant_id, page=page, negative_only=True
        )
        negatives = [
            PeriodLockNegativeBalance(
                warehouse_id=row.warehouse_id,
                warehouse_code=row.warehouse_code,
                product_id=row.product_id,
                sku=row.sku,
                qty_on_hand=row.qty_on_hand,
            )
            for row in negative_rows
        ]
        unposted, unposted_total = await self._unposted_documents(tenant_id, as_of=as_of)
        has_negatives = negative_total > 0
        blocked = advancing and has_negatives and not allow_negative_stock
        requires_acknowledgement = advancing and has_negatives and allow_negative_stock
        return PeriodLockPreviewResponse(
            allow_negative_stock=allow_negative_stock,
            negative_balances=negatives,
            negative_balances_total_count=negative_total,
            negative_balances_are_current=True,
            unposted_documents=unposted,
            unposted_documents_total_count=unposted_total,
            blocked=blocked,
            requires_acknowledgement=requires_acknowledgement,
        )

    async def _unposted_documents(
        self, tenant_id: UUID, *, as_of: date | None
    ) -> tuple[list[PeriodLockUnpostedDocument], int]:
        if as_of is None:
            return [], 0
        page = PageParams(page=1, page_size=PREVIEW_CAP)
        status = StockDocumentStatus.DRAFT.value
        adjustments, adj_total = await self.adjustments.list(
            tenant_id, page=page, status=status, document_date_to=as_of
        )
        transfers, transfer_total = await self.transfers.list(
            tenant_id, page=page, status=status, document_date_to=as_of
        )
        documents = [
            PeriodLockUnpostedDocument(
                id=row.id,
                document_type="stock_adjustment",
                document_number=row.document_number,
                document_date=row.document_date,
                status=row.status.value,
            )
            for row in adjustments
        ]
        documents.extend(
            PeriodLockUnpostedDocument(
                id=row.id,
                document_type="stock_transfer",
                document_number=row.document_number,
                document_date=row.document_date,
                status=row.status.value,
            )
            for row in transfers
        )
        documents.sort(key=lambda item: (item.document_date, item.document_number))
        return documents[:PREVIEW_CAP], adj_total + transfer_total

    def _assert_invariants(
        self,
        *,
        lock_date: date | None,
        hard_lock_date: date | None,
        timezone: str,
    ) -> None:
        today = today_in_timezone(timezone)
        if lock_date is not None and lock_date > today:
            raise ValidationError("lock_date cannot be after today")
        if hard_lock_date is not None and hard_lock_date > today:
            raise ValidationError("hard_lock_date cannot be after today")
        if lock_date is not None and hard_lock_date is not None and hard_lock_date > lock_date:
            raise ValidationError("hard_lock_date cannot be after lock_date")

    def _to_response(self, policy: PeriodLockPolicy) -> PeriodLockResponse:
        return PeriodLockResponse(
            lock_date=policy.lock_date,
            hard_lock_date=policy.hard_lock_date,
            lock_reason=policy.lock_reason,
            hard_lock_reason=policy.hard_lock_reason,
        )

    def _negative_details(
        self,
        reason: str,
        balances: list[PeriodLockNegativeBalance],
        total_count: int,
    ) -> dict[str, object]:
        return {
            "reason": reason,
            "balances": [
                {
                    "warehouse_id": str(row.warehouse_id),
                    "warehouse_code": row.warehouse_code,
                    "product_id": str(row.product_id),
                    "sku": row.sku,
                    "qty_on_hand": str(row.qty_on_hand),
                }
                for row in balances
            ],
            "total_count": total_count,
        }
