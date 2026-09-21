"""Unit tests for CRM foundation defaults."""

from decimal import Decimal

from app.core.enums import PipelineStageKind
from app.crm.foundations.defaults import DEFAULT_PIPELINE_STAGES


def test_default_pipeline_includes_closed_stages() -> None:
    kinds = {stage_kind for _name, _order, _prob, stage_kind in DEFAULT_PIPELINE_STAGES}
    assert PipelineStageKind.WON in kinds
    assert PipelineStageKind.LOST in kinds
    won = next(
        prob
        for _name, _order, prob, kind in DEFAULT_PIPELINE_STAGES
        if kind == PipelineStageKind.WON
    )
    assert won == Decimal("100")
