from dataclasses import dataclass, field

from app.services.continuation import ContinuationDecision, ContinuationRisk, HardGateTrigger
from app.services.triage import EscalationReason, RoutingDepartment, TriageResult

DEFAULT_CONSTRAINTS = [
    "No new dependencies",
    "No auth/approval/policy/audit behavior change",
]

DEFAULT_COMPLETION_CRITERIA = [
    "Requested artifact exists",
    "No unrelated code change",
    "Verification passed",
]


@dataclass(frozen=True)
class WorkOrderInput:
    task_summary: str
    required_files: list[str] = field(default_factory=list)
    optional_files: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=lambda: list(DEFAULT_CONSTRAINTS))


@dataclass(frozen=True)
class WorkOrderVerification:
    commands: list[str] = field(default_factory=list)
    expected_result: str = "pass"


@dataclass(frozen=True)
class WorkOrderGovernance:
    decision_outcome: ContinuationDecision
    risk_level: ContinuationRisk
    hard_gate_triggers: set[HardGateTrigger] = field(default_factory=set)
    escalation_reason: EscalationReason = EscalationReason.NONE
    management_review_required: bool = False


@dataclass(frozen=True)
class WorkOrderDraft:
    work_order_id: str
    project_id: str
    title: str
    objective: str
    assigned_department: RoutingDepartment
    next_action_suggestion: str
    inputs: WorkOrderInput
    governance: WorkOrderGovernance
    verification: WorkOrderVerification = field(default_factory=WorkOrderVerification)
    completion_criteria: list[str] = field(
        default_factory=lambda: list(DEFAULT_COMPLETION_CRITERIA)
    )

    def to_artifact_payload(self) -> dict[str, object]:
        return {
            "work_order_id": self.work_order_id,
            "project_id": self.project_id,
            "title": self.title,
            "objective": self.objective,
            "assigned_department": self.assigned_department.value,
            "inputs": {
                "task_summary": self.inputs.task_summary,
                "required_files": list(self.inputs.required_files),
                "optional_files": list(self.inputs.optional_files),
                "constraints": list(self.inputs.constraints),
            },
            "governance": {
                "decision_outcome": self.governance.decision_outcome.value,
                "risk_level": self.governance.risk_level.value,
                "hard_gate_triggers": sorted(
                    trigger.value for trigger in self.governance.hard_gate_triggers
                ),
                "escalation_reason": self.governance.escalation_reason.value,
                "management_review_required": self.governance.management_review_required,
            },
            "next_action_suggestion": self.next_action_suggestion,
            "verification": {
                "commands": list(self.verification.commands),
                "expected_result": self.verification.expected_result,
            },
            "completion_criteria": list(self.completion_criteria),
        }


def build_work_order_draft(
    triage_result: TriageResult,
    *,
    work_order_id: str,
    project_id: str,
    objective: str,
    title: str = "Draft work order",
    required_files: list[str] | None = None,
    optional_files: list[str] | None = None,
    verification_commands: list[str] | None = None,
) -> WorkOrderDraft:
    governance_review_required = _management_review_required(triage_result)
    required_files_snapshot = list(required_files or [])
    optional_files_snapshot = list(optional_files or [])
    verification_commands_snapshot = list(verification_commands or [])

    return WorkOrderDraft(
        work_order_id=work_order_id,
        project_id=project_id,
        title=title,
        objective=objective,
        assigned_department=triage_result.routing_target,
        next_action_suggestion=_next_action_suggestion(triage_result),
        inputs=WorkOrderInput(
            task_summary=objective,
            required_files=required_files_snapshot,
            optional_files=optional_files_snapshot,
        ),
        governance=WorkOrderGovernance(
            decision_outcome=triage_result.decision,
            risk_level=triage_result.risk_level,
            hard_gate_triggers=set(triage_result.hard_gate_triggers),
            escalation_reason=triage_result.escalation_reason,
            management_review_required=governance_review_required,
        ),
        verification=WorkOrderVerification(commands=verification_commands_snapshot),
    )


def _management_review_required(triage_result: TriageResult) -> bool:
    return (
        triage_result.decision == ContinuationDecision.REVIEW
        or triage_result.routing_target
        in (RoutingDepartment.MANAGEMENT, RoutingDepartment.AUDIT_REVIEW)
        or triage_result.escalation_likely_required
    )


def _next_action_suggestion(triage_result: TriageResult) -> str:
    if triage_result.decision == ContinuationDecision.REVIEW:
        return "Escalate to Management Department for REVIEW; do not continue autonomously."
    if triage_result.decision == ContinuationDecision.PAUSE:
        return "PAUSE and isolate blockers in Progress Control before implementation handoff."
    if triage_result.routing_target == RoutingDepartment.ACTION:
        return "Run low-risk Action Department support task, then re-triage before implementation."
    if triage_result.routing_target == RoutingDepartment.IMPLEMENTATION:
        return "Proceed with the smallest implementation change and run targeted verification."
    return "Follow routed department instructions and keep GO/PAUSE/REVIEW governance intact."
