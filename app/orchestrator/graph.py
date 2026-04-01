from app.schemas.project import ProjectStatus

STATE_TRANSITIONS = {
    ProjectStatus.DRAFT: [ProjectStatus.INTAKE_PENDING],
    ProjectStatus.INTAKE_PENDING: [ProjectStatus.READY_FOR_PLANNING],
    ProjectStatus.READY_FOR_PLANNING: [ProjectStatus.IN_PROGRESS],
    ProjectStatus.IN_PROGRESS: [
        ProjectStatus.WAITING_APPROVAL,
        ProjectStatus.REVIEW_FAILED,
        ProjectStatus.COMPLETED,
    ],
    ProjectStatus.WAITING_APPROVAL: [
        ProjectStatus.IN_PROGRESS,
        ProjectStatus.REVISION_REQUESTED,
    ],
    ProjectStatus.REVIEW_FAILED: [ProjectStatus.REVISION_REQUESTED],
    ProjectStatus.REVISION_REQUESTED: [
        ProjectStatus.READY_FOR_PLANNING,
        ProjectStatus.IN_PROGRESS,
    ],
    ProjectStatus.COMPLETED: [],
}


def can_transition(current: ProjectStatus, next_status: ProjectStatus) -> bool:
    return next_status in STATE_TRANSITIONS[current]
