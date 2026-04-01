from app.services.continuation import (
    ContinuationContext,
    ContinuationDecision,
    HardGateTrigger,
    assess_continuation,
    detect_hard_gate_triggers,
)


def test_detect_hard_gate_triggers_maps_known_areas() -> None:
    triggers = detect_hard_gate_triggers({"auth", "schema", "unknown"})
    assert HardGateTrigger.AUTHENTICATION_BEHAVIOR in triggers
    assert HardGateTrigger.DATABASE_SCHEMA in triggers
    assert len(triggers) == 2


def test_detect_hard_gate_triggers_deduplicates_schema_aliases() -> None:
    triggers = detect_hard_gate_triggers({"schema", "migration", "approval"})

    assert triggers == {HardGateTrigger.DATABASE_SCHEMA, HardGateTrigger.APPROVAL_FLOW}


def test_detect_hard_gate_triggers_normalizes_case_and_whitespace() -> None:
    triggers = detect_hard_gate_triggers({"  AUTH  ", " Policy ", "unknown"})

    assert triggers == {
        HardGateTrigger.AUTHENTICATION_BEHAVIOR,
        HardGateTrigger.POLICY_MODEL,
    }


def test_assess_continuation_review_on_hard_gate() -> None:
    assessment = assess_continuation(
        ContinuationContext(
            task_in_active_phase=True,
            next_step_clear=True,
            verification_passed=True,
            hard_gate_triggers={HardGateTrigger.POLICY_MODEL},
        )
    )
    assert assessment.decision == ContinuationDecision.REVIEW


def test_assess_continuation_pause_on_unclear_step() -> None:
    assessment = assess_continuation(
        ContinuationContext(
            task_in_active_phase=True,
            next_step_clear=False,
            verification_passed=True,
        )
    )
    assert assessment.decision == ContinuationDecision.PAUSE


def test_assess_continuation_pause_on_failed_verification() -> None:
    assessment = assess_continuation(
        ContinuationContext(
            task_in_active_phase=True,
            next_step_clear=True,
            verification_passed=False,
        )
    )
    assert assessment.decision == ContinuationDecision.PAUSE


def test_assess_continuation_go_for_safe_context() -> None:
    assessment = assess_continuation(
        ContinuationContext(
            task_in_active_phase=True,
            next_step_clear=True,
            verification_passed=True,
        )
    )
    assert assessment.decision == ContinuationDecision.GO


def test_assess_continuation_review_on_phase_mismatch() -> None:
    assessment = assess_continuation(
        ContinuationContext(
            task_in_active_phase=False,
            next_step_clear=True,
            verification_passed=True,
        )
    )

    assert assessment.decision == ContinuationDecision.REVIEW
    assert assessment.risk.name == "HIGH"
    assert assessment.reason == "task is outside the active roadmap phase."
