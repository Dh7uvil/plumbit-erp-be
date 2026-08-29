"""Operational masters every tenant needs after it exists.

Idempotent: existing taxes, units, warehouses, terms, and sequences are left
alone. Safe to call from tenant creation and from a later backfill.
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


async def seed_required_masters(session: AsyncSession, tenant_id: UUID) -> None:
    """Insert VAT, UOMs, MAIN warehouse, Net 30, default T&C, and the QUO sequence."""

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
    for name, tax_category, rate, is_default in _TAXES:
        if name in existing_tax_names:
            continue
        session.add(
            Tax(
                tenant_id=tenant_id,
                name=name,
                tax_category=tax_category,
                rate=rate,
                is_default=is_default,
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
        session.add(
            Warehouse(
                tenant_id=tenant_id,
                code="MAIN",
                name="Main Warehouse",
                is_default=True,
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
        session.add(
            TermsTemplate(
                tenant_id=tenant_id,
                name="Standard terms",
                body=_DEFAULT_TC,
                is_default=True,
            )
        )

    fiscal_year = datetime.now(UTC).year
    existing_sequence = (
        await session.execute(
            select(DocumentSequence.id).where(
                DocumentSequence.tenant_id == tenant_id,
                DocumentSequence.document_type == DocumentType.QUOTATION.value,
                DocumentSequence.series == "QUO",
                DocumentSequence.fiscal_year == fiscal_year,
                DocumentSequence.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing_sequence is None:
        session.add(
            DocumentSequence(
                tenant_id=tenant_id,
                document_type=DocumentType.QUOTATION.value,
                series="QUO",
                fiscal_year=fiscal_year,
                prefix="QUO",
                next_number=1,
                padding=6,
            )
        )

    await session.flush()
