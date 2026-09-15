"""One-time rewrite of party codes and compact document numbers."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Tenant
from app.core.enums import DocumentType, TenantStatus
from app.crm.customers.codes import unique_party_code
from app.crm.customers.models import Customer
from app.db.session import async_session_factory, transaction
from app.erp.accounting.customer_payments.models import CustomerPayment
from app.erp.accounting.fiscal import FiscalYearConfig
from app.erp.accounting.ledger.models import JournalEntry
from app.erp.accounting.models import DocumentSequence
from app.erp.accounting.numbering import (
    format_document_number,
    parse_compact_sequence,
    parse_old_document_number,
)
from app.erp.accounting.supplier_payments.models import SupplierPayment
from app.erp.credit_notes.models import CreditNote
from app.erp.debit_notes.models import DebitNote
from app.erp.landed_costs.models import LandedCost, LandedCostAllocation, LandedCostCharge
from app.erp.proforma_invoices.models import ProformaInvoice
from app.erp.purchase_invoices.models import PurchaseInvoice
from app.erp.purchase_orders.models import PurchaseOrder
from app.erp.quotation.models import Quotation, QuotationRevision
from app.erp.sales_invoices.models import SalesInvoice
from app.erp.sales_orders.models import SalesOrder
from app.inventory_management.delivery_notes.models import DeliveryNote
from app.inventory_management.goods_receipts.models import GoodsReceipt
from app.inventory_management.packages.models import Package
from app.inventory_management.purchase_returns.models import PurchaseReturn
from app.inventory_management.quality_inspections.models import QualityInspection
from app.inventory_management.sales_returns.models import SalesReturn
from app.inventory_management.stock_adjustments.models import StockAdjustment
from app.inventory_management.stock_transfers.models import StockTransfer
from app.logistics.shipments.models import Shipment

_PADDING = 6


def _temp_unique_value(entity_id: UUID) -> str:
    """Return a unique placeholder that fits ``VARCHAR(40)`` document numbers."""

    return f"~{entity_id.hex}"


def plan_party_code_updates(
    parties: list[tuple[UUID, str, str]],
    taken: list[str],
) -> tuple[dict[UUID, str], list[tuple[UUID, str]]]:
    """Return final codes and the subset that must change (id, new_code)."""

    assigned = [code for code in taken if code]
    codes: dict[UUID, str] = {}
    planned: list[tuple[UUID, str]] = []
    for party_id, name, current in parties:
        code = unique_party_code(name, assigned)
        assigned.append(code)
        codes[party_id] = code
        if current != code:
            planned.append((party_id, code))
    return codes, planned


def plan_document_number(
    current: str,
    *,
    prefix: str,
    fiscal_year: int,
    party_code: str | None,
    has_party: bool,
    padding: int = _PADDING,
) -> tuple[str | None, int | None]:
    """Return ``(new_number, seq)``; ``new_number`` is None when no rewrite is needed."""

    parsed_old = parse_old_document_number(current)
    if parsed_old is not None:
        _prefix, _year, seq = parsed_old
        new_number = format_document_number(
            prefix=prefix,
            party_code=party_code,
            fiscal_year=fiscal_year,
            number=seq,
            padding=padding,
        )
        return (None if current == new_number else new_number), seq
    compact_seq = parse_compact_sequence(current, prefix=prefix, has_party=has_party)
    return None, compact_seq


@dataclass(frozen=True, slots=True)
class NumberedTable:
    model: type[Any]
    number_attr: str
    prefix: str
    document_type: DocumentType
    date_attr: str
    party_attr: str | None = None
    has_party: bool = False


def _nt(
    model: type[Any],
    prefix: str,
    document_type: DocumentType,
    date_attr: str,
    party_attr: str | None = None,
    *,
    number_attr: str = "document_number",
    has_party: bool | None = None,
) -> NumberedTable:
    embeds = party_attr is not None if has_party is None else has_party
    return NumberedTable(
        model,
        number_attr,
        prefix,
        document_type,
        date_attr,
        party_attr,
        embeds,
    )


_TABLES: tuple[NumberedTable, ...] = (
    _nt(
        Quotation,
        "QUO",
        DocumentType.QUOTATION,
        "quote_date",
        "customer_id",
        number_attr="quote_number",
    ),
    _nt(SalesOrder, "SO", DocumentType.SALES_ORDER, "order_date", "customer_id"),
    _nt(ProformaInvoice, "PFI", DocumentType.PROFORMA_INVOICE, "proforma_date", "customer_id"),
    _nt(SalesInvoice, "INV", DocumentType.SALES_INVOICE, "invoice_date", "customer_id"),
    _nt(CreditNote, "CN", DocumentType.CREDIT_NOTE, "credit_note_date", "customer_id"),
    _nt(CustomerPayment, "RCP", DocumentType.CUSTOMER_PAYMENT, "payment_date", "customer_id"),
    _nt(DeliveryNote, "DN", DocumentType.DELIVERY_NOTE, "document_date", "customer_id"),
    _nt(SalesReturn, "SR", DocumentType.SALES_RETURN, "document_date", "customer_id"),
    _nt(PurchaseOrder, "PO", DocumentType.PURCHASE_ORDER, "order_date", "supplier_id"),
    _nt(GoodsReceipt, "GRN", DocumentType.GOODS_RECEIPT, "document_date", "supplier_id"),
    _nt(PurchaseInvoice, "BILL", DocumentType.PURCHASE_INVOICE, "invoice_date", "supplier_id"),
    _nt(DebitNote, "SDN", DocumentType.DEBIT_NOTE, "debit_note_date", "supplier_id"),
    _nt(SupplierPayment, "PAY", DocumentType.SUPPLIER_PAYMENT, "payment_date", "supplier_id"),
    _nt(PurchaseReturn, "PR", DocumentType.PURCHASE_RETURN, "document_date", "supplier_id"),
    _nt(StockTransfer, "STR", DocumentType.STOCK_TRANSFER, "document_date"),
    _nt(StockAdjustment, "STA", DocumentType.STOCK_ADJUSTMENT, "document_date"),
    _nt(JournalEntry, "JV", DocumentType.JOURNAL_ENTRY, "entry_date"),
    _nt(Shipment, "SHP", DocumentType.SHIPMENT, "created_at"),
    _nt(Package, "PKG", DocumentType.PACKAGE, "created_at", has_party=True),
    _nt(
        QualityInspection,
        "QCR",
        DocumentType.QUALITY_INSPECTION,
        "inspection_date",
        has_party=True,
    ),
    _nt(LandedCost, "LC", DocumentType.LANDED_COST, "document_date", has_party=True),
)


@dataclass(slots=True)
class TenantRenumberResult:
    tenant_id: UUID
    code: str
    parties_updated: int
    documents_updated: int
    sequences_updated: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite customer/supplier codes to unique 3-letter name codes and "
            "compact document numbers (SOAGM26000001). Idempotent for already-compact numbers."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing",
    )
    parser.add_argument("--tenant-id", type=UUID, default=None)
    parser.add_argument("--tenant-code", default=None)
    return parser.parse_args()


async def _load_tenants(
    *,
    tenant_id: UUID | None,
    tenant_code: str | None,
) -> list[tuple[UUID, str]]:
    statement = (
        select(Tenant.id, Tenant.code)
        .where(Tenant.status == TenantStatus.ACTIVE)
        .order_by(Tenant.created_at.asc())
    )
    if tenant_id is not None:
        statement = statement.where(Tenant.id == tenant_id)
    if tenant_code is not None:
        statement = statement.where(Tenant.code == tenant_code)
    async with async_session_factory() as session:
        result = await session.execute(statement)
        return [(row.id, row.code) for row in result.all()]


def _document_date(row: object, attr: str) -> date:
    value = getattr(row, attr)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"Unsupported date attribute {attr}")


async def _rewrite_party_codes(
    session: AsyncSession, tenant_id: UUID, *, dry_run: bool
) -> tuple[int, dict[UUID, str]]:
    result = await session.execute(
        select(Customer)
        .where(Customer.tenant_id == tenant_id, Customer.deleted_at.is_(None))
        .order_by(Customer.created_at.asc(), Customer.id.asc())
    )
    parties = list(result.scalars().all())
    deleted_codes = list(
        (
            await session.execute(
                select(Customer.code).where(
                    Customer.tenant_id == tenant_id,
                    Customer.deleted_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    codes, planned_ids = plan_party_code_updates(
        [(party.id, party.name, party.code) for party in parties],
        list(deleted_codes),
    )
    by_id = {party.id: party for party in parties}
    planned = [(by_id[party_id], code) for party_id, code in planned_ids]
    if dry_run:
        return len(planned), codes
    for party, _code in planned:
        party.code = _temp_unique_value(party.id)
    await session.flush()
    for party, code in planned:
        party.code = code
    await session.flush()
    return len(planned), codes


async def _package_party_ids(session: AsyncSession, tenant_id: UUID) -> dict[UUID, UUID]:
    result = await session.execute(
        select(Package.id, SalesOrder.customer_id)
        .join(SalesOrder, SalesOrder.id == Package.sales_order_id)
        .where(Package.tenant_id == tenant_id)
    )
    return {row.id: row.customer_id for row in result.all()}


async def _qcr_party_ids(session: AsyncSession, tenant_id: UUID) -> dict[UUID, UUID]:
    result = await session.execute(
        select(QualityInspection.id, GoodsReceipt.supplier_id)
        .join(GoodsReceipt, GoodsReceipt.id == QualityInspection.goods_receipt_id)
        .where(QualityInspection.tenant_id == tenant_id)
    )
    return {row.id: row.supplier_id for row in result.all()}


async def _landed_cost_party_ids(session: AsyncSession, tenant_id: UUID) -> dict[UUID, UUID]:
    mapping: dict[UUID, UUID] = {}
    allocations = await session.execute(
        select(LandedCostAllocation.landed_cost_id, GoodsReceipt.supplier_id)
        .join(GoodsReceipt, GoodsReceipt.id == LandedCostAllocation.goods_receipt_id)
        .join(LandedCost, LandedCost.id == LandedCostAllocation.landed_cost_id)
        .where(LandedCost.tenant_id == tenant_id)
        .order_by(LandedCostAllocation.line_number.asc())
    )
    for landed_cost_id, supplier_id in allocations.all():
        mapping.setdefault(landed_cost_id, supplier_id)
    charges = await session.execute(
        select(LandedCostCharge.landed_cost_id, PurchaseInvoice.supplier_id)
        .join(PurchaseInvoice, PurchaseInvoice.id == LandedCostCharge.purchase_invoice_id)
        .where(LandedCostCharge.tenant_id == tenant_id)
        .order_by(LandedCostCharge.line_number.asc())
    )
    for landed_cost_id, supplier_id in charges.all():
        mapping.setdefault(landed_cost_id, supplier_id)
    return mapping


async def _rewrite_table(
    session: AsyncSession,
    tenant_id: UUID,
    spec: NumberedTable,
    *,
    fiscal: FiscalYearConfig,
    party_codes: dict[UUID, str],
    extra_party_ids: dict[UUID, UUID],
    max_seq: dict[tuple[str, int], int],
    dry_run: bool,
) -> int:
    result = await session.execute(
        select(spec.model)
        .where(spec.model.tenant_id == tenant_id)
        .order_by(spec.model.created_at.asc(), spec.model.id.asc())
    )
    rows = list(result.scalars().all())
    planned: list[tuple[Any, str]] = []
    for row in rows:
        current = getattr(row, spec.number_attr)
        fiscal_year = fiscal.year_for(_document_date(row, spec.date_attr))
        party_id: UUID | None = None
        if spec.party_attr:
            party_id = getattr(row, spec.party_attr)
        elif spec.has_party:
            party_id = extra_party_ids.get(row.id)
        party_code = party_codes.get(party_id) if party_id is not None and spec.has_party else None
        if spec.has_party and party_code is None:
            party_code = "XXX"
        if not spec.has_party:
            party_code = None
        new_number, seq = plan_document_number(
            current,
            prefix=spec.prefix,
            fiscal_year=fiscal_year,
            party_code=party_code,
            has_party=spec.has_party,
        )
        if seq is not None:
            key = (spec.document_type.value, fiscal_year)
            max_seq[key] = max(max_seq[key], seq)
        if new_number is not None:
            planned.append((row, new_number))
    if dry_run:
        return len(planned)
    for row, _number in planned:
        setattr(row, spec.number_attr, _temp_unique_value(row.id))
    await session.flush()
    for row, number in planned:
        setattr(row, spec.number_attr, number)
    await session.flush()
    return len(planned)


async def _sync_quotation_revisions(
    session: AsyncSession, tenant_id: UUID, *, dry_run: bool
) -> None:
    if dry_run:
        return
    result = await session.execute(
        select(QuotationRevision, Quotation.quote_number)
        .join(Quotation, Quotation.id == QuotationRevision.quotation_id)
        .where(QuotationRevision.tenant_id == tenant_id)
    )
    for revision, quote_number in result.all():
        if revision.quote_number != quote_number:
            revision.quote_number = quote_number
    await session.flush()


async def _update_sequences(
    session: AsyncSession,
    tenant_id: UUID,
    max_seq: dict[tuple[str, int], int],
    *,
    dry_run: bool,
) -> int:
    result = await session.execute(
        select(DocumentSequence).where(
            DocumentSequence.tenant_id == tenant_id,
            DocumentSequence.deleted_at.is_(None),
        )
    )
    updated = 0
    for row in result.scalars().all():
        highest = max_seq.get((row.document_type, row.fiscal_year))
        if highest is None:
            continue
        next_number = highest + 1
        if row.next_number < next_number:
            updated += 1
            if not dry_run:
                row.next_number = next_number
    if not dry_run:
        await session.flush()
    return updated


async def renumber_tenant(
    session: AsyncSession, tenant_id: UUID, tenant_code: str, *, dry_run: bool
) -> TenantRenumberResult:
    fiscal = await FiscalYearConfig.load(session, tenant_id)
    parties_updated, party_codes = await _rewrite_party_codes(session, tenant_id, dry_run=dry_run)
    extra_party: dict[str, dict[UUID, UUID]] = {
        "PACKAGE": await _package_party_ids(session, tenant_id),
        "QUALITY_INSPECTION": await _qcr_party_ids(session, tenant_id),
        "LANDED_COST": await _landed_cost_party_ids(session, tenant_id),
    }
    max_seq: dict[tuple[str, int], int] = defaultdict(int)
    documents_updated = 0
    for spec in _TABLES:
        documents_updated += await _rewrite_table(
            session,
            tenant_id,
            spec,
            fiscal=fiscal,
            party_codes=party_codes,
            extra_party_ids=extra_party.get(spec.document_type.value, {}),
            max_seq=max_seq,
            dry_run=dry_run,
        )
    await _sync_quotation_revisions(session, tenant_id, dry_run=dry_run)
    sequences_updated = await _update_sequences(session, tenant_id, max_seq, dry_run=dry_run)
    return TenantRenumberResult(
        tenant_id=tenant_id,
        code=tenant_code,
        parties_updated=parties_updated,
        documents_updated=documents_updated,
        sequences_updated=sequences_updated,
    )


async def renumber_tenants(
    *,
    tenant_id: UUID | None = None,
    tenant_code: str | None = None,
    dry_run: bool = False,
) -> list[TenantRenumberResult]:
    tenants = await _load_tenants(tenant_id=tenant_id, tenant_code=tenant_code)
    if (tenant_id is not None or tenant_code is not None) and not tenants:
        raise ValueError("No active tenant matched the given filter")
    results: list[TenantRenumberResult] = []
    for target_id, code in tenants:
        async with async_session_factory() as session:
            if dry_run:
                result = await renumber_tenant(session, target_id, code, dry_run=True)
            else:
                async with transaction(session):
                    result = await renumber_tenant(session, target_id, code, dry_run=False)
            results.append(result)
    return results


def _print_summary(results: list[TenantRenumberResult], *, dry_run: bool) -> None:
    prefix = "Dry-run " if dry_run else ""
    if not results:
        print("No active tenants to renumber")
        return
    print(f"{prefix}Renumbered {len(results)} tenant(s)")
    for row in results:
        print(
            f"  {row.code}  {row.tenant_id}  "
            f"parties={row.parties_updated}  documents={row.documents_updated}  "
            f"sequences={row.sequences_updated}"
        )


def main() -> None:
    args = _parse_args()
    try:
        results = asyncio.run(
            renumber_tenants(
                tenant_id=args.tenant_id,
                tenant_code=args.tenant_code,
                dry_run=args.dry_run,
            )
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
        raise SystemExit(1) from None
    _print_summary(results, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
