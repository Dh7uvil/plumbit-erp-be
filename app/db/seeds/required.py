"""Operational masters every tenant needs after it exists.

Idempotent for taxes, units, warehouses, and terms (insert if missing).
Canonical document sequences are upserted: missing rows are inserted; existing
canonical rows get prefix and padding reconciled. ``next_number`` and
``is_active`` are never reset. Safe to call from tenant creation and backfill.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentType, TaxCategory
from app.erp.accounting.models import DocumentSequence, PaymentTerm, Tax, TermsTemplate
from app.inventory_management.units.models import Unit
from app.inventory_management.warehouses.models import Warehouse

_DEFAULT_TC = (
    "Prices are in the document currency and exclusive of delivery unless stated. "
    "This quotation is valid until the stated expiry date."
)

_TAXES: tuple[tuple[str, str, Decimal, bool], ...] = (
    ("Standard VAT 5%", TaxCategory.STANDARD.value, Decimal("5"), True),
    ("Zero Rated", TaxCategory.ZERO_RATED.value, Decimal("0"), False),
    ("Exempt", TaxCategory.EXEMPT.value, Decimal("0"), False),
    ("Out of Scope", TaxCategory.OUT_OF_SCOPE.value, Decimal("0"), False),
)

_UNITS: tuple[tuple[str, str], ...] = (
    ("PCS", "Pieces"),
    ("BOX", "Box"),
    ("M", "Metre"),
    ("KG", "Kilogram"),
)

# Canonical series equals prefix. Debit notes use SDN so DN stays delivery notes.
_DOCUMENT_SEQUENCES: tuple[tuple[DocumentType, str], ...] = (
    (DocumentType.QUOTATION, "QUO"),
    (DocumentType.SALES_ORDER, "SO"),
    (DocumentType.DELIVERY_NOTE, "DN"),
    (DocumentType.SALES_INVOICE, "INV"),
    (DocumentType.CREDIT_NOTE, "CN"),
    (DocumentType.PURCHASE_ORDER, "PO"),
    (DocumentType.GOODS_RECEIPT, "GRN"),
    (DocumentType.PURCHASE_INVOICE, "BILL"),
    (DocumentType.DEBIT_NOTE, "SDN"),
    (DocumentType.STOCK_TRANSFER, "STR"),
    (DocumentType.STOCK_ADJUSTMENT, "STA"),
)

_SEQUENCE_PADDING = 6


async def seed_required_masters(session: AsyncSession, tenant_id: UUID) -> None:
    """Insert VAT, UOMs, MAIN warehouse, Net 30, default T&C, and document sequences."""

    existing_tax_names = set(
        (
            await session.execute(
                select(Tax.name).where(
                    Tax.tenant_id == tenant_id,
                    Tax.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    has_default_tax = (
        await session.execute(
            select(Tax.id).where(
                Tax.tenant_id == tenant_id,
                Tax.is_default.is_(True),
                Tax.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none() is not None
    for name, tax_category, rate, is_default in _TAXES:
        if name in existing_tax_names:
            continue
        session.add(
            Tax(
                tenant_id=tenant_id,
                name=name,
                tax_category=tax_category,
                rate=rate,
                is_default=is_default and not has_default_tax,
            )
        )

    existing_unit_codes = set(
        (
            await session.execute(
                select(Unit.code).where(
                    Unit.tenant_id == tenant_id,
                    Unit.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for code, name in _UNITS:
        if code in existing_unit_codes:
            continue
        session.add(Unit(tenant_id=tenant_id, code=code, name=name))

    existing_warehouse = (
        await session.execute(
            select(Warehouse.id).where(
                Warehouse.tenant_id == tenant_id,
                Warehouse.code == "MAIN",
                Warehouse.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing_warehouse is None:
        has_default_warehouse = (
            await session.execute(
                select(Warehouse.id).where(
                    Warehouse.tenant_id == tenant_id,
                    Warehouse.is_default.is_(True),
                    Warehouse.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none() is not None
        session.add(
            Warehouse(
                tenant_id=tenant_id,
                code="MAIN",
                name="Main Warehouse",
                is_default=not has_default_warehouse,
            )
        )

    existing_term = (
        await session.execute(
            select(PaymentTerm.id).where(
                PaymentTerm.tenant_id == tenant_id,
                PaymentTerm.name == "Net 30",
                PaymentTerm.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing_term is None:
        session.add(
            PaymentTerm(
                tenant_id=tenant_id,
                name="Net 30",
                days=30,
                description="Payment due 30 days from the document date",
            )
        )

    existing_terms = (
        await session.execute(
            select(TermsTemplate.id).where(
                TermsTemplate.tenant_id == tenant_id,
                TermsTemplate.name == "Standard terms",
                TermsTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing_terms is None:
        has_default_terms = (
            await session.execute(
                select(TermsTemplate.id).where(
                    TermsTemplate.tenant_id == tenant_id,
                    TermsTemplate.is_default.is_(True),
                    TermsTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none() is not None
        session.add(
            TermsTemplate(
                tenant_id=tenant_id,
                name="Standard terms",
                body=_DEFAULT_TC,
                is_default=not has_default_terms,
            )
        )

    await _upsert_document_sequences(session, tenant_id)
    await session.flush()


async def _upsert_document_sequences(session: AsyncSession, tenant_id: UUID) -> None:
    """Insert missing canonical sequences; restore prefix/padding without resetting counters."""

    fiscal_year = datetime.now(UTC).year
    existing_rows = (
        (
            await session.execute(
                select(DocumentSequence).where(
                    DocumentSequence.tenant_id == tenant_id,
                    DocumentSequence.fiscal_year == fiscal_year,
                    DocumentSequence.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_key = {(row.document_type, row.series): row for row in existing_rows}

    for document_type, series in _DOCUMENT_SEQUENCES:
        existing = by_key.get((document_type.value, series))
        if existing is None:
            session.add(
                DocumentSequence(
                    tenant_id=tenant_id,
                    document_type=document_type.value,
                    series=series,
                    fiscal_year=fiscal_year,
                    prefix=series,
                    next_number=1,
                    padding=_SEQUENCE_PADDING,
                )
            )
            continue
        if existing.prefix != series:
            existing.prefix = series
        if existing.padding != _SEQUENCE_PADDING:
            existing.padding = _SEQUENCE_PADDING
