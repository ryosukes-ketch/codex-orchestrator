from app.intake.review_artifacts import intake_result_to_current_brief_artifact
from app.intake.service import IntakeAgent
from app.schemas.trend import TrendAnalysisRequest
from app.services.management_review import build_management_review_summary
from app.services.trend_workflow import run_trend_mock_workflow
from app.services.triage import TriageContext, triage_task
from app.services.work_order import build_work_order_draft


def test_management_review_summary_brief_only_defaults_to_pause_and_review_required() -> None:
    brief = _build_brief_artifact("Build an internal workflow platform.")

    summary = build_management_review_summary(current_brief=brief)

    assert summary.current_task == brief.current_task
    assert summary.decision_outcome == "PAUSE"
    assert summary.department_routing == "progress_control_department"
    assert summary.proposed_action == brief.proposed_action.summary
    assert summary.required_review is True


def test_management_review_summary_uses_triage_for_risk_and_hard_gate() -> None:
    brief = _build_brief_artifact("Harden approval controls.")
    triage = triage_task(
        TriageContext(
            changed_areas={"approval"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    trend = run_trend_mock_workflow(TrendAnalysisRequest(trend_topic="approval", max_items=1))

    summary = build_management_review_summary(
        current_brief=brief,
        triage_result=triage,
        trend_report=trend,
    )

    assert summary.decision_outcome == "REVIEW"
    assert summary.risk_level == "high"
    assert summary.department_routing == "management_department"
    assert summary.hard_gate_triggered is True
    assert "approval_flow_change" in summary.hard_gate_triggers
    assert summary.trend_provider == "mock"
    assert summary.trend_candidate_count == 1
    assert summary.required_review is True


def test_management_review_summary_prefers_work_order_governance_when_available() -> None:
    brief = _build_brief_artifact("Coordinate cross department action.")
    triage = triage_task(
        TriageContext(
            changed_areas={"cross_department"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    work_order = build_work_order_draft(
        triage,
        work_order_id="wo_summary",
        project_id=brief.project_id,
        objective="Escalate cross department routing.",
    )

    summary = build_management_review_summary(
        current_brief=brief,
        triage_result=triage,
        work_order=work_order,
    )

    assert summary.work_order_id == "wo_summary"
    assert summary.decision_outcome == "REVIEW"
    assert summary.department_routing == "management_department"
    assert summary.proposed_action == work_order.next_action_suggestion
    assert summary.required_review is True
    assert summary.escalation_reason == "cross_department_routing"


def test_management_review_summary_triage_pause_uses_fixed_pause_action() -> None:
    brief = _build_brief_artifact("Stabilize verification gate handling.")
    triage = triage_task(
        TriageContext(
            changed_areas={"implementation"},
            task_in_active_phase=True,
            verification_passed=False,
            ambiguous_scope=False,
        )
    )
    trend = run_trend_mock_workflow(
        TrendAnalysisRequest(trend_topic="verification", max_items=2)
    )

    summary = build_management_review_summary(
        current_brief=brief,
        triage_result=triage,
        trend_report=trend,
    )

    assert summary.decision_outcome == "PAUSE"
    assert summary.proposed_action == "Pause and isolate blockers before continuing."
    assert summary.required_review is False
    assert summary.escalation_reason == "verification_unstable"


def test_management_review_summary_triage_go_prefers_trend_suggestion() -> None:
    brief = _build_brief_artifact("Update docs and examples only.")
    triage = triage_task(
        TriageContext(
            changed_areas={"docs"},
            task_in_active_phase=True,
            verification_passed=True,
            ambiguous_scope=False,
        )
    )
    trend = run_trend_mock_workflow(TrendAnalysisRequest(trend_topic="docs", max_items=1))

    summary = build_management_review_summary(
        current_brief=brief,
        triage_result=triage,
        trend_report=trend,
    )

    assert summary.decision_outcome == "GO"
    assert summary.risk_level == "low"
    assert summary.department_routing == "action_department"
    assert summary.proposed_action == trend.next_action_suggestion
    assert summary.required_review is False
    assert summary.escalation_reason == "none"


def test_management_review_summary_trend_only_uses_brief_defaults_and_trend_metadata() -> None:
    brief = _build_brief_artifact("Prepare lightweight delivery checklist.")
    trend = run_trend_mock_workflow(TrendAnalysisRequest(trend_topic="delivery", max_items=3))

    summary = build_management_review_summary(
        current_brief=brief,
        trend_report=trend,
    )

    assert summary.project_id == brief.project_id
    assert summary.brief_id == brief.brief_id
    assert summary.decision_outcome == "PAUSE"
    assert summary.risk_level == brief.risk_snapshot.risk_level
    assert summary.department_routing == brief.department_context.candidate_routing
    assert summary.proposed_action == trend.next_action_suggestion
    assert summary.required_review is True
    assert summary.escalation_reason is None
    assert summary.trend_provider == trend.provider
    assert summary.trend_candidate_count == len(trend.candidate_trends)
    assert summary.work_order_id is None


def test_management_review_summary_brief_hard_gate_triggers_are_sorted() -> None:
    brief = _build_brief_artifact("Sort hard gate trigger list in summary.")
    brief = brief.model_copy(
        update={
            "risk_snapshot": brief.risk_snapshot.model_copy(
                update={
                    "hard_gate_triggered": True,
                    "hard_gate_triggers": ["z_trigger", "a_trigger"],
                }
            )
        }
    )

    summary = build_management_review_summary(current_brief=brief)

    assert summary.hard_gate_triggers == ["a_trigger", "z_trigger"]
    assert summary.hard_gate_triggered is True


def _build_brief_artifact(user_request: str):
    agent = IntakeAgent()
    intake_result = agent.build_brief(user_request)
    return intake_result_to_current_brief_artifact(
        intake_result,
        brief_id="brief_summary",
        project_id="project_summary",
    )
