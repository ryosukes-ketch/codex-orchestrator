from dataclasses import dataclass, field
from enum import Enum


class ContinuationDecision(str, Enum):
    GO = "GO"
    PAUSE = "PAUSE"
    REVIEW = "REVIEW"


class ContinuationRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class HardGateTrigger(str, Enum):
    AUTHENTICATION_BEHAVIOR = "authentication_behavior_change"
    AUTHORIZATION_BEHAVIOR = "authorization_behavior_change"
    APPROVAL_FLOW = "approval_flow_change"
    POLICY_MODEL = "policy_model_change"
    STRICT_MODE = "strict_mode_change"
    ACTOR_TRUST_MODEL = "actor_identity_trust_change"
    AUDIT_SEMANTICS = "audit_logging_semantics_change"
    DATABASE_SCHEMA = "database_schema_or_migration"
    PROVIDER_CONTRACT = "external_provider_contract_change"
    DEPENDENCY_ADDITION = "dependency_addition_required"
    DESTRUCTIVE_REFACTOR = "destructive_refactor"
    PRODUCTION_BEHAVIOR = "production_behavior_change"
    EXTERNAL_WRITE = "external_write_send_publish_action"
    ENV_HANDLING = "secrets_credentials_env_handling_change"
    ROADMAP_PHASE = "roadmap_phase_change_required"
    ARCHITECTURE_DIRECTION = "architecture_direction_change_required"


AREA_TO_HARD_GATE: dict[str, HardGateTrigger] = {
    "auth": HardGateTrigger.AUTHENTICATION_BEHAVIOR,
    "authorization": HardGateTrigger.AUTHORIZATION_BEHAVIOR,
    "approval": HardGateTrigger.APPROVAL_FLOW,
    "policy": HardGateTrigger.POLICY_MODEL,
    "strict_mode": HardGateTrigger.STRICT_MODE,
    "actor_trust": HardGateTrigger.ACTOR_TRUST_MODEL,
    "audit": HardGateTrigger.AUDIT_SEMANTICS,
    "schema": HardGateTrigger.DATABASE_SCHEMA,
    "migration": HardGateTrigger.DATABASE_SCHEMA,
    "provider_contract": HardGateTrigger.PROVIDER_CONTRACT,
    "dependency": HardGateTrigger.DEPENDENCY_ADDITION,
    "destructive_refactor": HardGateTrigger.DESTRUCTIVE_REFACTOR,
    "production_behavior": HardGateTrigger.PRODUCTION_BEHAVIOR,
    "external_write": HardGateTrigger.EXTERNAL_WRITE,
    "env": HardGateTrigger.ENV_HANDLING,
    "phase_change": HardGateTrigger.ROADMAP_PHASE,
    "architecture_change": HardGateTrigger.ARCHITECTURE_DIRECTION,
}


@dataclass(frozen=True)
class ContinuationContext:
    task_in_active_phase: bool
    next_step_clear: bool
    verification_passed: bool
    hard_gate_triggers: set[HardGateTrigger] = field(default_factory=set)


@dataclass(frozen=True)
class ContinuationAssessment:
    decision: ContinuationDecision
    risk: ContinuationRisk
    reason: str


def detect_hard_gate_triggers(changed_areas: set[str]) -> set[HardGateTrigger]:
    normalized_areas = {
        area.strip().lower() for area in changed_areas if isinstance(area, str) and area.strip()
    }
    return {AREA_TO_HARD_GATE[area] for area in normalized_areas if area in AREA_TO_HARD_GATE}


def assess_continuation(context: ContinuationContext) -> ContinuationAssessment:
    if context.hard_gate_triggers:
        reasons = ", ".join(sorted(trigger.value for trigger in context.hard_gate_triggers))
        return ContinuationAssessment(
            decision=ContinuationDecision.REVIEW,
            risk=ContinuationRisk.HIGH,
            reason=f"hard gate triggered: {reasons}",
        )

    if not context.task_in_active_phase:
        return ContinuationAssessment(
            decision=ContinuationDecision.REVIEW,
            risk=ContinuationRisk.HIGH,
            reason="task is outside the active roadmap phase.",
        )

    if not context.next_step_clear:
        return ContinuationAssessment(
            decision=ContinuationDecision.PAUSE,
            risk=ContinuationRisk.MEDIUM,
            reason="next valid step is unclear.",
        )

    if not context.verification_passed:
        return ContinuationAssessment(
            decision=ContinuationDecision.PAUSE,
            risk=ContinuationRisk.MEDIUM,
            reason="verification is failing or not yet isolated.",
        )

    return ContinuationAssessment(
        decision=ContinuationDecision.GO,
        risk=ContinuationRisk.LOW,
        reason="safe to continue with smallest phase-aligned change.",
    )
