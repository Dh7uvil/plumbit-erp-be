"""Opportunity pipeline stage rules."""

from uuid import UUID

from app.core.enums import OpportunityStatus, PipelineStageKind
from app.core.exceptions import InvalidStatusTransitionError, ValidationError
from app.crm.pipelines.models import PipelineStage

_TERMINAL = frozenset({OpportunityStatus.WON, OpportunityStatus.LOST})


def status_for_stage_kind(stage_kind: str) -> OpportunityStatus:
    if stage_kind == PipelineStageKind.WON.value:
        return OpportunityStatus.WON
    if stage_kind == PipelineStageKind.LOST.value:
        return OpportunityStatus.LOST
    return OpportunityStatus.OPEN


def assert_editable(status: OpportunityStatus) -> None:
    if status in _TERMINAL:
        raise InvalidStatusTransitionError(
            f"Opportunities in {status.value} status cannot be changed except by reopen"
        )


def assert_reopen_allowed(status: OpportunityStatus) -> None:
    if status not in _TERMINAL:
        raise InvalidStatusTransitionError("Only won or lost opportunities can be reopened")


def assert_stage_move_allowed(
    *,
    current_status: OpportunityStatus,
    pipeline_id: UUID,
    from_stage: PipelineStage,
    to_stage: PipelineStage,
) -> None:
    if current_status not in {OpportunityStatus.OPEN}:
        raise InvalidStatusTransitionError(
            "Closed opportunities cannot change stage except through reopen"
        )
    if to_stage.pipeline_id != pipeline_id:
        raise InvalidStatusTransitionError("Stage must belong to the opportunity pipeline")
    if from_stage.pipeline_id != pipeline_id:
        raise InvalidStatusTransitionError("Current stage does not belong to the pipeline")
    if from_stage.id == to_stage.id:
        raise ValidationError("Opportunity is already in the requested stage")


def assert_lost_reason_required(to_stage: PipelineStage, lost_reason_id: UUID | None) -> None:
    if to_stage.stage_kind == PipelineStageKind.LOST.value and lost_reason_id is None:
        raise ValidationError("lost_reason_id is required when moving to a lost stage")


def find_stage_by_kind(
    stages: list[PipelineStage], kind: PipelineStageKind
) -> PipelineStage | None:
    for stage in stages:
        if stage.stage_kind == kind.value:
            return stage
    return None


def default_reopen_stage(stages: list[PipelineStage]) -> PipelineStage | None:
    open_stages = [
        stage for stage in stages if stage.stage_kind == PipelineStageKind.OPEN.value
    ]
    if not open_stages:
        return None
    return min(open_stages, key=lambda item: (item.sort_order, item.name))


def allowed_target_stage_ids(
    *,
    status: OpportunityStatus,
    current_stage_id: UUID,
    stages: list[PipelineStage],
) -> list[UUID]:
    if status != OpportunityStatus.OPEN:
        return []
    return [stage.id for stage in stages if stage.id != current_stage_id]
