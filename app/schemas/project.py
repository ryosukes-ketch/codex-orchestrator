from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.brief import ProjectBrief


class Department(str, Enum):
    RESEARCH = "research"
    DESIGN = "design"
    BUILD = "build"
    REVIEW = "review"
    TREND = "trend"


class ActorRole(str, Enum):
    OWNER = "owner"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"
    VIEWER = "viewer"


class ActorType(str, Enum):
    HUMAN = "human"
    SERVICE = "service"
    SYSTEM = "system"


class ActorContext(BaseModel):
    actor_id: str
    actor_role: ActorRole
    actor_type: ActorType = ActorType.HUMAN


class ProjectPolicyActionRule(BaseModel):
    allowed_roles: list[ActorRole] = Field(default_factory=list)
    allowed_actor_ids: list[str] = Field(default_factory=list)


class ProjectPolicy(BaseModel):
    project_owner_actor_id: str | None = None
    strict_mode: bool = False
    action_rules: dict[str, ProjectPolicyActionRule] = Field(default_factory=dict)


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_APPROVAL = "waiting_approval"
    REVISION_REQUESTED = "revision_requested"
    DONE = "done"
    BLOCKED = "blocked"


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    INTAKE_PENDING = "intake_pending"
    READY_FOR_PLANNING = "ready_for_planning"
    IN_PROGRESS = "in_progress"
    WAITING_APPROVAL = "waiting_approval"
    REVIEW_FAILED = "review_failed"
    REVISION_REQUESTED = "revision_requested"
    COMPLETED = "completed"


class Project(BaseModel):
    id: str
    brief: ProjectBrief
    policy: ProjectPolicy = Field(default_factory=ProjectPolicy)
    status: ProjectStatus = ProjectStatus.DRAFT


class Task(BaseModel):
    id: str
    title: str
    department: Department
    status: TaskStatus = TaskStatus.PENDING
    depends_on: list[str] = Field(default_factory=list)
    note: str = ""


class Artifact(BaseModel):
    id: str
    task_id: str
    artifact_type: str
    content: dict[str, Any] = Field(default_factory=dict)


class Review(BaseModel):
    id: str
    task_id: str
    verdict: str
    findings: list[str] = Field(default_factory=list)


class Checkpoint(BaseModel):
    id: str
    name: str
    approved: bool = False
    approver: str = "human"
    note: str = ""


class ApprovalActionType(str, Enum):
    EXTERNAL_API_SEND = "external_api_send"
    DESTRUCTIVE_CHANGE = "destructive_change"
    BULK_MODIFY = "bulk_modify"
    PRODUCTION_AFFECTING_CHANGE = "production_affecting_change"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalRequest(BaseModel):
    id: str
    action_type: ApprovalActionType
    status: ApprovalStatus = ApprovalStatus.PENDING
    reason: str
    requested_by: str = "system"
    decision_note: str = ""


class RevisionResumeMode(str, Enum):
    REPLANNING = "replanning"
    REBUILDING = "rebuilding"
    REREVIEW = "rereview"


class HistoryEventType(str, Enum):
    AUTHENTICATION_SUCCEEDED = "authentication_succeeded"
    AUTHENTICATION_FAILED = "authentication_failed"
    ACTOR_RESOLVED = "actor_resolved"
    STATE_TRANSITION = "state_transition"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_APPROVED = "approval_approved"
    APPROVAL_REJECTED = "approval_rejected"
    AUTHORIZATION_GRANTED = "authorization_granted"
    AUTHORIZATION_FAILED = "authorization_failed"
    POLICY_OVERRIDE_APPLIED = "policy_override_applied"
    REVISION_REQUESTED = "revision_requested"
    REPLANNING_STARTED = "replanning_started"
    RESUME_TRIGGERED = "resume_triggered"
    TASK_STATUS_CHANGED = "task_status_changed"


class HistoryEvent(BaseModel):
    event_type: HistoryEventType
    actor: str = "system"
    actor_role: ActorRole = ActorRole.ADMIN
    actor_type: ActorType = ActorType.SYSTEM
    timestamp: str = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat(),
    )
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectRecord(BaseModel):
    project: Project
    tasks: list[Task] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    reviews: list[Review] = Field(default_factory=list)
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    approvals: list[ApprovalRequest] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    events: list[HistoryEvent] = Field(default_factory=list)


class ProjectSummary(BaseModel):
    project_id: str
    status: ProjectStatus
    completed_tasks: int
    artifact_count: int
    next_steps: list[str] = Field(default_factory=list)


class OrchestrationResult(BaseModel):
    record: ProjectRecord
    summary: ProjectSummary


class ProjectAudit(BaseModel):
    project_id: str
    status: ProjectStatus
    history: list[str] = Field(default_factory=list)
    events: list[HistoryEvent] = Field(default_factory=list)
    approvals: list[ApprovalRequest] = Field(default_factory=list)
    reviews: list[Review] = Field(default_factory=list)
    checkpoints: list[Checkpoint] = Field(default_factory=list)
