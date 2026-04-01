from app.orchestrator.graph import can_transition
from app.schemas.project import ProjectStatus


def test_core_happy_path_transitions() -> None:
    assert can_transition(ProjectStatus.DRAFT, ProjectStatus.INTAKE_PENDING)
    assert can_transition(
        ProjectStatus.INTAKE_PENDING,
        ProjectStatus.READY_FOR_PLANNING,
    )
    assert can_transition(
        ProjectStatus.READY_FOR_PLANNING,
        ProjectStatus.IN_PROGRESS,
    )
    assert can_transition(ProjectStatus.IN_PROGRESS, ProjectStatus.COMPLETED)


def test_approval_and_rollback_transitions() -> None:
    assert can_transition(
        ProjectStatus.IN_PROGRESS,
        ProjectStatus.WAITING_APPROVAL,
    )
    assert can_transition(
        ProjectStatus.WAITING_APPROVAL,
        ProjectStatus.IN_PROGRESS,
    )
    assert can_transition(
        ProjectStatus.WAITING_APPROVAL,
        ProjectStatus.REVISION_REQUESTED,
    )
    assert can_transition(
        ProjectStatus.IN_PROGRESS,
        ProjectStatus.REVIEW_FAILED,
    )
    assert can_transition(
        ProjectStatus.REVIEW_FAILED,
        ProjectStatus.REVISION_REQUESTED,
    )
    assert can_transition(
        ProjectStatus.REVISION_REQUESTED,
        ProjectStatus.READY_FOR_PLANNING,
    )


def test_disallowed_transition() -> None:
    assert not can_transition(ProjectStatus.DRAFT, ProjectStatus.COMPLETED)
