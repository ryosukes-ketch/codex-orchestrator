from typing import Literal

from pydantic import BaseModel, Field


class DepartmentContext(BaseModel):
    origin_department: str = "intake_department"
    candidate_routing: str = "progress_control_department"
    ownership_boundary_note: str = (
        "Intake prepares draft brief data and does not self-approve governance-sensitive work."
    )


class RiskSnapshot(BaseModel):
    risk_level: Literal["low", "medium", "high"] = "low"
    hard_gate_triggered: bool = False
    hard_gate_triggers: list[str] = Field(default_factory=list)
    escalation_likely_required: bool = False


class ProposedActionDraft(BaseModel):
    summary: str = "Route to Progress Control for triage and management review."
    verification_plan: list[str] = Field(default_factory=list)


class CurrentBriefArtifact(BaseModel):
    brief_id: str
    project_id: str
    active_phase: str = "phase_4"
    current_task: str
    requested_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    department_context: DepartmentContext = Field(default_factory=DepartmentContext)
    risk_snapshot: RiskSnapshot = Field(default_factory=RiskSnapshot)
    proposed_action: ProposedActionDraft = Field(default_factory=ProposedActionDraft)
    intake_missing_fields: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)


class ManagementReviewInput(BaseModel):
    related_project_id: str
    related_brief_id: str
    active_phase: str
    current_task: str
    candidate_routing_department: str
    risk_level: Literal["low", "medium", "high"]
    hard_gate_triggered: bool
    hard_gate_triggers: list[str] = Field(default_factory=list)
    intake_readiness: Literal["needs_clarification", "ready_for_planning"]
    intake_missing_fields: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    proposed_action_summary: str
    verification_plan: list[str] = Field(default_factory=list)
    reviewer_hint: str | None = None
    related_task_id: str | None = None


class ManagementReviewSummary(BaseModel):
    project_id: str
    brief_id: str | None = None
    current_task: str
    decision_outcome: Literal["GO", "PAUSE", "REVIEW"]
    risk_level: Literal["low", "medium", "high"]
    department_routing: str
    hard_gate_triggered: bool
    hard_gate_triggers: list[str] = Field(default_factory=list)
    proposed_action: str
    required_review: bool
    escalation_reason: str | None = None
    trend_provider: str | None = None
    trend_candidate_count: int = 0
    work_order_id: str | None = None


class BriefSummary(BaseModel):
    requested_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)


class ManagementReviewPacket(BaseModel):
    packet_id: str
    project_id: str
    brief_id: str | None = None
    current_task: str
    summarized_brief: BriefSummary
    risk_level: Literal["low", "medium", "high"]
    department_routing_recommendation: str
    hard_gate_status: bool
    hard_gate_triggers: list[str] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)
    proposed_next_action: str
    recommendation: Literal["GO", "PAUSE", "REVIEW"]
    required_review: bool
    work_order_id: str | None = None
    trend_provider: str | None = None
    trend_candidate_count: int = 0
