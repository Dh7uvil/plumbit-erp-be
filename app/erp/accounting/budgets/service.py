"""Budget use cases. No ledger posting."""

from __future__ import annotations

from builtins import list as _List
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import ACCOUNTING_MODULE
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.common.utils.currency import quantize_money
from app.core.enums import AuditAction, BudgetStatus
from app.core.exceptions import DocumentStaleError, ResourceNotFoundError, ValidationError
from app.db.session import transaction
from app.erp.accounting.accounts.service import AccountService
from app.erp.accounting.budgets.models import Budget, BudgetLine
from app.erp.accounting.budgets.repository import BudgetRepository
from app.erp.accounting.budgets.schemas import (
    BudgetCreate,
    BudgetLineInput,
    BudgetLineResponse,
    BudgetResponse,
    BudgetUpdate,
    BudgetVsActualLine,
    BudgetVsActualResponse,
)
from app.auth.org_service import OrganizationService
from app.core.enums import AccountType
from app.erp.accounting.cost_centers.service import CostCenterService
from app.erp.exchange_rates.service import CurrencyService

_ZERO = Decimal("0")


def month_start(value: date) -> date:
    return value.replace(day=1)


def month_end(value: date) -> date:
    start = month_start(value)
    if start.month == 12:
        return date(start.year, 12, 31)
    return date(start.year, start.month + 1, 1) - timedelta(days=1)


def _actions(status: str) -> _List[str]:
    if status == BudgetStatus.DRAFT.value:
        return ["update", "delete", "activate"]
    if status == BudgetStatus.ACTIVE.value:
        return ["close"]
    return []


class BudgetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BudgetRepository(session)
        self.accounts = AccountService(session)
        self.cost_centers = CostCenterService(session)
        self.currencies = CurrencyService(session)
        self.org = OrganizationService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        fiscal_year: int | None = None,
    ) -> tuple[_List[BudgetResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if fiscal_year is not None:
            filters["fiscal_year"] = fiscal_year
        rows, total = await self.repo.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters or None,
        )
        responses: _List[BudgetResponse] = []
        for row in rows:
            responses.append(await self._response(tenant_id, row, include_lines=False))
        return responses, total

    async def get(self, tenant_id: UUID, budget_id: UUID) -> BudgetResponse:
        return await self._response(tenant_id, await self._require(tenant_id, budget_id))

    async def amounts_by_account(
        self,
        tenant_id: UUID,
        budget_id: UUID,
        *,
        from_date: date,
        to_date: date,
        cost_center_id: UUID | None = None,
        branch_id: UUID | None = None,
    ) -> dict[UUID, Decimal]:
        row = await self._require(tenant_id, budget_id)
        if row.status == BudgetStatus.DRAFT.value:
            return {}
        totals: dict[UUID, Decimal] = {}
        for line in await self.repo.lines_for(tenant_id, budget_id):
            if line.period_start < month_start(from_date) or line.period_start > to_date:
                continue
            if cost_center_id is not None:
                if line.cost_center_id is None or line.cost_center_id != cost_center_id:
                    continue
            if branch_id is not None:
                if line.branch_id is None or line.branch_id != branch_id:
                    continue
            totals[line.account_id] = quantize_money(
                totals.get(line.account_id, _ZERO) + line.amount
            )
        return totals

    async def create(
        self, tenant_id: UUID, payload: BudgetCreate, *, actor_user_id: UUID
    ) -> BudgetResponse:
        async with transaction(self.session):
            prepared = await self._prepare_lines(tenant_id, payload.lines)
            row = await self.repo.create(
                tenant_id,
                {
                    "name": payload.name,
                    "fiscal_year": payload.fiscal_year,
                    "status": BudgetStatus.DRAFT.value,
                    "version": 1,
                    "notes": payload.notes,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            if prepared:
                await self.repo.replace_lines(tenant_id, row.id, prepared)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=ACCOUNTING_MODULE,
                entity_type="budget",
                entity_id=row.id,
                new_values={"name": row.name, "fiscal_year": row.fiscal_year},
            )
            return await self._response(tenant_id, row)

    async def update(
        self,
        tenant_id: UUID,
        budget_id: UUID,
        payload: BudgetUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> BudgetResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, budget_id, for_update=True)
            self._assert_version(row, expected_version)
            if row.status != BudgetStatus.DRAFT.value:
                raise ValidationError("Only draft budgets can be edited")
            values: dict[str, object] = {"updated_by": actor_user_id, "version": row.version + 1}
            if payload.name is not None:
                values["name"] = payload.name
            if payload.notes is not None:
                values["notes"] = payload.notes
            updated = await self.repo.update(tenant_id, budget_id, values)
            if updated is None:
                raise ResourceNotFoundError("Budget not found")
            if payload.lines is not None:
                prepared = await self._prepare_lines(tenant_id, payload.lines)
                await self.repo.replace_lines(tenant_id, budget_id, prepared)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=ACCOUNTING_MODULE,
                entity_type="budget",
                entity_id=budget_id,
                new_values={"name": updated.name},
            )
            return await self._response(tenant_id, updated)

    async def delete(
        self, tenant_id: UUID, budget_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> BudgetResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, budget_id, for_update=True)
            self._assert_version(row, expected_version)
            if row.status != BudgetStatus.DRAFT.value:
                raise ValidationError("Only draft budgets can be deleted")
            response = await self._response(tenant_id, row)
            deleted = await self.repo.soft_delete(tenant_id, budget_id)
            if deleted is None:
                raise ResourceNotFoundError("Budget not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=ACCOUNTING_MODULE,
                entity_type="budget",
                entity_id=budget_id,
                old_values={"name": row.name},
            )
            return response

    async def activate(
        self, tenant_id: UUID, budget_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> BudgetResponse:
        return await self._transition(
            tenant_id,
            budget_id,
            actor_user_id=actor_user_id,
            expected_version=expected_version,
            target=BudgetStatus.ACTIVE,
            action=AuditAction.CONFIRM,
        )

    async def close(
        self, tenant_id: UUID, budget_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> BudgetResponse:
        return await self._transition(
            tenant_id,
            budget_id,
            actor_user_id=actor_user_id,
            expected_version=expected_version,
            target=BudgetStatus.CLOSED,
            action=AuditAction.CLOSE,
        )

    async def _transition(
        self,
        tenant_id: UUID,
        budget_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
        target: BudgetStatus,
        action: AuditAction,
    ) -> BudgetResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, budget_id, for_update=True)
            self._assert_version(row, expected_version)
            if target == BudgetStatus.ACTIVE and row.status != BudgetStatus.DRAFT.value:
                raise ValidationError("Only a draft budget can be activated")
            if target == BudgetStatus.CLOSED and row.status != BudgetStatus.ACTIVE.value:
                raise ValidationError("Only an active budget can be closed")
            if target == BudgetStatus.ACTIVE and not await self.repo.lines_for(
                tenant_id, budget_id
            ):
                raise ValidationError("Add at least one budget line before activating")
            if target == BudgetStatus.ACTIVE:
                existing = await self.repo.active_for_fiscal_year(tenant_id, row.fiscal_year)
                if existing is not None and existing.id != budget_id:
                    raise ValidationError(
                        "Only one active budget is allowed per fiscal year"
                    )
            updated = await self.repo.update(
                tenant_id,
                budget_id,
                {
                    "status": target.value,
                    "version": row.version + 1,
                    "updated_by": actor_user_id,
                },
            )
            if updated is None:
                raise ResourceNotFoundError("Budget not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=action,
                module=ACCOUNTING_MODULE,
                entity_type="budget",
                entity_id=budget_id,
                new_values={"status": target.value},
            )
            return await self._response(tenant_id, updated)

    async def _prepare_lines(
        self, tenant_id: UUID, lines: _List[BudgetLineInput]
    ) -> _List[dict[str, object]]:
        seen: set[tuple[UUID, date, UUID | None, UUID | None]] = set()
        prepared: _List[dict[str, object]] = []
        for line in lines:
            if line.amount == _ZERO:
                continue
            period = month_start(line.period_start)
            key = (line.account_id, period, line.cost_center_id, line.branch_id)
            if key in seen:
                raise ValidationError(
                    "Duplicate budget line for the same account, period, and dimension"
                )
            seen.add(key)
            await self.accounts.require_postable(tenant_id, line.account_id)
            if line.cost_center_id is not None:
                await self.cost_centers.require_id(tenant_id, line.cost_center_id)
            if line.branch_id is not None:
                branches = await self.org.get_branches_by_ids(tenant_id, [line.branch_id])
                if line.branch_id not in branches:
                    raise ValidationError("Branch not found")
            prepared.append(
                {
                    "account_id": line.account_id,
                    "period_start": period,
                    "amount": quantize_money(line.amount),
                    "cost_center_id": line.cost_center_id,
                    "branch_id": line.branch_id,
                }
            )
        return prepared

    async def _require(
        self, tenant_id: UUID, budget_id: UUID, *, for_update: bool = False
    ) -> Budget:
        row = await self.repo.get(tenant_id, budget_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Budget not found")
        return row

    def _assert_version(self, row: Budget, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={"expected_version": expected_version, "actual_version": row.version}
            )

    async def _response(
        self, tenant_id: UUID, row: Budget, *, include_lines: bool = True
    ) -> BudgetResponse:
        lines: _List[BudgetLine] = []
        if include_lines:
            lines = await self.repo.lines_for(tenant_id, row.id)
        response = BudgetResponse.model_validate(row)
        response.lines = [BudgetLineResponse.model_validate(line) for line in lines]
        response.available_actions = _actions(row.status)
        return response


def line_variance(budget_amount: Decimal, actual_amount: Decimal) -> Decimal:
    return quantize_money(actual_amount - budget_amount)


def empty_vs_actual(
    *,
    budget_id: UUID,
    budget_name: str,
    currency_code: str,
    from_date: date,
    to_date: date,
    lines: _List[BudgetVsActualLine],
) -> BudgetVsActualResponse:
    total_budget_income = _ZERO
    total_budget_expense = _ZERO
    total_actual_income = _ZERO
    total_actual_expense = _ZERO
    for line in lines:
        if line.account_type == AccountType.INCOME.value:
            total_budget_income += line.budget_amount
            total_actual_income += line.actual_amount
        else:
            total_budget_expense += line.budget_amount
            total_actual_expense += line.actual_amount
    total_budget_income = quantize_money(total_budget_income)
    total_budget_expense = quantize_money(total_budget_expense)
    total_actual_income = quantize_money(total_actual_income)
    total_actual_expense = quantize_money(total_actual_expense)
    total_budget = quantize_money(total_budget_income + total_budget_expense)
    total_actual = quantize_money(total_actual_income + total_actual_expense)
    return BudgetVsActualResponse(
        budget_id=budget_id,
        budget_name=budget_name,
        currency_code=currency_code,
        from_date=from_date,
        to_date=to_date,
        total_budget=total_budget,
        total_actual=total_actual,
        total_variance=line_variance(total_budget, total_actual),
        total_budget_income=total_budget_income,
        total_budget_expense=total_budget_expense,
        total_actual_income=total_actual_income,
        total_actual_expense=total_actual_expense,
        lines=lines,
    )
