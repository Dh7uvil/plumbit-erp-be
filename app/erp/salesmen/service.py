"""Salesman targets and performance."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Employee, User
from app.common.utils.currency import quantize_money
from app.core.enums import EmployeeStatus, InvoiceDocumentStatus
from app.core.exceptions import ResourceNotFoundError
from app.db.session import transaction
from app.erp.accounting.fiscal import FiscalYearConfig
from app.erp.sales_invoices.models import SalesInvoice
from app.erp.salesmen.models import SalesTarget
from app.erp.salesmen.schemas import (
    SalesmanOverviewRow,
    SalesmanPeriodAmount,
    SalesmanTargetsUpdate,
)


class SalesmanService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_overview(
        self, tenant_id: UUID, *, fiscal_year: int | None = None
    ) -> list[SalesmanOverviewRow]:
        config = await FiscalYearConfig.load(self.session, tenant_id)
        year = fiscal_year if fiscal_year is not None else config.year_for(date.today())
        period_ranges = config.period_bounds(year)

        employees = (
            await self.session.execute(
                select(Employee, User.name)
                .outerjoin(
                    User,
                    (User.id == Employee.user_id) & (User.tenant_id == tenant_id),
                )
                .where(
                    Employee.tenant_id == tenant_id,
                    Employee.deleted_at.is_(None),
                    Employee.status == EmployeeStatus.ACTIVE.value,
                )
                .order_by(Employee.employee_code)
            )
        ).all()

        target_rows = (
            await self.session.execute(
                select(SalesTarget).where(
                    SalesTarget.tenant_id == tenant_id,
                    SalesTarget.fiscal_year == year,
                )
            )
        ).scalars().all()
        targets: dict[tuple[UUID, int], Decimal] = {
            (row.employee_id, row.period): Decimal(row.amount) for row in target_rows
        }

        actuals: dict[tuple[UUID, int], Decimal] = {}
        for period, start, end in period_ranges:
            statement = (
                select(SalesInvoice.salesperson_id, func.coalesce(func.sum(SalesInvoice.base_amount), 0))
                .where(
                    SalesInvoice.tenant_id == tenant_id,
                    SalesInvoice.deleted_at.is_(None),
                    SalesInvoice.status == InvoiceDocumentStatus.POSTED.value,
                    SalesInvoice.salesperson_id.is_not(None),
                    SalesInvoice.invoice_date >= start,
                    SalesInvoice.invoice_date <= end,
                )
                .group_by(SalesInvoice.salesperson_id)
            )
            for employee_id, total in (await self.session.execute(statement)).all():
                if employee_id is not None:
                    actuals[(employee_id, period)] = quantize_money(Decimal(total))

        overview: list[SalesmanOverviewRow] = []
        for employee, user_name in employees:
            periods: list[SalesmanPeriodAmount] = []
            target_total = Decimal("0")
            actual_total = Decimal("0")
            for period, _, _ in period_ranges:
                target = quantize_money(targets.get((employee.id, period), Decimal("0")))
                actual = quantize_money(actuals.get((employee.id, period), Decimal("0")))
                periods.append(
                    SalesmanPeriodAmount(period=period, target=target, actual=actual)
                )
                target_total += target
                actual_total += actual
            overview.append(
                SalesmanOverviewRow(
                    employee_id=employee.id,
                    employee_code=employee.employee_code,
                    name=user_name or employee.employee_code,
                    designation=employee.designation,
                    fiscal_year=year,
                    periods=periods,
                    target_total=quantize_money(target_total),
                    actual_total=quantize_money(actual_total),
                )
            )
        return overview

    async def update_targets(
        self,
        tenant_id: UUID,
        employee_id: UUID,
        payload: SalesmanTargetsUpdate,
    ) -> SalesmanOverviewRow:
        employee = await self.session.get(Employee, employee_id)
        if employee is None or employee.tenant_id != tenant_id or employee.deleted_at is not None:
            raise ResourceNotFoundError("Employee not found")
        async with transaction(self.session):
            for item in payload.periods:
                existing = (
                    await self.session.execute(
                        select(SalesTarget).where(
                            SalesTarget.tenant_id == tenant_id,
                            SalesTarget.employee_id == employee_id,
                            SalesTarget.fiscal_year == payload.fiscal_year,
                            SalesTarget.period == item.period,
                        )
                    )
                ).scalar_one_or_none()
                amount = quantize_money(item.target)
                if existing is None:
                    self.session.add(
                        SalesTarget(
                            tenant_id=tenant_id,
                            employee_id=employee_id,
                            fiscal_year=payload.fiscal_year,
                            period=item.period,
                            amount=amount,
                        )
                    )
                else:
                    existing.amount = amount
        rows = await self.list_overview(tenant_id, fiscal_year=payload.fiscal_year)
        match = next((row for row in rows if row.employee_id == employee_id), None)
        if match is None:
            raise ResourceNotFoundError("Employee not found")
        return match
