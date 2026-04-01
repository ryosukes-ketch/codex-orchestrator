# Management Readiness Artifact Consistency Checks
import json
from pathlib import Path

from app.schemas import ManagementDecisionRecord, ManagementReviewPacket, ReviewQueueItem
from app.services import run_dry_run_orchestration

# Governance Constants
SHARED_BOUNDARY_SOURCE = "docs/action_department_activation_decision_format.md"
SHARED_BOUNDARY_FLOW_REFERENCE = (
    f"`{SHARED_BOUNDARY_SOURCE}` (Shared governance boundary)."
)
SHARED_BOUNDARY_APPROVAL_REFERENCE = (
    f"follow `{SHARED_BOUNDARY_SOURCE}` (`## Shared governance boundary`)."
)
SHARED_AUTONOMOUS_NOTE = (
    "Autonomous continuation remains not approved unless explicitly approved "
    "through the required governance process."
)
SHARED_BOUNDARY_CLAUSES = [
    (
        "Activation decision artifacts are advisory-only until the required "
        "governance checkpoint is completed."
    ),
    "Unresolved blockers prevent activation from continuing.",
    (
        "A paused activation path requires blocker clearance and re-review "
        "before continuation."
    ),
    "A review path must identify an explicit escalation destination.",
    (
        "Activation approval and autonomous continuation approval are separate "
        "decisions."
    ),
    (
        "Autonomous continuation remains not approved unless explicitly approved "
        "through the required governance process."
    ),
]
LIMITED_LIVE_PROVIDER_USE_ACTIVATION_CHECKPOINT = "limited_live_provider_use_activation"
AUDIT_AND_REVIEW_DEPARTMENT = "Audit and Review Department"
VALID_DECISIONS = {"GO", "PAUSE", "REVIEW"}

# Path Constants
ACTIVATION_DECISION_EXAMPLE_PATH = (
    "docs/examples/action_department_activation_decision_example.json"
)
ACTIVATION_APPROVAL_RECORD_EXAMPLE_PATH = (
    "docs/examples/action_department_activation_approval_record_example.json"
)
ACTIVATION_APPROVAL_RECORD_PAUSE_EXAMPLE_PATH = (
    "docs/examples/action_department_activation_approval_record_pause_example.json"
)
ACTIVATION_APPROVAL_RECORD_REVIEW_EXAMPLE_PATH = (
    "docs/examples/action_department_activation_approval_record_review_example.json"
)
ACTIVATION_FLOW_EXAMPLE_PATH = "docs/examples/action_department_activation_flow_example.md"
DRY_RUN_ACTIVATION_DECISION_FLOW_EXAMPLE_PATH = (
    "docs/examples/action_department_dry_run_activation_decision_flow_example.md"
)
DRY_RUN_ACTIVATION_PAUSE_FLOW_EXAMPLE_PATH = (
    "docs/examples/action_department_dry_run_activation_pause_flow_example.md"
)
DRY_RUN_ACTIVATION_REVIEW_FLOW_EXAMPLE_PATH = (
    "docs/examples/action_department_dry_run_activation_review_flow_example.md"
)
MANAGEMENT_REVIEW_PACKET_EXAMPLE_PATH = "docs/examples/management_review_packet_example.json"
REVIEW_QUEUE_ITEM_EXAMPLE_PATH = "docs/examples/review_queue_item_example.json"
MANAGEMENT_DECISION_EXAMPLE_PATH = "docs/examples/management_decision_example.json"
MANAGEMENT_REVIEW_FLOW_EXAMPLE_PATH = "docs/examples/management_review_flow_example.md"

# Required File Groups
# Management governance and review artifacts required for baseline readiness
MANAGEMENT_REQUIRED_FILES = [
    "AGENTS.md",
    "docs/direction_guard.json",
    "docs/roadmap.json",
    "docs/management_department_runbook.md",
    "docs/management_review_template.md",
    "docs/review_decision_template.md",
    "docs/review_queue_format.md",
    "docs/management_decision_format.md",
    "docs/management_readiness_checklist.md",
    "docs/model_governance_policy.md",
    "docs/model_routing_policy.json",
    MANAGEMENT_REVIEW_PACKET_EXAMPLE_PATH,
    MANAGEMENT_REVIEW_FLOW_EXAMPLE_PATH,
    REVIEW_QUEUE_ITEM_EXAMPLE_PATH,
    MANAGEMENT_DECISION_EXAMPLE_PATH,
]
# Activation-specific governance artifacts required for manual activation checks
ACTIVATION_REQUIRED_FILES = [
    "docs/action_department_activation_decision_format.md",
    "docs/action_department_activation_approval_record_format.md",
    "docs/action_department_activation_approval_record_builder_boundary_memo.md",
    ACTIVATION_DECISION_EXAMPLE_PATH,
    ACTIVATION_APPROVAL_RECORD_EXAMPLE_PATH,
    ACTIVATION_APPROVAL_RECORD_PAUSE_EXAMPLE_PATH,
    ACTIVATION_APPROVAL_RECORD_REVIEW_EXAMPLE_PATH,
    ACTIVATION_FLOW_EXAMPLE_PATH,
]
# Dry-run flow artifacts required for simulation-path readiness coverage
DRY_RUN_REQUIRED_FILES = [
    DRY_RUN_ACTIVATION_DECISION_FLOW_EXAMPLE_PATH,
    DRY_RUN_ACTIVATION_PAUSE_FLOW_EXAMPLE_PATH,
    DRY_RUN_ACTIVATION_REVIEW_FLOW_EXAMPLE_PATH,
]


# Artifact Presence Baseline Check
def test_management_readiness_artifact_files_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    # Keep existence checks grouped by management, activation, then dry-run scope
    required_files = (
        MANAGEMENT_REQUIRED_FILES
        + ACTIVATION_REQUIRED_FILES
        + DRY_RUN_REQUIRED_FILES
    )
    missing = [path for path in required_files if not (root / path).exists()]
    assert missing == []


# Core Importability Check
def test_management_readiness_core_structures_are_importable() -> None:
    assert ManagementReviewPacket.__name__ == "ManagementReviewPacket"
    assert ReviewQueueItem.__name__ == "ReviewQueueItem"
    assert ManagementDecisionRecord.__name__ == "ManagementDecisionRecord"
    assert callable(run_dry_run_orchestration)


# Example JSON Schema and Model Validation Check
def test_management_readiness_example_json_artifacts_validate_against_models() -> None:
    root = Path(__file__).resolve().parents[1]
    management_decision_path = root / MANAGEMENT_DECISION_EXAMPLE_PATH
    review_queue_item_path = root / REVIEW_QUEUE_ITEM_EXAMPLE_PATH

    management_decision_payload = json.loads(management_decision_path.read_text(encoding="utf-8"))
    review_queue_item_payload = json.loads(review_queue_item_path.read_text(encoding="utf-8"))

    management_decision = ManagementDecisionRecord.model_validate(management_decision_payload)
    review_queue_item = ReviewQueueItem.model_validate(review_queue_item_payload)

    assert management_decision.item_id == "rq_20260325_001"
    assert review_queue_item.item_id == "rq_20260325_001"


# Management Artifact Cross-Consistency Check
def test_management_review_example_artifacts_are_cross_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    packet_path = root / MANAGEMENT_REVIEW_PACKET_EXAMPLE_PATH
    queue_path = root / REVIEW_QUEUE_ITEM_EXAMPLE_PATH
    decision_path = root / MANAGEMENT_DECISION_EXAMPLE_PATH
    flow_note_path = root / MANAGEMENT_REVIEW_FLOW_EXAMPLE_PATH

    packet = ManagementReviewPacket.model_validate(
        json.loads(packet_path.read_text(encoding="utf-8"))
    )
    queue_item = ReviewQueueItem.model_validate(json.loads(queue_path.read_text(encoding="utf-8")))
    decision = ManagementDecisionRecord.model_validate(
        json.loads(decision_path.read_text(encoding="utf-8"))
    )
    flow_note = flow_note_path.read_text(encoding="utf-8")

    assert packet.current_task == queue_item.current_task
    assert packet.risk_level == queue_item.risk_level
    assert packet.recommendation == queue_item.recommendation
    assert decision.decision == queue_item.recommendation
    assert decision.item_id == queue_item.item_id
    assert decision.related_queue_item_id == queue_item.item_id
    assert decision.related_packet_id == packet.packet_id
    assert decision.related_project_id == packet.project_id == queue_item.related_project_id
    assert (
        "Management approval outcome (`GO` / `PAUSE` / `REVIEW`) is a governance decision record."
        in flow_note
    )
    assert "Autonomous continuation eligibility is a separate check." in flow_note
    assert "Even if management outcome is `GO`" in flow_note


# Activation Artifact Consistency Check
def test_action_department_activation_artifacts_are_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    activation_format_path = root / "docs/action_department_activation_decision_format.md"
    activation_example_path = root / ACTIVATION_DECISION_EXAMPLE_PATH
    approval_record_format_path = (
        root / "docs/action_department_activation_approval_record_format.md"
    )
    approval_record_example_path = root / ACTIVATION_APPROVAL_RECORD_EXAMPLE_PATH
    approval_record_pause_example_path = root / ACTIVATION_APPROVAL_RECORD_PAUSE_EXAMPLE_PATH
    approval_record_review_example_path = root / ACTIVATION_APPROVAL_RECORD_REVIEW_EXAMPLE_PATH
    activation_flow_path = root / ACTIVATION_FLOW_EXAMPLE_PATH
    dry_run_activation_flow_path = root / DRY_RUN_ACTIVATION_DECISION_FLOW_EXAMPLE_PATH
    dry_run_activation_pause_flow_path = root / DRY_RUN_ACTIVATION_PAUSE_FLOW_EXAMPLE_PATH
    dry_run_activation_review_flow_path = root / DRY_RUN_ACTIVATION_REVIEW_FLOW_EXAMPLE_PATH
    approval_record_builder_boundary_memo_path = (
        root / "docs/action_department_activation_approval_record_builder_boundary_memo.md"
    )
    readiness_path = root / "docs/management_readiness_checklist.md"
    model_policy_path = root / "docs/model_governance_policy.md"

    activation_format = activation_format_path.read_text(encoding="utf-8")
    activation_example = json.loads(activation_example_path.read_text(encoding="utf-8"))
    approval_record_format = approval_record_format_path.read_text(encoding="utf-8")
    approval_record_example = json.loads(approval_record_example_path.read_text(encoding="utf-8"))
    approval_record_pause_example = json.loads(
        approval_record_pause_example_path.read_text(encoding="utf-8")
    )
    approval_record_review_example = json.loads(
        approval_record_review_example_path.read_text(encoding="utf-8")
    )
    activation_flow = activation_flow_path.read_text(encoding="utf-8")
    dry_run_activation_flow = dry_run_activation_flow_path.read_text(encoding="utf-8")
    dry_run_activation_pause_flow = dry_run_activation_pause_flow_path.read_text(
        encoding="utf-8"
    )
    dry_run_activation_review_flow = dry_run_activation_review_flow_path.read_text(
        encoding="utf-8"
    )
    approval_record_builder_boundary_memo = (
        approval_record_builder_boundary_memo_path.read_text(encoding="utf-8")
    )
    readiness_text = readiness_path.read_text(encoding="utf-8")
    model_policy_text = model_policy_path.read_text(encoding="utf-8")

    assert activation_example["recommendation"] in VALID_DECISIONS
    assert activation_example["autonomous_continuation_status"] != "approved"
    assert all(
        example["autonomous_continuation_note"] == SHARED_AUTONOMOUS_NOTE
        for example in [
            activation_example,
            approval_record_example,
            approval_record_pause_example,
            approval_record_review_example,
        ]
    )

    assert isinstance(activation_example["remaining_blockers"], list)
    assert isinstance(activation_example["human_approvals_recorded"], list)
    assert activation_example["human_approvals_recorded"] != []
    assert (
        activation_example["human_approvals_recorded"][0]["checkpoint"]
        == LIMITED_LIVE_PROVIDER_USE_ACTIVATION_CHECKPOINT
    )

    assert "rollback_disable_expectation" in activation_example
    assert "disable limited live provider use" in activation_example["rollback_disable_expectation"]
    assert "route work to REVIEW" in activation_example["rollback_disable_expectation"]

    assert approval_record_example["recommendation"] in VALID_DECISIONS
    assert approval_record_example["autonomous_continuation_status"] != "approved"
    assert (
        approval_record_example["autonomous_continuation_note"]
        == SHARED_AUTONOMOUS_NOTE
    )
    assert (
        approval_record_example["human_approval_status"]["checkpoint"]
        == LIMITED_LIVE_PROVIDER_USE_ACTIVATION_CHECKPOINT
    )
    assert (
        approval_record_example["management_review_status"]["review_outcome"]
        in VALID_DECISIONS
    )
    assert isinstance(approval_record_example["blocker_notes"], list)
    assert isinstance(approval_record_example["retained_constraints"], list)
    assert "advisory-only" in " ".join(approval_record_example["retained_constraints"])
    assert (
        approval_record_example["activation_target"]["department"]
        == activation_example["activation_target"]["department"]
    )
    assert (
        approval_record_example["activation_target"]["provider_use_mode"]
        == activation_example["activation_target"]["provider_use_mode"]
    )
    assert (
        approval_record_example["recommendation"] == activation_example["recommendation"]
    )
    assert "rollback_disable_expectation" in approval_record_example
    assert (
        "disable limited live provider use"
        in approval_record_example["rollback_disable_expectation"]
    )
    assert "route work to REVIEW" in approval_record_example["rollback_disable_expectation"]

    assert "`recommendation`: `GO` / `PAUSE` / `REVIEW`" in activation_format
    assert (
        "Activation approval is not equivalent to autonomous continuation approval."
        in activation_format
    )
    assert "`rollback_disable_expectation`" in activation_format
    assert "`human_approval_status`" in approval_record_format
    assert "`management_review_status`" in approval_record_format
    assert (
        "Activation approval is not equivalent to autonomous continuation approval."
        in approval_record_format
    )
    assert (
        "If blockers remain unresolved, recommendation should be `PAUSE` or `REVIEW`."
        in approval_record_format
    )
    assert SHARED_BOUNDARY_APPROVAL_REFERENCE in approval_record_format
    assert "## Lifecycle variants (manual outcomes)" in approval_record_format
    assert (
        "docs/action_department_activation_decision_format.md"
        in approval_record_builder_boundary_memo
        and "docs/action_department_activation_approval_record_format.md"
        in approval_record_builder_boundary_memo
    )

    assert "## 3) Human approval checkpoints" in activation_flow
    assert LIMITED_LIVE_PROVIDER_USE_ACTIVATION_CHECKPOINT in activation_flow
    assert "## 4) Mandatory stop / REVIEW cases" in activation_flow
    assert "Return `REVIEW` and stop when any applies:" in activation_flow
    assert "blockers are non-empty and unresolved" in activation_flow
    assert "rollback/disable expectation is missing" in activation_flow
    assert "## 7) Post-decision expectations and rollback/disable stance" in activation_flow
    assert "immediately disable limited live provider use" in activation_flow
    assert "cheap action-model suggestions remain advisory-only for risky work" in activation_flow
    assert "docs/action_department_activation_approval_record_format.md" in activation_flow
    assert ACTIVATION_APPROVAL_RECORD_EXAMPLE_PATH in activation_flow
    assert (
        "Activation approval must remain separate from autonomous continuation eligibility."
        in activation_flow
    )

    assert "Action Department limited-live provider activation gate" in readiness_text
    assert "Human approval checkpoints before activation" in readiness_text
    assert "Blockers that prevent activation" in readiness_text
    assert "Rollback / disable expectations" in readiness_text
    assert "limited live provider use is not equal to autonomous continuation" in readiness_text

    assert "Latest aliases must not self-authorize risky continuation." in model_policy_text
    assert "latest-alias outputs remain advisory-only inputs" in model_policy_text
    assert (
        all(clause in activation_format for clause in SHARED_BOUNDARY_CLAUSES)
        and all(
            SHARED_BOUNDARY_FLOW_REFERENCE in flow
            for flow in [
                dry_run_activation_flow,
                dry_run_activation_pause_flow,
                dry_run_activation_review_flow,
            ]
        )
    )
    assert ACTIVATION_DECISION_EXAMPLE_PATH in dry_run_activation_flow
    assert ACTIVATION_APPROVAL_RECORD_EXAMPLE_PATH in dry_run_activation_flow
    assert LIMITED_LIVE_PROVIDER_USE_ACTIVATION_CHECKPOINT in dry_run_activation_flow
    assert "`GO` / `PAUSE` / `REVIEW`" in dry_run_activation_flow
    assert (
        "Activation approval does not by itself grant autonomous continuation."
        in dry_run_activation_flow
    )
    assert "autonomous continuation can remain `not_approved`" in dry_run_activation_flow
    assert "advisory-only for risky work" in dry_run_activation_flow
    assert "rollback/disable expectation" in dry_run_activation_flow
    assert "hard-gate concerns are unresolved" in dry_run_activation_flow
    assert "blockers remain non-empty" in dry_run_activation_flow

    assert approval_record_pause_example["recommendation"] == "PAUSE"
    assert approval_record_pause_example["autonomous_continuation_status"] != "approved"
    assert (
        approval_record_pause_example["human_approval_status"]["checkpoint"]
        == LIMITED_LIVE_PROVIDER_USE_ACTIVATION_CHECKPOINT
    )
    assert approval_record_pause_example["management_review_status"]["review_outcome"] == "PAUSE"
    assert isinstance(approval_record_pause_example["blocker_notes"], list)
    assert approval_record_pause_example["blocker_notes"] != []
    assert all(
        example["autonomous_continuation_note"] == SHARED_AUTONOMOUS_NOTE
        for example in [
            approval_record_example,
            approval_record_pause_example,
            approval_record_review_example,
        ]
    )
    assert (
        "until blockers are resolved and re-review is completed"
        in approval_record_pause_example["rollback_disable_expectation"]
    )
    assert (
        "disabled" in approval_record_pause_example["rollback_disable_expectation"].lower()
    )

    assert approval_record_review_example["recommendation"] == "REVIEW"
    assert approval_record_review_example["autonomous_continuation_status"] != "approved"
    assert (
        approval_record_review_example["human_approval_status"]["checkpoint"]
        == LIMITED_LIVE_PROVIDER_USE_ACTIVATION_CHECKPOINT
    )
    assert (
        approval_record_review_example["management_review_status"]["review_outcome"]
        == "REVIEW"
    )
    assert isinstance(approval_record_review_example["blocker_notes"], list)
    assert approval_record_review_example["blocker_notes"] != []
    assert (
        "route all related work through review"
        in approval_record_review_example["rollback_disable_expectation"].lower()
    )
    assert ACTIVATION_DECISION_EXAMPLE_PATH in dry_run_activation_review_flow
    assert (
        ACTIVATION_APPROVAL_RECORD_REVIEW_EXAMPLE_PATH in dry_run_activation_review_flow
    )
    assert (
        LIMITED_LIVE_PROVIDER_USE_ACTIVATION_CHECKPOINT
        in dry_run_activation_review_flow
    )
    assert "Persistent blockers force `REVIEW`" in dry_run_activation_review_flow
    assert "Escalation destination must be explicit." in dry_run_activation_review_flow
    assert AUDIT_AND_REVIEW_DEPARTMENT in dry_run_activation_review_flow
    assert "remains `not_approved`" in dry_run_activation_review_flow
    assert "advisory-only for risky work" in dry_run_activation_review_flow
    assert ACTIVATION_DECISION_EXAMPLE_PATH in dry_run_activation_pause_flow
    assert ACTIVATION_APPROVAL_RECORD_PAUSE_EXAMPLE_PATH in dry_run_activation_pause_flow
    assert (
        LIMITED_LIVE_PROVIDER_USE_ACTIVATION_CHECKPOINT in dry_run_activation_pause_flow
    )
    assert (
        "Activation remains blocked while blockers are non-empty."
        in dry_run_activation_pause_flow
    )
    assert "Autonomous continuation remains `not_approved`." in dry_run_activation_pause_flow
    assert "advisory-only for risky work" in dry_run_activation_pause_flow
    assert "Require re-review" in dry_run_activation_pause_flow
    assert "escalate to `REVIEW` path" in dry_run_activation_pause_flow
    assert AUDIT_AND_REVIEW_DEPARTMENT in dry_run_activation_pause_flow
    assert (
        AUDIT_AND_REVIEW_DEPARTMENT
        in approval_record_review_example["management_review_status"]["note"]
    )
