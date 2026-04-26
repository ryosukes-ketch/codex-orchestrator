from pydantic import BaseModel, Field

from app.schemas.brief import ProjectBrief
from app.schemas.project import ActorContext, ActorRole, ActorType, ProjectPolicy, RevisionResumeMode


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


class AuthTokenIssueRequest(BaseModel):
    actor_id: str = Field(min_length=1)
    actor_role: ActorRole
    actor_type: ActorType = ActorType.HUMAN
    token: str | None = None
    description: str = ""


class AuthTokenRevokeRequest(BaseModel):
    token: str = Field(min_length=1)


class AuthTokenRotateRequest(BaseModel):
    token: str = Field(min_length=1)
    new_token: str | None = None


class AuthTokenDescriptor(BaseModel):
    token_preview: str
    token_fingerprint: str
    actor_id: str
    actor_role: ActorRole
    actor_type: ActorType
    created_at: str = ""
    updated_at: str = ""
    description: str = ""


class AuthTokenListResponse(BaseModel):
    auth_service_mode: str
    token_store_path: str = ""
    managed_by_actor_id: str
    token_count: int
    tokens: list[AuthTokenDescriptor] = Field(default_factory=list)


class AuthTokenIssueResponse(BaseModel):
    auth_service_mode: str
    token_store_path: str = ""
    managed_by_actor_id: str
    token: str
    token_preview: str
    token_fingerprint: str
    actor: ActorContext
    created_at: str = ""
    updated_at: str = ""
    description: str = ""


class AuthTokenRevokeResponse(BaseModel):
    auth_service_mode: str
    token_store_path: str = ""
    managed_by_actor_id: str
    token_preview: str
    token_fingerprint: str
    actor: ActorContext
    created_at: str = ""
    updated_at: str = ""
    description: str = ""
    revoked_at: str


class AuthTokenRotateResponse(BaseModel):
    auth_service_mode: str
    token_store_path: str = ""
    managed_by_actor_id: str
    old_token_preview: str
    old_token_fingerprint: str
    token: str
    token_preview: str
    token_fingerprint: str
    actor: ActorContext
    created_at: str = ""
    updated_at: str = ""
    description: str = ""
