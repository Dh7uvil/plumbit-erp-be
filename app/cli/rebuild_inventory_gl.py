"""Explicit rebuild of missing inventory journals from stock movements.

Does not run automatically. Historical tenants whose GRN/QC path posted stock
without a journal can be repaired with ``uv run rebuild-inventory-gl --apply``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Tenant, User
from app.core.enums import StockMovementType, TenantStatus, UserStatus
from app.db.session import async_session_factory, transaction
from app.erp.accounting.ledger.inventory_posting import (
    SOURCE_DELIVERY_NOTE,
    SOURCE_GOODS_RECEIPT,
    SOURCE_PURCHASE_RETURN,
    SOURCE_QUALITY_INSPECTION,
    SOURCE_SALES_RETURN,
    SOURCE_STOCK_ADJUSTMENT,
    InventoryLedgerService,
)
from app.inventory_management.stock.models import StockMovement

_ZERO = Decimal("0")
_HOLD_TYPES = frozenset({StockMovementType.QC_HOLD.value, StockMovementType.QC_RELEASE.value})


@dataclass(frozen=True, slots=True)
class RebuildRow:
    source_type: str
    source_id: UUID
    document_date: date
    amount: Decimal
    restored: Decimal
    scrap: Decimal
    skipped: str | None = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild missing inventory GL journals from stock movements. "
            "Dry-run by default; pass --apply to post."
        )
    )
    parser.add_argument("--tenant-id", type=UUID, required=True, help="Tenant UUID")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Post missing journals. Without this flag the command only reports.",
    )
    return parser.parse_args()


async def _require_tenant(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or tenant.status != TenantStatus.ACTIVE:
        raise SystemExit(f"Active tenant not found: {tenant_id}")
    return tenant


async def _actor_id(session: AsyncSession, tenant_id: UUID) -> UUID:
    statement = (
        select(User.id)
        .where(User.tenant_id == tenant_id, User.status == UserStatus.ACTIVE)
        .order_by(User.created_at.asc())
        .limit(1)
    )
    user_id = await session.scalar(statement)
    if user_id is None:
        raise SystemExit(f"No active user found for tenant {tenant_id}")
    return user_id


async def _missing_rows(session: AsyncSession, tenant_id: UUID) -> list[RebuildRow]:
    from app.core.enums import JournalEntryStatus
    from app.erp.accounting.ledger.models import JournalEntry

    statement = select(StockMovement).where(
        StockMovement.tenant_id == tenant_id,
        StockMovement.movement_type.notin_(_HOLD_TYPES),
        StockMovement.value.is_not(None),
    )
    movements = list((await session.execute(statement)).scalars().all())
    grouped: dict[tuple[str, UUID], list[StockMovement]] = defaultdict(list)
    for row in movements:
        grouped[(row.source_type, row.source_id)].append(row)

    posted = {
        (source_type, source_id)
        for source_type, source_id in (
            await session.execute(
                select(JournalEntry.source_type, JournalEntry.source_id).where(
                    JournalEntry.tenant_id == tenant_id,
                    JournalEntry.status == JournalEntryStatus.POSTED.value,
                    JournalEntry.deleted_at.is_(None),
                    JournalEntry.source_type.is_not(None),
                    JournalEntry.source_id.is_not(None),
                )
            )
        ).all()
    }

    rows: list[RebuildRow] = []
    for (source_type, source_id), items in grouped.items():
        if (source_type, source_id) in posted:
            continue
        document_date = max(item.document_date for item in items)
        restored = sum(
            (
                item.value or _ZERO
                for item in items
                if item.movement_type == StockMovementType.RETURN_IN.value
            ),
            _ZERO,
        )
        scrap = sum(
            (
                abs(item.value or _ZERO)
                for item in items
                if item.movement_type == StockMovementType.DAMAGE.value
            ),
            _ZERO,
        )
        signed = sum((item.value or _ZERO for item in items), _ZERO)
        amount = abs(signed)
        skipped = None
        if source_type not in {
            SOURCE_GOODS_RECEIPT,
            SOURCE_DELIVERY_NOTE,
            SOURCE_PURCHASE_RETURN,
            SOURCE_QUALITY_INSPECTION,
            SOURCE_SALES_RETURN,
            SOURCE_STOCK_ADJUSTMENT,
        }:
            skipped = "unsupported_source"
        elif amount == _ZERO and restored == _ZERO and scrap == _ZERO:
            skipped = "zero_amount"
        rows.append(
            RebuildRow(
                source_type=source_type,
                source_id=source_id,
                document_date=document_date,
                amount=amount,
                restored=abs(restored),
                scrap=scrap,
                skipped=skipped,
            )
        )
    rows.sort(
        key=lambda item: (
            item.document_date.isoformat(),
            item.source_type,
            str(item.source_id),
        )
    )
    return rows


async def _apply_row(
    ledger: InventoryLedgerService,
    tenant_id: UUID,
    row: RebuildRow,
    *,
    actor_id: UUID,
) -> None:
    kwargs = {
        "source_id": row.source_id,
        "entry_date": row.document_date,
        "actor_id": actor_id,
    }
    if row.source_type == SOURCE_GOODS_RECEIPT:
        await ledger.post_goods_receipt(tenant_id, amount=row.amount, **kwargs)
    elif row.source_type == SOURCE_DELIVERY_NOTE:
        await ledger.post_delivery_note(tenant_id, amount=row.amount, **kwargs)
    elif row.source_type == SOURCE_PURCHASE_RETURN:
        await ledger.post_purchase_return(tenant_id, amount=row.amount, **kwargs)
    elif row.source_type == SOURCE_QUALITY_INSPECTION:
        await ledger.post_quality_scrap(tenant_id, amount=row.scrap or row.amount, **kwargs)
    elif row.source_type == SOURCE_SALES_RETURN:
        await ledger.post_sales_return(
            tenant_id,
            restored_amount=row.restored,
            scrap_amount=row.scrap,
            **kwargs,
        )
    else:
        raise ValueError(f"unsupported source {row.source_type}")


async def rebuild(tenant_id: UUID, *, apply: bool) -> int:
    async with async_session_factory() as session:
        await _require_tenant(session, tenant_id)
        actor_id = await _actor_id(session, tenant_id)
        rows = await _missing_rows(session, tenant_id)
        actionable = [row for row in rows if row.skipped is None]
        skipped = [row for row in rows if row.skipped is not None]
        print(f"tenant={tenant_id} missing={len(actionable)} skipped={len(skipped)} apply={apply}")
        for row in rows:
            flag = row.skipped or ("apply" if apply else "dry-run")
            print(
                f"  {row.document_date} {row.source_type} {row.source_id} "
                f"amount={row.amount} restored={row.restored} scrap={row.scrap} [{flag}]"
            )
        if not apply:
            return 0
        ledger = InventoryLedgerService(session)
        async with transaction(session):
            for row in actionable:
                if row.source_type == SOURCE_STOCK_ADJUSTMENT:
                    await _apply_adjustment(session, ledger, tenant_id, row, actor_id=actor_id)
                else:
                    await _apply_row(ledger, tenant_id, row, actor_id=actor_id)
        print(f"posted={len(actionable)}")
        return 0


async def _apply_adjustment(
    session: AsyncSession,
    ledger: InventoryLedgerService,
    tenant_id: UUID,
    row: RebuildRow,
    *,
    actor_id: UUID,
) -> None:
    statement = select(StockMovement.value).where(
        StockMovement.tenant_id == tenant_id,
        StockMovement.source_type == SOURCE_STOCK_ADJUSTMENT,
        StockMovement.source_id == row.source_id,
        StockMovement.value.is_not(None),
    )
    signed = sum(((value or _ZERO) for (value,) in (await session.execute(statement)).all()), _ZERO)
    await ledger.post_stock_adjustment(
        tenant_id,
        source_id=row.source_id,
        entry_date=row.document_date,
        inventory_delta=signed,
        actor_id=actor_id,
    )


def main() -> None:
    args = _parse_args()
    try:
        raise SystemExit(asyncio.run(rebuild(args.tenant_id, apply=args.apply)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
