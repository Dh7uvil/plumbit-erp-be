"""Compact document number formatting: PREFIX + party + YY + sequence."""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundError
from app.crm.customers.models import Customer

PARTY_DOCUMENT_TYPES = frozenset(
    {
        "QUOTATION",
        "SALES_ORDER",
        "PROFORMA_INVOICE",
        "SALES_INVOICE",
        "CREDIT_NOTE",
        "CUSTOMER_PAYMENT",
        "DELIVERY_NOTE",
        "SALES_RETURN",
        "PACKAGE",
        "PURCHASE_ORDER",
        "GOODS_RECEIPT",
        "PURCHASE_INVOICE",
        "DEBIT_NOTE",
        "SUPPLIER_PAYMENT",
        "PURCHASE_RETURN",
        "QUALITY_INSPECTION",
        "LANDED_COST",
    }
)
OLD_NUMBER_PATTERN = re.compile(r"^([A-Z]+)-(\d{4})-(\d+)$")


def format_document_number(
    *,
    prefix: str,
    party_code: str | None,
    fiscal_year: int,
    number: int,
    padding: int,
) -> str:
    """Return ``SOAGM26000006`` or ``JV26000001`` when there is no party."""

    yy = f"{fiscal_year % 100:02d}"
    seq = str(number).zfill(padding)
    return f"{prefix}{party_code or ''}{yy}{seq}"


def document_type_embeds_party(document_type: str) -> bool:
    """Return whether this document type includes a 3-letter party code."""

    return document_type in PARTY_DOCUMENT_TYPES


def parse_old_document_number(value: str) -> tuple[str, int, int] | None:
    """Return ``(prefix, fiscal_year, sequence)`` for hyphenated legacy numbers."""

    match = OLD_NUMBER_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def parse_compact_sequence(value: str, *, prefix: str, has_party: bool) -> int | None:
    """Return the integer sequence from a compact number, or ``None`` if malformed."""

    if not value.startswith(prefix):
        return None
    rest = value[len(prefix) :]
    if has_party:
        if len(rest) < 5:
            return None
        rest = rest[3:]
    if len(rest) < 3:
        return None
    seq = rest[2:]
    return int(seq) if seq.isdigit() else None


async def party_code_for(session: AsyncSession, tenant_id: UUID, party_id: UUID) -> str:
    """Load the active party code for a customer or supplier id."""

    statement = select(Customer.code).where(
        Customer.tenant_id == tenant_id,
        Customer.id == party_id,
        Customer.deleted_at.is_(None),
    )
    result = await session.execute(statement)
    code = result.scalar_one_or_none()
    if code is None:
        raise ResourceNotFoundError("Customer not found")
    return code
