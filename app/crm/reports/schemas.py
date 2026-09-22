"""CRM report request/response schemas."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class CrmReportCurrencyMixin(BaseModel):
    currency_code: str | None = Field(
        default=None,
        description="ISO currency code for monetary amounts (tenant base currency).",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal FX or data warnings for monetary totals.",
    )


class SalesPipelineLine(BaseModel):
    group_key: str
    group_label: str
    opportunity_count: int
    amount: Decimal
    weighted_amount: Decimal


class SalesPipelineResponse(CrmReportCurrencyMixin):
    group_by: str
    pipeline_id: UUID | None = None
    opportunity_count: int
    total_amount: Decimal
    total_weighted_amount: Decimal
    truncated: bool = False
    lines: list[SalesPipelineLine] = Field(default_factory=list)


class SalesFunnelLine(BaseModel):
    stage_id: UUID
    stage_name: str
    sort_order: int
    stage_kind: str
    opportunity_count: int
    amount: Decimal
    weighted_amount: Decimal
    conversion_percent: Decimal | None = None


class SalesFunnelResponse(CrmReportCurrencyMixin):
    pipeline_id: UUID
    pipeline_name: str
    opportunity_count: int
    total_amount: Decimal
    total_weighted_amount: Decimal
    lines: list[SalesFunnelLine] = Field(default_factory=list)


class WinLossLine(BaseModel):
    group_key: str
    group_label: str
    won_count: int
    lost_count: int
    won_amount: Decimal
    lost_amount: Decimal
    win_percent: Decimal | None = None


class WinLossResponse(CrmReportCurrencyMixin):
    from_date: date
    to_date: date
    group_by: str
    won_count: int
    lost_count: int
    won_amount: Decimal
    lost_amount: Decimal
    win_percent: Decimal | None = None
    truncated: bool = False
    lines: list[WinLossLine] = Field(default_factory=list)


class LeadConversionLine(BaseModel):
    group_key: str
    group_label: str
    lead_count: int
    converted_count: int
    conversion_percent: Decimal | None = None


class LeadConversionResponse(BaseModel):
    from_date: date
    to_date: date
    group_by: str
    lead_count: int
    converted_count: int
    conversion_percent: Decimal | None = None
    truncated: bool = False
    lines: list[LeadConversionLine] = Field(default_factory=list)


class SalesActivityLine(BaseModel):
    group_key: str
    group_label: str
    activity_count: int
    open_count: int
    completed_count: int
    overdue_count: int


class SalesActivityResponse(BaseModel):
    from_date: date
    to_date: date
    group_by: str
    activity_count: int
    open_count: int
    completed_count: int
    overdue_count: int
    truncated: bool = False
    lines: list[SalesActivityLine] = Field(default_factory=list)


class CrmDashboardResponse(CrmReportCurrencyMixin):
    as_of: date
    open_pipeline_count: int
    open_pipeline_value: Decimal
    closing_this_month_count: int
    closing_this_month_value: Decimal
    overdue_activity_count: int
