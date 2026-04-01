from pydantic import BaseModel, Field

from app.schemas.brief import ProjectBrief
from app.schemas.project import ActorContext, ProjectPolicy, RevisionResumeMode


class IntakeBriefRequest(BaseModel):
    user_request: str = Field(min_length=1)


class OrchestratorRunRequest(BaseModel):
    brief: ProjectBrief
    project_policy: ProjectPolicy | None = None
    trend_provider: str = "mock"
    approved_actions: list[str] = Field(default_factory=list)
    simulate_review_failure: bool = False


class ApprovalResumeRequest(BaseModel):
    project_id: str = Field(min_length=1)
    approved_actions: list[str] = Field(default_factory=list)
    actor: ActorContext | None = None
    note: str = ""
    trend_provider: str = "mock"


class ApprovalRejectRequest(BaseModel):
    project_id: str = Field(min_length=1)
    rejected_actions: list[str] = Field(default_factory=list)
    actor: ActorContext | None = None
    reason: str = Field(min_length=1)
    note: str = ""


class RevisionResumeRequest(BaseModel):
    project_id: str = Field(min_length=1)
    resume_mode: RevisionResumeMode
    actor: ActorContext | None = None
    reason: str = ""
    trend_provider: str = "mock"
    approved_actions: list[str] = Field(default_factory=list)


class ReplanningStartRequest(BaseModel):
    project_id: str = Field(min_length=1)
    actor: ActorContext | None = None
    note: str = ""
    trend_provider: str = "mock"
    approved_actions: list[str] = Field(default_factory=list)
    reset_downstream_tasks: bool = True
