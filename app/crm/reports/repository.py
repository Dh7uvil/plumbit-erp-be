"""SQL aggregations for CRM reports."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Date as SADate

from app.auth.models import User
from app.core.enums import ActivityStatus, LeadStatus, OpportunityStatus
from app.crm.activities.models import Activity
from app.crm.campaigns.models import Campaign
from app.crm.lead_sources.models import LeadSource
from app.crm.leads.models import Lead
from app.crm.lost_reasons.models import LostReason
from app.crm.opportunities.models import Opportunity
from app.crm.pipelines.models import Pipeline, PipelineStage
from app.crm.reports.constants import (
    REPORT_ROW_LIMIT,
    UNASSIGNED_KEY,
    UNASSIGNED_LABEL,
)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


def _as_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return _ZERO
    return Decimal(str(value))


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int(value)
    if value is None:
        return 0
    return int(str(value))


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return _as_decimal(value)


def percent_of(part: int | Decimal, whole: int | Decimal) -> Decimal | None:
    whole_dec = _as_decimal(whole)
    if whole_dec <= _ZERO:
        return None
    return (_as_decimal(part) * _HUNDRED / whole_dec).quantize(Decimal("0.0001"))


def bound_rows[T](rows: list[T], *, limit: int = REPORT_ROW_LIMIT) -> tuple[list[T], bool]:
    if len(rows) > limit:
        return rows[:limit], True
    return rows, False


class CrmReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def default_pipeline(self, tenant_id: UUID) -> Pipeline | None:
        result = await self.session.execute(
            select(Pipeline)
            .where(
                Pipeline.tenant_id == tenant_id,
                Pipeline.deleted_at.is_(None),
                Pipeline.is_default.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_pipeline(self, tenant_id: UUID, pipeline_id: UUID) -> Pipeline | None:
        result = await self.session.execute(
            select(Pipeline).where(
                Pipeline.tenant_id == tenant_id,
                Pipeline.id == pipeline_id,
                Pipeline.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def stages_for_pipeline(self, tenant_id: UUID, pipeline_id: UUID) -> list[PipelineStage]:
        result = await self.session.execute(
            select(PipelineStage)
            .where(
                PipelineStage.tenant_id == tenant_id,
                PipelineStage.pipeline_id == pipeline_id,
            )
            .order_by(PipelineStage.sort_order.asc(), PipelineStage.name.asc())
        )
        return list(result.scalars().all())

    async def pipeline_aggregates(
        self,
        tenant_id: UUID,
        *,
        group_by: str,
        pipeline_id: UUID | None,
    ) -> list[dict[str, object]]:
        amount = func.coalesce(Opportunity.amount, 0)
        probability = func.coalesce(Opportunity.probability, PipelineStage.probability, 0)
        weighted = amount * probability / 100
        group_col, label_col, order_col = self._pipeline_group_columns(group_by)
        criteria = [
            Opportunity.tenant_id == tenant_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.status == OpportunityStatus.OPEN.value,
        ]
        if pipeline_id is not None:
            criteria.append(Opportunity.pipeline_id == pipeline_id)
        statement = (
            select(
                group_col.label("group_key"),
                label_col.label("group_label"),
                Opportunity.currency_id.label("currency_id"),
                func.count().label("opportunity_count"),
                func.coalesce(func.sum(amount), 0).label("amount"),
                func.coalesce(func.sum(weighted), 0).label("weighted_amount"),
            )
            .select_from(Opportunity)
            .outerjoin(
                PipelineStage,
                and_(
                    PipelineStage.id == Opportunity.stage_id,
                    PipelineStage.tenant_id == Opportunity.tenant_id,
                ),
            )
            .outerjoin(
                User,
                and_(User.id == Opportunity.owner_id, User.tenant_id == Opportunity.tenant_id),
            )
            .outerjoin(
                LeadSource,
                and_(
                    LeadSource.id == Opportunity.source_id,
                    LeadSource.tenant_id == Opportunity.tenant_id,
                ),
            )
            .outerjoin(
                Campaign,
                and_(
                    Campaign.id == Opportunity.campaign_id,
                    Campaign.tenant_id == Opportunity.tenant_id,
                ),
            )
            .where(*criteria)
            .group_by(group_col, label_col, order_col, Opportunity.currency_id)
            .order_by(order_col, label_col)
            .limit(REPORT_ROW_LIMIT + 1)
        )
        rows = (await self.session.execute(statement)).all()
        return [self._pipeline_row(row) for row in rows]

    async def funnel_aggregates(
        self, tenant_id: UUID, pipeline_id: UUID
    ) -> dict[UUID, dict[str, Decimal | int]]:
        amount = func.coalesce(Opportunity.amount, 0)
        probability = func.coalesce(Opportunity.probability, PipelineStage.probability, 0)
        weighted = amount * probability / 100
        statement = (
            select(
                Opportunity.stage_id,
                Opportunity.currency_id,
                func.count().label("opportunity_count"),
                func.coalesce(func.sum(amount), 0).label("amount"),
                func.coalesce(func.sum(weighted), 0).label("weighted_amount"),
            )
            .select_from(Opportunity)
            .outerjoin(
                PipelineStage,
                and_(
                    PipelineStage.id == Opportunity.stage_id,
                    PipelineStage.tenant_id == Opportunity.tenant_id,
                ),
            )
            .where(
                Opportunity.tenant_id == tenant_id,
                Opportunity.deleted_at.is_(None),
                Opportunity.pipeline_id == pipeline_id,
            )
            .group_by(Opportunity.stage_id, Opportunity.currency_id)
        )
        rows = (await self.session.execute(statement)).all()
        StageBucket = dict[str, Decimal | int | list[tuple[UUID | None, Decimal, Decimal]]]
        merged: dict[UUID, StageBucket] = {}
        for row in rows:
            if row.stage_id is None:
                continue
            bucket = merged.setdefault(
                row.stage_id,
                {
                    "opportunity_count": 0,
                    "currency_slices": [],
                },
            )
            bucket["opportunity_count"] = _as_int(bucket["opportunity_count"]) + _as_int(
                row.opportunity_count
            )
            slices = bucket["currency_slices"]
            assert isinstance(slices, list)
            slices.append(
                (
                    row.currency_id,
                    _as_decimal(row.amount),
                    _as_decimal(row.weighted_amount),
                )
            )
        return merged

    async def win_loss_aggregates(
        self,
        tenant_id: UUID,
        *,
        group_by: str,
        from_date: date,
        to_date: date,
    ) -> list[dict[str, object]]:
        group_col, label_col, order_col = self._win_loss_group_columns(group_by)
        close_date = func.coalesce(
            Opportunity.expected_close_date, cast(Opportunity.updated_at, SADate)
        )
        won = Opportunity.status == OpportunityStatus.WON.value
        lost = Opportunity.status == OpportunityStatus.LOST.value
        statement = (
            select(
                group_col.label("group_key"),
                label_col.label("group_label"),
                Opportunity.currency_id.label("currency_id"),
                func.coalesce(func.sum(case((won, 1), else_=0)), 0).label("won_count"),
                func.coalesce(func.sum(case((lost, 1), else_=0)), 0).label("lost_count"),
                func.coalesce(
                    func.sum(case((won, func.coalesce(Opportunity.amount, 0)), else_=0)),
                    0,
                ).label("won_amount"),
                func.coalesce(
                    func.sum(case((lost, func.coalesce(Opportunity.amount, 0)), else_=0)),
                    0,
                ).label("lost_amount"),
            )
            .select_from(Opportunity)
            .outerjoin(
                User,
                and_(User.id == Opportunity.owner_id, User.tenant_id == Opportunity.tenant_id),
            )
            .outerjoin(
                LeadSource,
                and_(
                    LeadSource.id == Opportunity.source_id,
                    LeadSource.tenant_id == Opportunity.tenant_id,
                ),
            )
            .outerjoin(
                Campaign,
                and_(
                    Campaign.id == Opportunity.campaign_id,
                    Campaign.tenant_id == Opportunity.tenant_id,
                ),
            )
            .outerjoin(
                LostReason,
                and_(
                    LostReason.id == Opportunity.lost_reason_id,
                    LostReason.tenant_id == Opportunity.tenant_id,
                ),
            )
            .where(
                Opportunity.tenant_id == tenant_id,
                Opportunity.deleted_at.is_(None),
                Opportunity.status.in_((OpportunityStatus.WON.value, OpportunityStatus.LOST.value)),
                close_date >= from_date,
                close_date <= to_date,
            )
            .group_by(group_col, label_col, order_col, Opportunity.currency_id)
            .order_by(order_col, label_col)
            .limit(REPORT_ROW_LIMIT + 1)
        )
        rows = (await self.session.execute(statement)).all()
        result: list[dict[str, object]] = []
        for row in rows:
            won_count = _as_int(row.won_count)
            lost_count = _as_int(row.lost_count)
            result.append(
                {
                    "group_key": self._key(row.group_key),
                    "group_label": self._label(row.group_label),
                    "currency_id": row.currency_id,
                    "won_count": won_count,
                    "lost_count": lost_count,
                    "won_amount": _as_decimal(row.won_amount),
                    "lost_amount": _as_decimal(row.lost_amount),
                    "win_percent": percent_of(won_count, won_count + lost_count),
                }
            )
        return result

    async def lead_conversion_aggregates(
        self,
        tenant_id: UUID,
        *,
        group_by: str,
        from_date: date,
        to_date: date,
    ) -> list[dict[str, object]]:
        group_col, label_col, order_col = self._lead_group_columns(group_by)
        converted = Lead.status == LeadStatus.CONVERTED.value
        created_on = cast(Lead.created_at, SADate)
        statement = (
            select(
                group_col.label("group_key"),
                label_col.label("group_label"),
                func.count().label("lead_count"),
                func.coalesce(func.sum(case((converted, 1), else_=0)), 0).label("converted_count"),
            )
            .select_from(Lead)
            .outerjoin(
                User,
                and_(User.id == Lead.owner_id, User.tenant_id == Lead.tenant_id),
            )
            .outerjoin(
                LeadSource,
                and_(LeadSource.id == Lead.source_id, LeadSource.tenant_id == Lead.tenant_id),
            )
            .outerjoin(
                Campaign,
                and_(Campaign.id == Lead.campaign_id, Campaign.tenant_id == Lead.tenant_id),
            )
            .where(
                Lead.tenant_id == tenant_id,
                Lead.deleted_at.is_(None),
                created_on >= from_date,
                created_on <= to_date,
            )
            .group_by(group_col, label_col, order_col)
            .order_by(order_col, label_col)
            .limit(REPORT_ROW_LIMIT + 1)
        )
        rows = (await self.session.execute(statement)).all()
        result: list[dict[str, object]] = []
        for row in rows:
            lead_count = _as_int(row.lead_count)
            converted_count = _as_int(row.converted_count)
            result.append(
                {
                    "group_key": self._key(row.group_key),
                    "group_label": self._label(row.group_label),
                    "lead_count": lead_count,
                    "converted_count": converted_count,
                    "conversion_percent": percent_of(converted_count, lead_count),
                }
            )
        return result

    async def activity_aggregates(
        self,
        tenant_id: UUID,
        *,
        group_by: str,
        from_date: date,
        to_date: date,
        now: datetime,
    ) -> list[dict[str, object]]:
        group_col, label_col, order_col = self._activity_group_columns(group_by)
        activity_date = func.coalesce(
            cast(Activity.due_at, SADate), cast(Activity.created_at, SADate)
        )
        open_status = Activity.status == ActivityStatus.OPEN.value
        completed = Activity.status == ActivityStatus.COMPLETED.value
        overdue = and_(open_status, Activity.due_at.is_not(None), Activity.due_at < now)
        statement = (
            select(
                group_col.label("group_key"),
                label_col.label("group_label"),
                func.count().label("activity_count"),
                func.coalesce(func.sum(case((open_status, 1), else_=0)), 0).label("open_count"),
                func.coalesce(func.sum(case((completed, 1), else_=0)), 0).label("completed_count"),
                func.coalesce(func.sum(case((overdue, 1), else_=0)), 0).label("overdue_count"),
            )
            .select_from(Activity)
            .outerjoin(
                User,
                and_(User.id == Activity.owner_id, User.tenant_id == Activity.tenant_id),
            )
            .where(
                Activity.tenant_id == tenant_id,
                Activity.deleted_at.is_(None),
                activity_date >= from_date,
                activity_date <= to_date,
            )
            .group_by(group_col, label_col, order_col)
            .order_by(order_col, label_col)
            .limit(REPORT_ROW_LIMIT + 1)
        )
        rows = (await self.session.execute(statement)).all()
        return [
            {
                "group_key": self._key(row.group_key),
                "group_label": self._label(row.group_label),
                "activity_count": _as_int(row.activity_count),
                "open_count": _as_int(row.open_count),
                "completed_count": _as_int(row.completed_count),
                "overdue_count": _as_int(row.overdue_count),
            }
            for row in rows
        ]

    async def dashboard_totals(
        self,
        tenant_id: UUID,
        *,
        month_start: date,
        month_end: date,
        now: datetime,
    ) -> dict[str, Decimal | int]:
        open_criteria = (
            Opportunity.tenant_id == tenant_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.status == OpportunityStatus.OPEN.value,
        )
        open_count = _as_int(
            await self.session.scalar(
                select(func.count()).select_from(Opportunity).where(*open_criteria)
            )
        )
        open_value_rows = (
            await self.session.execute(
                select(
                    Opportunity.currency_id,
                    func.coalesce(func.sum(Opportunity.amount), 0).label("amount"),
                )
                .select_from(Opportunity)
                .where(*open_criteria)
                .group_by(Opportunity.currency_id)
            )
        ).all()
        closing_criteria = (
            *open_criteria,
            Opportunity.expected_close_date.is_not(None),
            Opportunity.expected_close_date >= month_start,
            Opportunity.expected_close_date < month_end,
        )
        closing_count = _as_int(
            await self.session.scalar(
                select(func.count()).select_from(Opportunity).where(*closing_criteria)
            )
        )
        closing_value_rows = (
            await self.session.execute(
                select(
                    Opportunity.currency_id,
                    func.coalesce(func.sum(Opportunity.amount), 0).label("amount"),
                )
                .select_from(Opportunity)
                .where(*closing_criteria)
                .group_by(Opportunity.currency_id)
            )
        ).all()
        overdue_count = _as_int(
            await self.session.scalar(
                select(func.count())
                .select_from(Activity)
                .where(
                    Activity.tenant_id == tenant_id,
                    Activity.deleted_at.is_(None),
                    Activity.status == ActivityStatus.OPEN.value,
                    Activity.due_at.is_not(None),
                    Activity.due_at < now,
                )
            )
        )
        return {
            "open_pipeline_count": open_count,
            "open_pipeline_value_rows": [
                (row.currency_id, _as_decimal(row.amount)) for row in open_value_rows
            ],
            "closing_this_month_count": closing_count,
            "closing_this_month_value_rows": [
                (row.currency_id, _as_decimal(row.amount)) for row in closing_value_rows
            ],
            "overdue_activity_count": overdue_count,
        }

    def _pipeline_row(self, row: Any) -> dict[str, object]:
        return {
            "group_key": self._key(row.group_key),
            "group_label": self._label(row.group_label),
            "currency_id": row.currency_id,
            "opportunity_count": _as_int(row.opportunity_count),
            "amount": _as_decimal(row.amount),
            "weighted_amount": _as_decimal(row.weighted_amount),
        }

    def _pipeline_group_columns(self, group_by: str) -> tuple[Any, Any, Any]:
        if group_by == "owner":
            key = func.coalesce(cast(Opportunity.owner_id, String), UNASSIGNED_KEY)
            label = func.coalesce(User.name, UNASSIGNED_LABEL)
            return key, label, label
        if group_by == "source":
            key = func.coalesce(cast(Opportunity.source_id, String), UNASSIGNED_KEY)
            label = func.coalesce(LeadSource.name, UNASSIGNED_LABEL)
            return key, label, label
        if group_by == "campaign":
            key = func.coalesce(cast(Opportunity.campaign_id, String), UNASSIGNED_KEY)
            label = func.coalesce(Campaign.name, UNASSIGNED_LABEL)
            return key, label, label
        key = func.coalesce(cast(Opportunity.stage_id, String), UNASSIGNED_KEY)
        label = func.coalesce(PipelineStage.name, UNASSIGNED_LABEL)
        order = func.coalesce(PipelineStage.sort_order, 10_000)
        return key, label, order

    def _win_loss_group_columns(self, group_by: str) -> tuple[Any, Any, Any]:
        if group_by == "owner":
            key = func.coalesce(cast(Opportunity.owner_id, String), UNASSIGNED_KEY)
            label = func.coalesce(User.name, UNASSIGNED_LABEL)
            return key, label, label
        if group_by == "source":
            key = func.coalesce(cast(Opportunity.source_id, String), UNASSIGNED_KEY)
            label = func.coalesce(LeadSource.name, UNASSIGNED_LABEL)
            return key, label, label
        if group_by == "campaign":
            key = func.coalesce(cast(Opportunity.campaign_id, String), UNASSIGNED_KEY)
            label = func.coalesce(Campaign.name, UNASSIGNED_LABEL)
            return key, label, label
        key = func.coalesce(cast(Opportunity.lost_reason_id, String), UNASSIGNED_KEY)
        label = func.coalesce(LostReason.name, UNASSIGNED_LABEL)
        return key, label, label

    def _lead_group_columns(self, group_by: str) -> tuple[Any, Any, Any]:
        if group_by == "source":
            key = func.coalesce(cast(Lead.source_id, String), UNASSIGNED_KEY)
            label = func.coalesce(LeadSource.name, UNASSIGNED_LABEL)
            return key, label, label
        if group_by == "owner":
            key = func.coalesce(cast(Lead.owner_id, String), UNASSIGNED_KEY)
            label = func.coalesce(User.name, UNASSIGNED_LABEL)
            return key, label, label
        if group_by == "campaign":
            key = func.coalesce(cast(Lead.campaign_id, String), UNASSIGNED_KEY)
            label = func.coalesce(Campaign.name, UNASSIGNED_LABEL)
            return key, label, label
        return Lead.status, Lead.status, Lead.status

    def _activity_group_columns(self, group_by: str) -> tuple[Any, Any, Any]:
        if group_by == "status":
            return Activity.status, Activity.status, Activity.status
        if group_by == "owner":
            key = func.coalesce(cast(Activity.owner_id, String), UNASSIGNED_KEY)
            label = func.coalesce(User.name, UNASSIGNED_LABEL)
            return key, label, label
        return Activity.activity_type, Activity.activity_type, Activity.activity_type

    def _key(self, value: object) -> str:
        if value is None:
            return UNASSIGNED_KEY
        return str(value)

    def _label(self, value: object) -> str:
        if value is None or value == "":
            return UNASSIGNED_LABEL
        return str(value)
