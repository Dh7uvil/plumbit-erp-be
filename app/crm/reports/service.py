"""Read-only CRM report aggregates."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.org_service import OrganizationService
from app.common.utils.currency import quantize_money
from app.common.utils.datetime import today_in_timezone, utcnow
from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.crm.pipelines.models import Pipeline
from app.crm.reports.constants import (
    ACTIVITY_GROUPS,
    DEFAULT_ACTIVITY_GROUP,
    DEFAULT_LEAD_CONVERSION_GROUP,
    DEFAULT_PIPELINE_GROUP,
    DEFAULT_WIN_LOSS_GROUP,
    LEAD_CONVERSION_GROUPS,
    PIPELINE_GROUPS,
    WIN_LOSS_GROUPS,
)
from app.crm.reports.repository import (
    CrmReportRepository,
    _as_int,
    _optional_decimal,
    bound_rows,
    percent_of,
)
from app.crm.reports.schemas import (
    CrmDashboardResponse,
    LeadConversionLine,
    LeadConversionResponse,
    SalesActivityLine,
    SalesActivityResponse,
    SalesFunnelLine,
    SalesFunnelResponse,
    SalesPipelineLine,
    SalesPipelineResponse,
    WinLossLine,
    WinLossResponse,
)
from app.erp.exchange_rates.service import CurrencyService

_ZERO = Decimal("0")


class CrmReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CrmReportRepository(session)
        self.currencies = CurrencyService(session)

    async def sales_pipeline(
        self,
        tenant_id: UUID,
        *,
        group_by: str = DEFAULT_PIPELINE_GROUP,
        pipeline_id: UUID | None = None,
    ) -> SalesPipelineResponse:
        grouping = self._require_group(group_by, PIPELINE_GROUPS, field="group_by")
        if pipeline_id is not None:
            await self._require_pipeline(tenant_id, pipeline_id)
        rows, truncated = bound_rows(
            await self.repo.pipeline_aggregates(
                tenant_id, group_by=grouping, pipeline_id=pipeline_id
            )
        )
        lines = [
            SalesPipelineLine(
                group_key=str(row["group_key"]),
                group_label=str(row["group_label"]),
                opportunity_count=_as_int(row["opportunity_count"]),
                amount=quantize_money(Decimal(str(row["amount"]))),
                weighted_amount=quantize_money(Decimal(str(row["weighted_amount"]))),
            )
            for row in rows
        ]
        return SalesPipelineResponse(
            currency_code=await self._currency_code(tenant_id),
            group_by=grouping,
            pipeline_id=pipeline_id,
            opportunity_count=sum(line.opportunity_count for line in lines),
            total_amount=quantize_money(sum((line.amount for line in lines), _ZERO)),
            total_weighted_amount=quantize_money(
                sum((line.weighted_amount for line in lines), _ZERO)
            ),
            truncated=truncated,
            lines=lines,
        )

    async def sales_funnel(
        self, tenant_id: UUID, *, pipeline_id: UUID | None = None
    ) -> SalesFunnelResponse:
        pipeline = (
            await self._require_pipeline(tenant_id, pipeline_id)
            if pipeline_id is not None
            else await self.repo.default_pipeline(tenant_id)
        )
        if pipeline is None:
            raise ValidationError("No default pipeline is configured")
        stages = await self.repo.stages_for_pipeline(tenant_id, pipeline.id)
        aggregates = await self.repo.funnel_aggregates(tenant_id, pipeline.id)
        lines: list[SalesFunnelLine] = []
        previous_count: int | None = None
        for stage in stages:
            stats = aggregates.get(stage.id, {})
            count = int(stats.get("opportunity_count", 0))
            amount = quantize_money(Decimal(str(stats.get("amount", _ZERO))))
            weighted = quantize_money(Decimal(str(stats.get("weighted_amount", _ZERO))))
            conversion = None if previous_count is None else percent_of(count, previous_count)
            lines.append(
                SalesFunnelLine(
                    stage_id=stage.id,
                    stage_name=stage.name,
                    sort_order=stage.sort_order,
                    stage_kind=stage.stage_kind,
                    opportunity_count=count,
                    amount=amount,
                    weighted_amount=weighted,
                    conversion_percent=conversion,
                )
            )
            previous_count = count
        return SalesFunnelResponse(
            currency_code=await self._currency_code(tenant_id),
            pipeline_id=pipeline.id,
            pipeline_name=pipeline.name,
            opportunity_count=sum(line.opportunity_count for line in lines),
            total_amount=quantize_money(sum((line.amount for line in lines), _ZERO)),
            total_weighted_amount=quantize_money(
                sum((line.weighted_amount for line in lines), _ZERO)
            ),
            lines=lines,
        )

    async def win_loss(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        group_by: str = DEFAULT_WIN_LOSS_GROUP,
    ) -> WinLossResponse:
        self._require_range(from_date, to_date)
        grouping = self._require_group(group_by, WIN_LOSS_GROUPS, field="group_by")
        rows, truncated = bound_rows(
            await self.repo.win_loss_aggregates(
                tenant_id, group_by=grouping, from_date=from_date, to_date=to_date
            )
        )
        lines = [
            WinLossLine(
                group_key=str(row["group_key"]),
                group_label=str(row["group_label"]),
                won_count=_as_int(row["won_count"]),
                lost_count=_as_int(row["lost_count"]),
                won_amount=quantize_money(Decimal(str(row["won_amount"]))),
                lost_amount=quantize_money(Decimal(str(row["lost_amount"]))),
                win_percent=_optional_decimal(row["win_percent"]),
            )
            for row in rows
        ]
        won_count = sum(line.won_count for line in lines)
        lost_count = sum(line.lost_count for line in lines)
        return WinLossResponse(
            currency_code=await self._currency_code(tenant_id),
            from_date=from_date,
            to_date=to_date,
            group_by=grouping,
            won_count=won_count,
            lost_count=lost_count,
            won_amount=quantize_money(sum((line.won_amount for line in lines), _ZERO)),
            lost_amount=quantize_money(sum((line.lost_amount for line in lines), _ZERO)),
            win_percent=percent_of(won_count, won_count + lost_count),
            truncated=truncated,
            lines=lines,
        )

    async def lead_conversion(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        group_by: str = DEFAULT_LEAD_CONVERSION_GROUP,
    ) -> LeadConversionResponse:
        self._require_range(from_date, to_date)
        grouping = self._require_group(group_by, LEAD_CONVERSION_GROUPS, field="group_by")
        rows, truncated = bound_rows(
            await self.repo.lead_conversion_aggregates(
                tenant_id, group_by=grouping, from_date=from_date, to_date=to_date
            )
        )
        lines = [
            LeadConversionLine(
                group_key=str(row["group_key"]),
                group_label=str(row["group_label"]),
                lead_count=_as_int(row["lead_count"]),
                converted_count=_as_int(row["converted_count"]),
                conversion_percent=_optional_decimal(row["conversion_percent"]),
            )
            for row in rows
        ]
        lead_count = sum(line.lead_count for line in lines)
        converted_count = sum(line.converted_count for line in lines)
        return LeadConversionResponse(
            from_date=from_date,
            to_date=to_date,
            group_by=grouping,
            lead_count=lead_count,
            converted_count=converted_count,
            conversion_percent=percent_of(converted_count, lead_count),
            truncated=truncated,
            lines=lines,
        )

    async def sales_activity(
        self,
        tenant_id: UUID,
        *,
        from_date: date,
        to_date: date,
        group_by: str = DEFAULT_ACTIVITY_GROUP,
    ) -> SalesActivityResponse:
        self._require_range(from_date, to_date)
        grouping = self._require_group(group_by, ACTIVITY_GROUPS, field="group_by")
        rows, truncated = bound_rows(
            await self.repo.activity_aggregates(
                tenant_id,
                group_by=grouping,
                from_date=from_date,
                to_date=to_date,
                now=utcnow(),
            )
        )
        lines = [
            SalesActivityLine(
                group_key=str(row["group_key"]),
                group_label=str(row["group_label"]),
                activity_count=_as_int(row["activity_count"]),
                open_count=_as_int(row["open_count"]),
                completed_count=_as_int(row["completed_count"]),
                overdue_count=_as_int(row["overdue_count"]),
            )
            for row in rows
        ]
        return SalesActivityResponse(
            from_date=from_date,
            to_date=to_date,
            group_by=grouping,
            activity_count=sum(line.activity_count for line in lines),
            open_count=sum(line.open_count for line in lines),
            completed_count=sum(line.completed_count for line in lines),
            overdue_count=sum(line.overdue_count for line in lines),
            truncated=truncated,
            lines=lines,
        )

    async def dashboard(self, tenant_id: UUID) -> CrmDashboardResponse:
        timezone = await OrganizationService(self.session).get_timezone(tenant_id)
        today = today_in_timezone(timezone)
        month_start = today.replace(day=1)
        if today.month == 12:
            next_month = date(today.year + 1, 1, 1)
        else:
            next_month = date(today.year, today.month + 1, 1)
        totals = await self.repo.dashboard_totals(
            tenant_id, month_start=month_start, month_end=next_month, now=utcnow()
        )
        return CrmDashboardResponse(
            currency_code=await self._currency_code(tenant_id),
            as_of=today,
            open_pipeline_count=_as_int(totals["open_pipeline_count"]),
            open_pipeline_value=quantize_money(Decimal(str(totals["open_pipeline_value"]))),
            closing_this_month_count=_as_int(totals["closing_this_month_count"]),
            closing_this_month_value=quantize_money(
                Decimal(str(totals["closing_this_month_value"]))
            ),
            overdue_activity_count=_as_int(totals["overdue_activity_count"]),
        )

    async def _currency_code(self, tenant_id: UUID) -> str:
        return (await self.currencies.get_base(tenant_id)).code

    async def _require_pipeline(self, tenant_id: UUID, pipeline_id: UUID) -> Pipeline:
        pipeline = await self.repo.get_pipeline(tenant_id, pipeline_id)
        if pipeline is None:
            raise ResourceNotFoundError("Pipeline not found")
        return pipeline

    def _require_range(self, from_date: date, to_date: date) -> None:
        if from_date > to_date:
            raise ValidationError("from_date must be on or before to_date")

    def _require_group(self, group_by: str, allowed: frozenset[str], *, field: str) -> str:
        if group_by not in allowed:
            raise ValidationError("Invalid report grouping", details={field: group_by})
        return group_by
