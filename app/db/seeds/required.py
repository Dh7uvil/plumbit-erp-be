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
from app.erp.accounting.accounts.chart import UAE_CHART
from app.erp.accounting.accounts.models import Account
from app.erp.accounting.fiscal import FiscalYearConfig
from app.erp.accounting.models import DocumentSequence, PaymentTerm, Tax, TermsTemplate
from app.db.seeds.charge_types import seed_charge_types
from app.db.seeds.crm_foundations import seed_crm_foundations
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
    (DocumentType.GRN_CHARGE_ADJUSTMENT, "GCA"),
    (DocumentType.PURCHASE_INVOICE, "BILL"),
    (DocumentType.DEBIT_NOTE, "SDN"),
    (DocumentType.STOCK_TRANSFER, "STR"),
    (DocumentType.STOCK_ADJUSTMENT, "STA"),
    (DocumentType.PROFORMA_INVOICE, "PFI"),
    (DocumentType.QUALITY_INSPECTION, "QCR"),
    (DocumentType.PACKAGE, "PKG"),
    (DocumentType.SHIPMENT, "SHP"),
    (DocumentType.SALES_RETURN, "SR"),
    (DocumentType.PURCHASE_RETURN, "PR"),
    (DocumentType.JOURNAL_ENTRY, "JV"),
    (DocumentType.CUSTOMER_PAYMENT, "RCP"),
    (DocumentType.SUPPLIER_PAYMENT, "PAY"),
    (DocumentType.COST_SHEET_IMPORT, "CSI"),
    (DocumentType.COST_SHEET_EXPORT, "CSE"),
    (DocumentType.COST_SHEET_OTHER, "CSO"),
    (DocumentType.CASH_RECEIPT_VOUCHER, "CRV"),
    (DocumentType.CASH_PAYMENT_VOUCHER, "CPV"),
    (DocumentType.BANK_RECEIPT_VOUCHER, "BRV"),
    (DocumentType.BANK_PAYMENT_VOUCHER, "BPV"),
    (DocumentType.CONTRA_VOUCHER, "CON"),
    (DocumentType.GENERAL_PURCHASE_VOUCHER, "GP"),
    (DocumentType.PAYMENT_VOUCHER, "PV"),
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
    await seed_chart_of_accounts(session, tenant_id)
    await reconcile_chart_of_accounts(session, tenant_id)
    await seed_crm_foundations(session, tenant_id)
    await seed_charge_types(session, tenant_id)
    await session.flush()


async def _upsert_document_sequences(session: AsyncSession, tenant_id: UUID) -> None:
    """Insert missing canonical sequences; restore prefix/padding without resetting counters."""

    config = await FiscalYearConfig.load(session, tenant_id)
    fiscal_year = config.year_for(datetime.now(UTC).date())
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


def _deleted_chart_account(rows: list[Account], code: str) -> Account | None:
    """Prefer the latest soft-deleted system row for a chart code."""

    deleted = [row for row in rows if row.code == code and row.deleted_at is not None]
    if not deleted:
        return None
    system = [row for row in deleted if row.is_system]
    pool = system or deleted
    return max(pool, key=lambda row: row.deleted_at or datetime.min.replace(tzinfo=UTC))


async def _ensure_chart_of_accounts(session: AsyncSession, tenant_id: UUID) -> None:
    """Insert missing UAE chart rows, or restore the soft-deleted row for that code."""

    existing = list(
        (await session.execute(select(Account).where(Account.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    by_code = {row.code: row for row in existing if row.deleted_at is None}
    mapped_roles = {row.system_role for row in by_code.values() if row.system_role}
    for row in UAE_CHART:
        role_value = None if row.system_role is None else row.system_role.value
        account = by_code.get(row.code)
        if account is None:
            deleted = _deleted_chart_account(existing, row.code)
            if deleted is not None:
                if deleted.system_role is not None and deleted.system_role in mapped_roles:
                    deleted.system_role = None
                elif (
                    role_value is not None
                    and deleted.system_role is None
                    and role_value not in mapped_roles
                ):
                    deleted.system_role = role_value
                    deleted.is_system = True
                deleted.deleted_at = None
                deleted.is_active = True
                if deleted.system_role is not None:
                    mapped_roles.add(deleted.system_role)
                by_code[row.code] = deleted
                continue
            if role_value is not None and role_value in mapped_roles:
                role_value = None
            parent = by_code.get(row.parent_code) if row.parent_code else None
            depth = 0 if parent is None else parent.depth + 1
            account = Account(
                tenant_id=tenant_id,
                code=row.code,
                name=row.name,
                account_type=row.account_type.value,
                account_subtype=row.account_subtype.value,
                parent_id=None if parent is None else parent.id,
                depth=depth,
                is_group=row.is_group,
                is_system=True,
                system_role=role_value,
            )
            session.add(account)
            await session.flush()
            existing.append(account)
            by_code[row.code] = account
            if role_value is not None:
                mapped_roles.add(role_value)
            continue
        if role_value is None or role_value in mapped_roles or account.system_role is not None:
            continue
        account.system_role = role_value
        account.is_system = True
        mapped_roles.add(role_value)


async def seed_chart_of_accounts(session: AsyncSession, tenant_id: UUID) -> None:
    """Ensure the UAE default chart exists for a new or existing tenant."""

    await _ensure_chart_of_accounts(session, tenant_id)


async def reconcile_chart_of_accounts(session: AsyncSession, tenant_id: UUID) -> None:
    """Restore or insert missing seeded rows and map unmapped system roles."""

    await _ensure_chart_of_accounts(session, tenant_id)
