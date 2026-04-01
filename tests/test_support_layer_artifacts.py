import json
from pathlib import Path

from app.schemas.management import CurrentBriefArtifact
from app.services.continuation import ContinuationDecision, ContinuationRisk
from app.services.triage import EscalationReason, RoutingDepartment

_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: str) -> dict:
    return json.loads((_ROOT / path).read_text(encoding="utf-8"))


def test_support_layer_required_artifacts_exist() -> None:
    required_paths = [
        "README.md",
        "docs/architecture.md",
        "docs/implementation-plan.md",
        "docs/codex_continuation_runbook.md",
        "docs/codex_automation_prompts.md",
        "docs/current_brief_template.json",
        "docs/current_work_order_template.json",
        "docs/direction_guard.json",
        "docs/roadmap.json",
        "docs/model_routing_policy.json",
    ]

    missing = [path for path in required_paths if not (_ROOT / path).exists()]
    assert missing == []


def test_current_brief_template_validates_against_current_brief_artifact_contract() -> None:
    payload = _load_json("docs/current_brief_template.json")
    artifact = CurrentBriefArtifact.model_validate(payload)

    assert artifact.active_phase == "phase_4"
    assert artifact.department_context.origin_department == "intake_department"
    assert artifact.department_context.candidate_routing == "progress_control_department"
    assert artifact.risk_snapshot.risk_level == "low"
    assert artifact.risk_snapshot.hard_gate_triggered is False


def test_current_work_order_template_keeps_governance_decision_contract() -> None:
    payload = _load_json("docs/current_work_order_template.json")

    assert payload["assigned_department"] in {member.value for member in RoutingDepartment}
    assert payload["governance"]["decision_outcome"] in {
        member.value for member in ContinuationDecision
    }
    assert payload["governance"]["risk_level"] in {member.value for member in ContinuationRisk}
    assert payload["governance"]["escalation_reason"] in {
        member.value for member in EscalationReason
    }
    assert isinstance(payload["governance"]["hard_gate_triggers"], list)
    assert isinstance(payload["governance"]["management_review_required"], bool)
    assert isinstance(payload["verification"]["commands"], list)
    assert isinstance(payload["verification"]["expected_result"], str)
    assert payload["verification"]["expected_result"] != ""


def test_governance_json_artifacts_share_stable_decision_vocabulary() -> None:
    direction_guard = _load_json("docs/direction_guard.json")
    roadmap = _load_json("docs/roadmap.json")
    routing_policy = _load_json("docs/model_routing_policy.json")

    assert set(direction_guard["decision_values"]) == {"GO", "PAUSE", "REVIEW"}
    phase_ids = {phase["id"] for phase in roadmap["phases"]}
    assert roadmap["current_phase"] in phase_ids
    active_phase_ids = [
        phase["id"] for phase in roadmap["phases"] if phase.get("status") == "active"
    ]
    assert active_phase_ids == [roadmap["current_phase"]]

    assert "hard_gate_first" in routing_policy["principles"]
    assert (
        routing_policy["escalation_requirements"]["final_authority"] == "management_department"
    )
    assert all(model["authority"] == "advisory_only" for model in routing_policy["models"].values())


def test_support_markdown_contracts_reference_continuation_governance_artifacts() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (_ROOT / "docs/codex_continuation_runbook.md").read_text(encoding="utf-8")
    prompts = (_ROOT / "docs/codex_automation_prompts.md").read_text(encoding="utf-8")

    assert "docs/current_brief_template.json" in readme
    assert "docs/current_work_order_template.json" in readme
    assert "GO" in readme and "PAUSE" in readme and "REVIEW" in readme
    assert "docs/direction_guard.json" in runbook
    assert "docs/roadmap.json" in runbook
    assert "GO / PAUSE / REVIEW" in runbook
    assert "$continue-workflow" in prompts
    assert "If hard gate triggers, return REVIEW and stop." in prompts
