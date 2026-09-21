"""Unit tests: available_actions follows server state machine."""

from uuid import uuid4

from app.auth.catalog import OPPORTUNITY_DELETE, OPPORTUNITY_UPDATE
from app.core.enums import OpportunityStatus, PipelineStageKind
from app.crm.opportunities.models import Opportunity
from app.crm.opportunities.service import OpportunityService
from app.crm.pipelines.models import PipelineStage


def _stage(kind: PipelineStageKind, *, sort_order: int) -> PipelineStage:
    stage = PipelineStage(
        tenant_id=uuid4(),
        pipeline_id=uuid4(),
        name=kind.value,
        sort_order=sort_order,
        probability=25,
        stage_kind=kind.value,
    )
    stage.id = uuid4()
    return stage


def test_open_opportunity_actions_ignore_client_payload() -> None:
    pipeline_id = uuid4()
    current_stage = _stage(PipelineStageKind.OPEN, sort_order=1)
    current_stage.pipeline_id = pipeline_id
    next_stage = _stage(PipelineStageKind.OPEN, sort_order=2)
    next_stage.pipeline_id = pipeline_id
    won_stage = _stage(PipelineStageKind.WON, sort_order=3)
    won_stage.pipeline_id = pipeline_id
    lost_stage = _stage(PipelineStageKind.LOST, sort_order=4)
    lost_stage.pipeline_id = pipeline_id

    row = Opportunity(
        tenant_id=uuid4(),
        opportunity_number="OPP-00001",
        name="Deal",
        pipeline_id=pipeline_id,
        stage_id=current_stage.id,
        status=OpportunityStatus.OPEN.value,
        version=1,
    )
    row.id = uuid4()

    service = OpportunityService(
        session=None,  # type: ignore[arg-type]
        actor_permissions=frozenset({OPPORTUNITY_UPDATE, OPPORTUNITY_DELETE}),
    )
    actions = service.available_actions_for(row, [current_stage, next_stage, won_stage, lost_stage])

    assert f"move_stage:{next_stage.id}" in actions
    assert "win" in actions
    assert "lose" in actions
    assert "update" in actions
    assert "delete" in actions
    assert "reopen" not in actions
    assert f"move_stage:{current_stage.id}" not in actions


def test_won_opportunity_only_reopen() -> None:
    pipeline_id = uuid4()
    won_stage = _stage(PipelineStageKind.WON, sort_order=5)
    won_stage.pipeline_id = pipeline_id
    row = Opportunity(
        tenant_id=uuid4(),
        opportunity_number="OPP-00002",
        name="Closed",
        pipeline_id=pipeline_id,
        stage_id=won_stage.id,
        status=OpportunityStatus.WON.value,
        version=2,
    )
    row.id = uuid4()

    service = OpportunityService(
        session=None,  # type: ignore[arg-type]
        actor_permissions=frozenset({OPPORTUNITY_UPDATE, OPPORTUNITY_DELETE}),
    )
    actions = service.available_actions_for(row, [won_stage])

    assert actions == ["reopen"]
