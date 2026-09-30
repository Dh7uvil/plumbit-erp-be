"""Read-only data-quality checks used before adding DB constraints."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import configure_logging
from app.db.session import async_session_factory
from app.wiring import wire_platform

CheckRunner = Callable[[AsyncSession, UUID | None], list[tuple[UUID, int]]]

_SALES_LINE_COUNTERS_SQL = text(
    """
    SELECT tenant_id, COUNT(*)::int AS violations
    FROM (
        SELECT tenant_id
        FROM sales_order_lines
        WHERE qty_delivered > quantity
           OR qty_invoiced > quantity
           OR qty_returned > quantity
           OR qty_reserved > quantity
        UNION ALL
        SELECT tenant_id
        FROM sales_invoice_lines
        WHERE qty_credited > quantity
           OR qty_delivered > quantity
        UNION ALL
        SELECT tenant_id
        FROM delivery_note_lines
        WHERE qty_invoiced > quantity
    ) rows
    WHERE (:tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
    GROUP BY tenant_id
    ORDER BY tenant_id
    """
)

_GRAND_TOTAL_NEGATIVE_SQL = text(
    """
    SELECT tenant_id, COUNT(*)::int AS violations
    FROM (
        SELECT tenant_id FROM quotations
        WHERE grand_total < 0 AND deleted_at IS NULL
        UNION ALL
        SELECT tenant_id FROM sales_orders
        WHERE grand_total < 0 AND deleted_at IS NULL
        UNION ALL
        SELECT tenant_id FROM proforma_invoices
        WHERE grand_total < 0 AND deleted_at IS NULL
        UNION ALL
        SELECT tenant_id FROM sales_invoices
        WHERE grand_total < 0 AND deleted_at IS NULL
        UNION ALL
        SELECT tenant_id FROM credit_notes
        WHERE grand_total < 0 AND deleted_at IS NULL
        UNION ALL
        SELECT tenant_id FROM purchase_orders
        WHERE grand_total < 0 AND deleted_at IS NULL
        UNION ALL
        SELECT tenant_id FROM purchase_invoices
        WHERE grand_total < 0 AND deleted_at IS NULL
        UNION ALL
        SELECT tenant_id FROM debit_notes
        WHERE grand_total < 0 AND deleted_at IS NULL
    ) rows
    WHERE (:tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
    GROUP BY tenant_id
    ORDER BY tenant_id
    """
)

_SUPPLIER_INVOICE_DUPES_SQL = text(
    """
    SELECT tenant_id, SUM(cnt - 1)::int AS violations
    FROM (
        SELECT tenant_id, COUNT(*)::int AS cnt
        FROM purchase_invoices
        WHERE supplier_invoice_number IS NOT NULL
          AND BTRIM(supplier_invoice_number) <> ''
          AND deleted_at IS NULL
        GROUP BY tenant_id, supplier_id, supplier_invoice_number
        HAVING COUNT(*) > 1
    ) dupes
    WHERE (:tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
    GROUP BY tenant_id
    ORDER BY tenant_id
    """
)

_QUALITY_HOLD_EXCEEDS_ONHAND_SQL = text(
    """
    SELECT tenant_id, COUNT(*)::int AS violations
    FROM stock_balances
    WHERE qty_quality_hold > qty_on_hand
      AND deleted_at IS NULL
      AND (:tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
    GROUP BY tenant_id
    ORDER BY tenant_id
    """
)

_JOURNAL_REVERSED_SOURCE_SQL = text(
    """
    SELECT tenant_id, COUNT(*)::int AS violations
    FROM journal_entries
    WHERE status = 'POSTED'
      AND reversed_by_id IS NOT NULL
      AND source_type IS NOT NULL
      AND source_id IS NOT NULL
      AND deleted_at IS NULL
      AND (:tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
    GROUP BY tenant_id
    ORDER BY tenant_id
    """
)

CHECKS: dict[str, tuple[str, CheckRunner]] = {}


def _register(name: str, description: str, sql: text) -> None:
    async def _run(session: AsyncSession, tenant_id: UUID | None) -> list[tuple[UUID, int]]:
        result = await session.execute(
            sql,
            {"tenant_id": str(tenant_id) if tenant_id is not None else None},
        )
        return [(row.tenant_id, row.violations) for row in result]

    CHECKS[name] = (description, _run)


_register(
    "sales-line-counters",
    "Sales line counters exceed ordered quantity",
    _SALES_LINE_COUNTERS_SQL,
)
_register(
    "grand-total-negative",
    "Commercial documents with negative grand_total",
    _GRAND_TOTAL_NEGATIVE_SQL,
)
_register(
    "supplier-invoice-dupes",
    "Duplicate supplier invoice numbers per supplier",
    _SUPPLIER_INVOICE_DUPES_SQL,
)
_register(
    "quality-hold-exceeds-onhand",
    "Stock rows where qty_quality_hold exceeds qty_on_hand",
    _QUALITY_HOLD_EXCEEDS_ONHAND_SQL,
)
_register(
    "journal-reversed-source",
    "Posted source journals that have already been reversed",
    _JOURNAL_REVERSED_SOURCE_SQL,
)


async def _run_check(check: str, *, tenant_id: UUID | None) -> int:
    wire_platform()
    description, runner = CHECKS[check]
    total = 0
    async with async_session_factory() as session:
        rows = await runner(session, tenant_id)
    if not rows:
        scope = f"tenant={tenant_id}" if tenant_id is not None else "all tenants"
        print(f"{check}: {scope} ok (0 violations)")
        return 0
    for tid, count in rows:
        print(f"tenant={tid} violations={count}")
        total += count
    print(f"{check}: {description}; total violations={total}")
    return total


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run read-only data-quality checks before adding DB constraints.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, (description, _) in CHECKS.items():
        sub = subparsers.add_parser(name, help=description)
        sub.add_argument("--tenant-id", default=None, help="Limit to one tenant UUID")
    return parser.parse_args()


def main() -> None:
    from app.core.config import get_settings

    args = _parse_args()
    configure_logging(get_settings().log_level)
    tenant_id = UUID(args.tenant_id) if args.tenant_id is not None else None
    try:
        violations = asyncio.run(_run_check(args.command, tenant_id=tenant_id))
    except KeyboardInterrupt:
        print("Stopped", file=sys.stderr)
        raise SystemExit(0) from None
    if violations:
        print(
            f"Data-quality check '{args.command}' failed with {violations} violation(s)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"Data-quality check '{args.command}' passed")


if __name__ == "__main__":
    main()
