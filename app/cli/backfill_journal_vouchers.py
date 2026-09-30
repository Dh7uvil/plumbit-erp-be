"""Backfill JOURNAL vouchers from legacy manual journal entries.

Dry-run by default. Idempotent: skips journals already linked to a voucher.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.models import Tenant, User
from app.core.enums import JournalEntryStatus, JournalType, TenantStatus, UserStatus, VoucherType
from app.db.session import async_session_factory, transaction
from app.erp.accounting.ledger.models import JournalEntry
from app.erp.accounting.vouchers.models import Voucher
from app.erp.accounting.vouchers.repository import VoucherRepository

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    journal_id: UUID
    document_number: str
    entry_date: str
    status: str
    line_count: int
    debit_total: Decimal


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill JOURNAL vouchers from manual journal entries. "
            "Dry-run by default; pass --apply to persist."
        )
    )
    parser.add_argument("--tenant-id", type=UUID, required=True, help="Tenant UUID")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create missing vouchers. Without this flag the command only reports.",
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


async def _linked_journal_ids(session: AsyncSession, tenant_id: UUID) -> set[UUID]:
    statement = select(Voucher.journal_entry_id).where(
        Voucher.tenant_id == tenant_id,
        Voucher.deleted_at.is_(None),
        Voucher.journal_entry_id.is_not(None),
    )
    return {row for row in (await session.scalars(statement)).all() if row is not None}


async def _candidate_journals(session: AsyncSession, tenant_id: UUID) -> list[JournalEntry]:
    linked = await _linked_journal_ids(session, tenant_id)
    statement = (
        select(JournalEntry)
        .where(
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.deleted_at.is_(None),
            JournalEntry.journal_type == JournalType.MANUAL.value,
            JournalEntry.source_type.is_(None),
        )
        .options(selectinload(JournalEntry.lines))
        .order_by(JournalEntry.entry_date.asc(), JournalEntry.document_number.asc())
    )
    rows = list((await session.scalars(statement)).all())
    return [row for row in rows if row.id not in linked]


def _plan_for(journal: JournalEntry) -> BackfillPlan:
    debit_total = sum((line.debit for line in journal.lines), _ZERO)
    return BackfillPlan(
        journal_id=journal.id,
        document_number=journal.document_number,
        entry_date=journal.entry_date.isoformat(),
        status=journal.status,
        line_count=len(journal.lines),
        debit_total=debit_total,
    )


async def _create_voucher(
    session: AsyncSession,
    tenant_id: UUID,
    journal: JournalEntry,
    *,
    actor_user_id: UUID,
) -> Voucher:
    repo = VoucherRepository(session)
    debit_total = sum((line.debit for line in journal.lines), _ZERO)
    is_posted = JournalEntryStatus(journal.status) == JournalEntryStatus.POSTED
    row = await repo.create(
        tenant_id,
        {
            "document_number": journal.document_number,
            "voucher_type": VoucherType.JOURNAL.value,
            "status": journal.status,
            "version": journal.version,
            "is_posted": is_posted,
            "voucher_date": journal.entry_date,
            "payment_account_id": None,
            "counter_account_id": None,
            "total_amount": debit_total,
            "amount_unapplied": _ZERO,
            "currency_id": journal.currency_id,
            "base_currency_id": journal.currency_id,
            "exchange_rate": journal.exchange_rate,
            "foreign_amount": debit_total,
            "base_amount": debit_total,
            "party_type": None,
            "party_id": None,
            "payment_method": None,
            "cheque_number": None,
            "cheque_date": None,
            "external_reference": journal.external_reference,
            "reference": journal.reference,
            "branch_id": journal.branch_id,
            "cost_center_id": journal.cost_center_id,
            "narration": journal.narration,
            "journal_entry_id": journal.id,
            "reversal_journal_entry_id": journal.reversed_by_id,
            "posted_at": journal.posted_at,
            "posted_by": journal.posted_by,
            "created_by": actor_user_id,
            "updated_by": actor_user_id,
        },
    )
    await repo.replace_lines(
        tenant_id,
        row.id,
        [
            {
                "line_number": line.line_number,
                "account_id": line.account_id,
                "amount": max(line.debit, line.credit),
                "debit": line.debit,
                "credit": line.credit,
                "party_type": line.party_type,
                "party_id": line.party_id,
                "tax_id": line.tax_id,
                "branch_id": line.branch_id,
                "cost_center_id": line.cost_center_id,
                "description": line.description,
            }
            for line in journal.lines
        ],
    )
    return row


async def _run(tenant_id: UUID, *, apply: bool) -> int:
    async with async_session_factory() as session:
        await _require_tenant(session, tenant_id)
        candidates = await _candidate_journals(session, tenant_id)
        if not candidates:
            print("No manual journal entries require backfill.")
            return 0

        plans = [_plan_for(journal) for journal in candidates]
        print(f"Found {len(plans)} manual journal(s) without a linked JOURNAL voucher:")
        for plan in plans:
            print(
                f"  {plan.document_number} ({plan.entry_date}) "
                f"status={plan.status} lines={plan.line_count} debit={plan.debit_total}"
            )

        if not apply:
            print("Dry run only. Re-run with --apply to create vouchers.")
            return 0

        actor_user_id = await _actor_id(session, tenant_id)
        created = 0
        async with transaction(session):
            for journal in candidates:
                linked = await session.scalar(
                    select(Voucher.id).where(
                        Voucher.tenant_id == tenant_id,
                        Voucher.journal_entry_id == journal.id,
                        Voucher.deleted_at.is_(None),
                    )
                )
                if linked is not None:
                    continue
                await _create_voucher(session, tenant_id, journal, actor_user_id=actor_user_id)
                created += 1
        print(f"Created {created} JOURNAL voucher(s).")
        return 0


def main() -> None:
    args = _parse_args()
    raise SystemExit(asyncio.run(_run(args.tenant_id, apply=args.apply)))


if __name__ == "__main__":
    main()
    sys.exit(0)
