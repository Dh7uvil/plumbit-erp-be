"""Default CRM setup data for new and backfilled tenants."""

from decimal import Decimal

from app.core.enums import PipelineStageKind

DEFAULT_PIPELINE_NAME = "Standard Sales"

DEFAULT_PIPELINE_STAGES: tuple[tuple[str, int, Decimal, PipelineStageKind], ...] = (
    ("Qualification", 1, Decimal("10"), PipelineStageKind.OPEN),
    ("Needs Analysis", 2, Decimal("20"), PipelineStageKind.OPEN),
    ("Proposal", 3, Decimal("50"), PipelineStageKind.OPEN),
    ("Negotiation", 4, Decimal("80"), PipelineStageKind.OPEN),
    ("Closed Won", 5, Decimal("100"), PipelineStageKind.WON),
    ("Closed Lost", 6, Decimal("0"), PipelineStageKind.LOST),
)

DEFAULT_LEAD_SOURCES: tuple[str, ...] = (
    "Website",
    "Referral",
    "Cold Call",
    "Trade Show",
    "Partner",
    "Advertisement",
    "Email Campaign",
    "Social Media",
)
