"""Dunning persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.core.enums import InvoiceDocumentStatus
from app.erp.accounting.dunning.models import DunningLog, DunningRule
from app.erp.sales_invoices.models import SalesInvoice


class DunningRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._repo = BaseRepository(
            session,
            DunningRule,
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "name", "days_offset", "is_active"}
            ),
            allowed_filter_fields=frozenset({"is_active"}),
            search_fields=frozenset({"name", "description"}),
        )

    async def get(self, tenant_id: UUID, rule_id: UUID) -> DunningRule | None:
        return await self._repo.get(tenant_id, rule_id)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[DunningRule], int]:
        return await self._repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters
        )

    async def list_active(self, tenant_id: UUID) -> Sequence[DunningRule]:
        stmt = (
            select(DunningRule)
            .where(
                DunningRule.tenant_id == tenant_id,
                DunningRule.deleted_at.is_(None),
                DunningRule.is_active.is_(True),
            )
            .order_by(DunningRule.days_offset.asc(), DunningRule.name.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> DunningRule:
        return await self._repo.create(tenant_id, values)

    async def update(
        self, tenant_id: UUID, rule_id: UUID, values: Mapping[str, object]
    ) -> DunningRule | None:
        return await self._repo.update(tenant_id, rule_id, values)

    async def soft_delete(self, tenant_id: UUID, rule_id: UUID) -> DunningRule | None:
        return await self._repo.soft_delete(tenant_id, rule_id)


class DunningLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_invoice_rule(
        self, tenant_id: UUID, *, sales_invoice_id: UUID, dunning_rule_id: UUID
    ) -> DunningLog | None:
        stmt = select(DunningLog).where(
            DunningLog.tenant_id == tenant_id,
            DunningLog.sales_invoice_id == sales_invoice_id,
            DunningLog.dunning_rule_id == dunning_rule_id,
        )
        return await self.session.scalar(stmt)

    async def list_for_invoice(
        self, tenant_id: UUID, sales_invoice_id: UUID
    ) -> Sequence[tuple[DunningLog, DunningRule | None]]:
        rule = aliased(DunningRule)
        stmt: Select[tuple[DunningLog, DunningRule | None]] = (
            select(DunningLog, rule)
            .outerjoin(
                rule,
                and_(
                    rule.id == DunningLog.dunning_rule_id,
                    rule.tenant_id == DunningLog.tenant_id,
                ),
            )
            .where(
                DunningLog.tenant_id == tenant_id,
                DunningLog.sales_invoice_id == sales_invoice_id,
            )
            .order_by(DunningLog.sent_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.all()

    async def create(self, tenant_id: UUID, values: Mapping[str, object]) -> DunningLog:
        row = DunningLog(tenant_id=tenant_id, **dict(values))
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def invoices_due_for_rule(
        self,
        tenant_id: UUID,
        *,
        target_due_date: date,
    ) -> Sequence[SalesInvoice]:
        stmt = select(SalesInvoice).where(
            SalesInvoice.tenant_id == tenant_id,
            SalesInvoice.deleted_at.is_(None),
            SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
            SalesInvoice.due_date == target_due_date,
            SalesInvoice.balance_due > Decimal("0"),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
