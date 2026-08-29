"""Common catalog data shared by every tenant.

ISO 4217 currencies are inserted idempotently. AED is the sole base on insert;
existing ``is_base`` flags are never flipped. Used at tenant creation and by
``uv run seed-tenants`` to backfill orgs that were provisioned with a smaller set.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Tenant
from app.erp.exchange_rates.catalog import BASE_CURRENCY_CODE, ISO_4217_CURRENCIES
from app.erp.exchange_rates.models import Currency


async def seed_common_data(session: AsyncSession, tenant_id: UUID) -> int:
    """Insert missing ISO currencies and set the tenant default to AED if empty.

    Returns the number of currency rows inserted.
    """

    existing_result = await session.execute(
        select(Currency.code).where(
            Currency.tenant_id == tenant_id,
            Currency.deleted_at.is_(None),
        )
    )
    existing_codes = set(existing_result.scalars().all())
    inserted = 0
    for entry in ISO_4217_CURRENCIES:
        if entry.code in existing_codes:
            continue
        session.add(
            Currency(
                tenant_id=tenant_id,
                code=entry.code,
                name=entry.name,
                symbol=entry.symbol,
                decimal_places=entry.decimal_places,
                is_base=entry.code == BASE_CURRENCY_CODE,
            )
        )
        inserted += 1
    await session.flush()

    tenant = await session.get(Tenant, tenant_id)
    if tenant is not None and tenant.default_currency_id is None:
        aed_result = await session.execute(
            select(Currency.id).where(
                Currency.tenant_id == tenant_id,
                Currency.code == BASE_CURRENCY_CODE,
                Currency.deleted_at.is_(None),
            )
        )
        aed_id = aed_result.scalar_one_or_none()
        if aed_id is not None:
            tenant.default_currency_id = aed_id
            settings = dict(tenant.settings or {})
            settings.setdefault("default_currency", BASE_CURRENCY_CODE)
            tenant.settings = settings

    return inserted
