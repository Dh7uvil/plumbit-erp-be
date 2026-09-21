"""Unit tests for opportunity stage workflow."""

from uuid import uuid4

import pytest

from app.core.enums import OpportunityStatus, PipelineStageKind
from app.core.exceptions import InvalidStatusTransitionError, ValidationError
from app.crm.opportunities.workflow import (
    assert_editable,
    assert_lost_reason_required,
    assert_stage_move_allowed,
    status_for_stage_kind,
)
from app.crm.pipelines.models import PipelineStage


def _stage(*, kind: PipelineStageKind, pipeline_id=None) -> PipelineStage:
    pid = pipeline_id or uuid4()
    stage = PipelineStage(
        tenant_id=uuid4(),
        pipeline_id=pid,
        name=kind.value,
        sort_order=1,
        probability=10,
        stage_kind=kind.value,
    )
    stage.id = uuid4()
    return stage


def test_status_for_won_stage() -> None:
    assert status_for_stage_kind(PipelineStageKind.WON.value) == OpportunityStatus.WON


def test_closed_opportunity_is_not_editable() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        assert_editable(OpportunityStatus.WON)


def test_lost_stage_requires_reason() -> None:
    lost = _stage(kind=PipelineStageKind.LOST)
    with pytest.raises(ValidationError):
        assert_lost_reason_required(lost, None)


def test_cross_pipeline_stage_is_rejected() -> None:
    pipeline_id = uuid4()
    other_pipeline = uuid4()
    from_stage = _stage(kind=PipelineStageKind.OPEN, pipeline_id=pipeline_id)
    to_stage = _stage(kind=PipelineStageKind.OPEN, pipeline_id=other_pipeline)
    with pytest.raises(InvalidStatusTransitionError):
        assert_stage_move_allowed(
            current_status=OpportunityStatus.OPEN,
            pipeline_id=pipeline_id,
            from_stage=from_stage,
            to_stage=to_stage,
        )
