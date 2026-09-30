"""Fiscal-year resolution. Defaults of 1 January keep existing numbering identical."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import PERIOD_OVERRIDE
from app.auth.models import Tenant
from app.core.exceptions import FiscalYearLockedError, ResourceNotFoundError
from app.core.permissions import has_permission
from app.erp.accounting.models import DocumentSequence

_CACHE_KEY = "fiscal_year_config"


def _clamp_day(year: int, month: int, day: int) -> date:
    last = monthrange(year, month)[1]
    return date(year, month, min(day, last))


@dataclass(frozen=True, slots=True)
class FiscalYearConfig:
    start_month: int = 1
    start_day: int = 1

    def year_for(self, document_date: date) -> int:
        """Return the fiscal year that contains ``document_date``.

        With the 1 January default this is ``document_date.year``.
        """

        start = _clamp_day(document_date.year, self.start_month, self.start_day)
        if document_date >= start:
            return document_date.year
        return document_date.year - 1

    def bounds(self, fiscal_year: int) -> tuple[date, date]:
        start = _clamp_day(fiscal_year, self.start_month, self.start_day)
        end = _clamp_day(fiscal_year + 1, self.start_month, self.start_day) - timedelta(days=1)
        return start, end

    def period_bounds(self, fiscal_year: int) -> list[tuple[int, date, date]]:
        """Return fiscal periods 1–12 as ``(period, start, end)`` within the year."""

        fy_start, fy_end = self.bounds(fiscal_year)
        periods: list[tuple[int, date, date]] = []
        cursor = fy_start
        for period in range(1, 13):
            if period == 12:
                period_end = fy_end
            else:
                next_month = cursor.month + 1
                next_year = cursor.year
                if next_month > 12:
                    next_month = 1
                    next_year += 1
                next_start = _clamp_day(next_year, next_month, self.start_day)
                period_end = next_start - timedelta(days=1)
            periods.append((period, cursor, period_end))
            cursor = period_end + timedelta(days=1)
        return periods

    def fiscal_period_for(self, document_date: date) -> int:
        """Return the 1–12 fiscal period that contains ``document_date``."""

        fiscal_year = self.year_for(document_date)
        for period, start, end in self.period_bounds(fiscal_year):
            if start <= document_date <= end:
                return period
        return 12

    @classmethod
    async def load(cls, session: AsyncSession, tenant_id: UUID) -> FiscalYearConfig:
        cache: dict[UUID, FiscalYearConfig] = session.sync_session.info.setdefault(_CACHE_KEY, {})
        cached = cache.get(tenant_id)
        if cached is not None:
            return cached
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise ResourceNotFoundError("Tenant not found")
        config = cls(
            start_month=int(tenant.fiscal_year_start_month),
            start_day=int(tenant.fiscal_year_start_day),
        )
        cache[tenant_id] = config
        return config


async def year_for(session: AsyncSession, tenant_id: UUID, document_date: date) -> int:
    """Resolve the fiscal year for a document date. Byte-identical to ``.year`` at 1/1."""

    config = await FiscalYearConfig.load(session, tenant_id)
    return config.year_for(document_date)


async def sequences_have_been_issued(session: AsyncSession, tenant_id: UUID) -> bool:
    statement = (
        select(DocumentSequence.id)
        .where(
            DocumentSequence.tenant_id == tenant_id,
            DocumentSequence.deleted_at.is_(None),
            DocumentSequence.next_number > 1,
        )
        .limit(1)
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None


async def assert_start_change_allowed(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    current_month: int,
    current_day: int,
    new_month: int,
    new_day: int,
    actor_permissions: frozenset[str],
    acknowledged: bool,
) -> None:
    """Refuse a fiscal-start change after numbering has started, unless overridden."""

    if (new_month, new_day) == (current_month, current_day):
        return
    if not await sequences_have_been_issued(session, tenant_id):
        return
    if has_permission(actor_permissions, PERIOD_OVERRIDE) and acknowledged:
        return
    raise FiscalYearLockedError(
        details={
            "requires_acknowledgement": True,
            "requires_override": True,
        }
    )
