import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_json(path: str) -> dict:
    return json.loads(_read(path))


def test_readme_and_docs_markdown_local_references_exist() -> None:
    markdown_files = [ROOT / "README.md", *sorted((ROOT / "docs").glob("**/*.md"))]
    reference_pattern = re.compile(
        r"`((?:docs|app|tests|\.env\.example|README\.md|AGENTS\.md|\.agents)"
        r"[^`\s]*\.(?:md|json|py|toml))`"
        r"|\((\.\.?/[^)\s]*\.(?:md|json|py|toml))\)"
    )

    missing: list[str] = []
    for file_path in markdown_files:
        content = file_path.read_text(encoding="utf-8")
        for match in reference_pattern.finditer(content):
            ref = match.group(1) or match.group(2)
            target = (
                (file_path.parent / ref).resolve()
                if ref.startswith("./") or ref.startswith("../")
                else ROOT / ref
            )
            if not target.exists():
                missing.append(f"{file_path.relative_to(ROOT)}::{ref}")

    assert missing == []


def test_decision_vocabulary_is_consistent_across_governance_docs() -> None:
    direction_guard = _load_json("docs/direction_guard.json")
    runbook = _read("docs/codex_continuation_runbook.md")
    prompts = _read("docs/codex_automation_prompts.md")
    readme = _read("README.md")

    assert set(direction_guard["decision_values"]) == {"GO", "PAUSE", "REVIEW"}
    assert "GO / PAUSE / REVIEW" in runbook
    assert "GO / PAUSE / REVIEW" in prompts
    assert "`GO`" in readme and "`PAUSE`" in readme and "`REVIEW`" in readme


def test_templates_and_examples_keep_expected_core_fields() -> None:
    brief_template = _load_json("docs/current_brief_template.json")
    work_order_template = _load_json("docs/current_work_order_template.json")
    review_packet_example = _load_json("docs/examples/management_review_packet_example.json")
    queue_item_example = _load_json("docs/examples/review_queue_item_example.json")
    decision_example = _load_json("docs/examples/management_decision_example.json")

    for key in ("brief_id", "project_id", "current_task", "risk_snapshot", "proposed_action"):
        assert key in brief_template
    for key in ("work_order_id", "project_id", "assigned_department", "governance", "verification"):
        assert key in work_order_template
    for key in ("packet_id", "project_id", "recommendation", "required_review"):
        assert key in review_packet_example
    for key in ("item_id", "related_project_id", "recommendation", "review_status"):
        assert key in queue_item_example
    for key in ("item_id", "decision", "reviewer_id", "rationale"):
        assert key in decision_example


def test_readme_and_runbooks_reference_existing_support_artifacts() -> None:
    readme = _read("README.md")
    runbook = _read("docs/codex_continuation_runbook.md")
    operational_runbook = _read("docs/operational_readiness_runbook.md")
    startup_runbook = _read("docs/operational_startup_runbook.md")
    prompts = _read("docs/codex_automation_prompts.md")

    assert "docs/codex_continuation_runbook.md" in readme
    assert "docs/codex_automation_prompts.md" in readme
    assert "docs/model_governance_policy.md" in readme
    assert "docs/model_routing_policy.json" in readme
    assert "docs/operator_workflow_runbook.md" in readme
    assert "docs/staging_validation_plan.md" in readme
    assert "docs/staging_execution_record.md" in readme
    assert "docs/staging_evidence_template.md" in readme
    assert "docs/staging_issue_triage_template.md" in readme
    assert "docs/staging_signoff_template.md" in readme
    assert "docs/live_validation_checklist.md" in readme
    assert "docs/rollout_plan.md" in readme
    assert "docs/rollback_checklist.md" in readme
    assert "docs/production_readiness_gaps.md" in readme
    assert "docs/system_requirements.md" in readme
    assert "docs/mvp_requirements.md" in readme
    assert "docs/pre_production_requirements.md" in readme
    assert "docs/non_goals.md" in readme
    assert "docs/requirement_traceability_matrix.md" in readme
    assert "docs/acceptance_criteria.md" in readme
    assert "docs/commercial_pilot_delivery_kit.md" in readme
    assert "docs/commercial_pilot_support_runbook.md" in readme
    assert "docs/commercial_pilot_scope_and_constraints.md" in readme
    assert "docs/commercial_pilot_acceptance_checklist.md" in readme
    assert "docs/commercial_pilot_handoff_checklist.md" in readme
    assert "docs/commercial_pilot_inquiry_template.md" in readme
    assert "docs/self_serve_distribution_kit_baseline.md" in readme
    assert "docs/self_serve_onboarding_guardrails.md" in readme
    assert "docs/self_serve_update_rollback_safety.md" in readme
    assert "docs/self_serve_support_safe_packaging.md" in readme
    assert "docs/self_serve_commercial_handoff_readiness.md" in readme
    assert "docs/self_serve_product_acceptance_checklist.md" in readme
    assert "docs/release_governance_baseline.md" in readme
    assert "docs/release_notes_template.md" in readme
    assert "docs/release_notes_phase11_example.md" in readme
    assert "docs/known_issues_register.md" in readme
    assert "docs/commercial_launch_support_boundary.md" in readme
    assert "docs/commercial_launch_sla_lite.md" in readme
    assert "docs/commercial_launch_go_no_go_checklist.md" in readme
    assert "docs/launch_week_support_trend_review.md" in readme
    assert "docs/launch_week_runbook_delta_backlog.md" in readme
    assert "docs/phase12_recurring_issue_hardening.md" in readme
    assert "docs/post_launch_issue_triage.md" in readme
    assert "docs/post_launch_priority_scoring.md" in readme
    assert "docs/known_issue_routing.md" in readme
    assert "docs/post_launch_release_backlog_flow.md" in readme
    assert "docs/release_candidate_promotion.md" in readme
    assert "docs/release_go_hold_rollback_decision.md" in readme
    assert "docs/release_note_publication_flow.md" in readme
    assert "docs/release_train_evidence_flow.md" in readme
    assert "docs/ga_launch_execution_baseline.md" in readme
    assert "docs/phase15_early_operations_stabilization.md" in readme
    assert "docs/phase15_hotfix_next_release_routing.md" in readme
    assert "docs/phase15_evidence_closure.md" in readme
    assert "docs/phase16_ga_weekly_reliability_review.md" in readme
    assert "docs/phase17_monthly_reliability_governance.md" in readme
    assert "docs/phase17_closure_sla_routing.md" in readme
    assert "docs/phase20_environment_compatibility_support.md" in readme
    assert "docs/phase21_auditability_retention_governance.md" in readme
    assert "docs/phase22_steady_state_operations_closure.md" in readme
    assert "docs/steady_state_operations_handbook.md" in readme
    assert "docs/release_ops_cadence_baseline.md" in readme
    assert "docs/steady_state_improvement_backlog.md" in readme
    assert "docs/steady_state_burndown_tracking.md" in readme
    assert "docs/steady_state_checkpoint_refresh.md" in readme
    assert "docs/steady_state_watchlist_owner_ack.json" in readme
    assert "docs/direction_guard.json" in runbook
    assert "docs/roadmap.json" in runbook
    assert "docs/operator_workflow_runbook.md" in operational_runbook
    assert "self-serve-update-guard.ps1" in operational_runbook
    assert "self-serve-support-intake.ps1" in operational_runbook
    assert "self-serve-handoff-package.ps1" in operational_runbook
    assert "scripts\\refresh-openapi.ps1" in readme
    assert "scripts\\refresh-openapi.ps1" in startup_runbook
    assert "scripts\\openclaw-gateway-check.ps1" in readme
    assert "openclaw-evidence-capture.ps1" in readme
    assert "operator-stage-report.ps1" in readme
    assert "operator-audit-assert.ps1" in readme
    assert "operator-full-cycle.ps1" in readme
    assert "operator-cycle-suite.ps1" in readme
    assert "operator-handoff-envelope.ps1" in readme
    assert "operator-stage-gate.ps1" in readme
    assert "operator-replay-export.ps1" in readme
    assert "operator-support-bundle.ps1" in readme
    assert "launch-week-trend-review.ps1" in readme
    assert "support-recurring-hardening.ps1" in readme
    assert "post-launch-triage.ps1" in readme
    assert "post-launch-priority-score.ps1" in readme
    assert "known-issue-route.ps1" in readme
    assert "post-launch-backlog-export.ps1" in readme
    assert "release-candidate-promote.ps1" in readme
    assert "release-decision-package.ps1" in readme
    assert "release-notes-assemble.ps1" in readme
    assert "known-issue-publication-route.ps1" in readme
    assert "release-train-evidence-export.ps1" in readme
    assert "ga-launch-package-execute.ps1" in readme
    assert "early-ops-incident-loop.ps1" in readme
    assert "hotfix-next-release-route.ps1" in readme
    assert "phase15-evidence-closeout.ps1" in readme
    assert "ga-weekly-reliability-review.ps1" in readme
    assert "ga-monthly-reliability-targets.ps1" in readme
    assert "ga-closure-sla-breach-route.ps1" in readme
    assert "ga-quarterly-reliability-governance.ps1" in readme
    assert "ga-quarterly-closure-sla-ownership.ps1" in readme
    assert "ga-quarterly-review-package.ps1" in readme
    assert "ga-upgrade-impact-matrix.ps1" in readme
    assert "ga-migration-rehearsal-package.ps1" in readme
    assert "ga-upgrade-rollback-safety.ps1" in readme
    assert "ga-upgrade-evidence-closeout.ps1" in readme
    assert "ga-supported-environment-matrix.ps1" in readme
    assert "ga-compatibility-preflight.ps1" in readme
    assert "ga-support-intake-normalization.ps1" in readme
    assert "ga-environment-support-closeout.ps1" in readme
    assert "ga-artifact-retention-coverage.ps1" in readme
    assert "ga-audit-traceability-index.ps1" in readme
    assert "ga-incident-change-ledger.ps1" in readme
    assert "ga-auditability-closeout.ps1" in readme
    assert "ga-steady-state-operations-handbook.ps1" in readme
    assert "ga-release-ops-cadence-baseline.ps1" in readme
    assert "ga-end-to-end-operations-evidence.ps1" in readme
    assert "ga-steady-state-closeout.ps1" in readme
    assert "ga-steady-state-improvement-backlog.ps1" in readme
    assert "ga-steady-state-burndown.ps1" in readme
    assert "ga-steady-state-checkpoint-refresh.ps1" in readme
    assert "ga-steady-state-escalation-watchlist-route.ps1" in readme
    assert "sqlite-backup.ps1" in readme
    assert "sqlite-restore.ps1" in readme
    assert "sqlite-verify.ps1" in readme
    assert "sqlite-export.ps1" in readme
    assert "self-serve-preflight.ps1" in readme
    assert "self-serve-update-guard.ps1" in readme
    assert "self-serve-support-intake.ps1" in readme
    assert "self-serve-handoff-package.ps1" in readme
    assert "-AuditJsonPath" in readme
    assert "-NoEventDerivedTelemetry" in readme
    assert "-SummaryOutPath" in readme
    assert "status-summary.json" in readme
    assert "bundle-manifest.json" in readme
    assert "readiness-manifest-" in readme
    assert "readiness-summary-" in readme
    assert "operator-menu.ps1" in readme
    assert "Readiness Replay Summary" in readme
    assert "legacy_fallback_normalizations" in readme
    assert "-BundleManifestPath" in readme
    assert "operator-status.ps1 -BundleManifestPath" in readme
    assert "operator-stage-report.ps1 -BundleManifestPath" in readme
    assert "operator-audit-assert.ps1 -BundleManifestPath" in readme
    assert "-RunOpenClawGatewayCheck" in readme
    assert "-OperatorMaxLlmTransportFallbacks" in readme
    assert "openclaw-gateway-check.ps1" in startup_runbook
    assert "openclaw-evidence-capture.ps1" in startup_runbook
    assert "operator-full-cycle.ps1" in startup_runbook
    assert "operator-cycle-suite.ps1" in startup_runbook
    assert "operator-stage-gate.ps1" in startup_runbook
    assert "operator-replay-export.ps1" in startup_runbook
    assert "operator-support-bundle.ps1" in startup_runbook
    assert "launch-week-trend-review.ps1" in startup_runbook
    assert "support-recurring-hardening.ps1" in startup_runbook
    assert "post-launch-triage.ps1" in startup_runbook
    assert "post-launch-priority-score.ps1" in startup_runbook
    assert "known-issue-route.ps1" in startup_runbook
    assert "post-launch-backlog-export.ps1" in startup_runbook
    assert "release-candidate-promote.ps1" in startup_runbook
    assert "release-decision-package.ps1" in startup_runbook
    assert "release-notes-assemble.ps1" in startup_runbook
    assert "known-issue-publication-route.ps1" in startup_runbook
    assert "release-train-evidence-export.ps1" in startup_runbook
    assert "ga-launch-package-execute.ps1" in startup_runbook
    assert "early-ops-incident-loop.ps1" in startup_runbook
    assert "hotfix-next-release-route.ps1" in startup_runbook
    assert "phase15-evidence-closeout.ps1" in startup_runbook
    assert "ga-weekly-reliability-review.ps1" in startup_runbook
    assert "ga-monthly-reliability-targets.ps1" in startup_runbook
    assert "ga-closure-sla-breach-route.ps1" in startup_runbook
    assert "ga-quarterly-reliability-governance.ps1" in startup_runbook
    assert "ga-quarterly-closure-sla-ownership.ps1" in startup_runbook
    assert "ga-quarterly-review-package.ps1" in startup_runbook
    assert "ga-upgrade-impact-matrix.ps1" in startup_runbook
    assert "ga-migration-rehearsal-package.ps1" in startup_runbook
    assert "ga-upgrade-rollback-safety.ps1" in startup_runbook
    assert "ga-upgrade-evidence-closeout.ps1" in startup_runbook
    assert "ga-supported-environment-matrix.ps1" in startup_runbook
    assert "ga-compatibility-preflight.ps1" in startup_runbook
    assert "ga-support-intake-normalization.ps1" in startup_runbook
    assert "ga-environment-support-closeout.ps1" in startup_runbook
    assert "ga-artifact-retention-coverage.ps1" in startup_runbook
    assert "ga-audit-traceability-index.ps1" in startup_runbook
    assert "ga-incident-change-ledger.ps1" in startup_runbook
    assert "ga-auditability-closeout.ps1" in startup_runbook
    assert "ga-steady-state-operations-handbook.ps1" in startup_runbook
    assert "ga-release-ops-cadence-baseline.ps1" in startup_runbook
    assert "ga-end-to-end-operations-evidence.ps1" in startup_runbook
    assert "ga-steady-state-closeout.ps1" in startup_runbook
    assert "ga-steady-state-improvement-backlog.ps1" in startup_runbook
    assert "ga-steady-state-burndown.ps1" in startup_runbook
    assert "ga-steady-state-checkpoint-refresh.ps1" in startup_runbook
    assert "ga-steady-state-escalation-watchlist-route.ps1" in startup_runbook
    assert "steady_state_watchlist_owner_ack.json" in startup_runbook
    assert "-AuditJsonPath" in startup_runbook
    assert "-NoEventDerivedTelemetry" in startup_runbook
    assert "-SummaryOutPath" in startup_runbook
    assert "status-summary.json" in startup_runbook
    assert "bundle-manifest.json" in startup_runbook
    assert "readiness-manifest-" in startup_runbook
    assert "readiness-summary-" in startup_runbook
    assert "-BundleManifestPath" in startup_runbook
    assert "-RunOperatorSuite" in startup_runbook
    assert "-OperatorRequireStageTelemetry" in startup_runbook
    assert "-OperatorMaxLlmTransportFallbacks" in startup_runbook
    assert "-OperatorAuthorizationOperator" in startup_runbook
    assert "-RunOpenClawGatewayCheck" in startup_runbook
    assert "openclaw-gateway-check.ps1" in operational_runbook
    assert "openclaw-evidence-capture.ps1" in operational_runbook
    assert "operator-stage-report.ps1" in operational_runbook
    assert "operator-audit-assert.ps1" in operational_runbook
    assert "operator-full-cycle.ps1" in operational_runbook
    assert "operator-cycle-suite.ps1" in operational_runbook
    assert "operator-stage-gate.ps1" in operational_runbook
    assert "operator-replay-export.ps1" in operational_runbook
    assert "operator-support-bundle.ps1" in operational_runbook
    assert "launch-week-trend-review.ps1" in operational_runbook
    assert "support-recurring-hardening.ps1" in operational_runbook
    assert "post-launch-triage.ps1" in operational_runbook
    assert "post-launch-priority-score.ps1" in operational_runbook
    assert "known-issue-route.ps1" in operational_runbook
    assert "post-launch-backlog-export.ps1" in operational_runbook
    assert "release-candidate-promote.ps1" in operational_runbook
    assert "release-decision-package.ps1" in operational_runbook
    assert "release-notes-assemble.ps1" in operational_runbook
    assert "known-issue-publication-route.ps1" in operational_runbook
    assert "release-train-evidence-export.ps1" in operational_runbook
    assert "ga-launch-package-execute.ps1" in operational_runbook
    assert "early-ops-incident-loop.ps1" in operational_runbook
    assert "hotfix-next-release-route.ps1" in operational_runbook
    assert "phase15-evidence-closeout.ps1" in operational_runbook
    assert "ga-weekly-reliability-review.ps1" in operational_runbook
    assert "ga-monthly-reliability-targets.ps1" in operational_runbook
    assert "ga-closure-sla-breach-route.ps1" in operational_runbook
    assert "ga-quarterly-reliability-governance.ps1" in operational_runbook
    assert "ga-quarterly-closure-sla-ownership.ps1" in operational_runbook
    assert "ga-quarterly-review-package.ps1" in operational_runbook
    assert "ga-upgrade-impact-matrix.ps1" in operational_runbook
    assert "ga-migration-rehearsal-package.ps1" in operational_runbook
    assert "ga-upgrade-rollback-safety.ps1" in operational_runbook
    assert "ga-upgrade-evidence-closeout.ps1" in operational_runbook
    assert "ga-supported-environment-matrix.ps1" in operational_runbook
    assert "ga-compatibility-preflight.ps1" in operational_runbook
    assert "ga-support-intake-normalization.ps1" in operational_runbook
    assert "ga-environment-support-closeout.ps1" in operational_runbook
    assert "ga-artifact-retention-coverage.ps1" in operational_runbook
    assert "ga-audit-traceability-index.ps1" in operational_runbook
    assert "ga-incident-change-ledger.ps1" in operational_runbook
    assert "ga-auditability-closeout.ps1" in operational_runbook
    assert "ga-steady-state-operations-handbook.ps1" in operational_runbook
    assert "ga-release-ops-cadence-baseline.ps1" in operational_runbook
    assert "ga-end-to-end-operations-evidence.ps1" in operational_runbook
    assert "ga-steady-state-closeout.ps1" in operational_runbook
    assert "ga-steady-state-improvement-backlog.ps1" in operational_runbook
    assert "ga-steady-state-burndown.ps1" in operational_runbook
    assert "ga-steady-state-checkpoint-refresh.ps1" in operational_runbook
    assert "ga-steady-state-escalation-watchlist-route.ps1" in operational_runbook
    assert "steady_state_watchlist_owner_ack.json" in operational_runbook
    assert "-AuditJsonPath" in operational_runbook
    assert "-NoEventDerivedTelemetry" in operational_runbook
    assert "-SummaryOutPath" in operational_runbook
    assert "status-summary.json" in operational_runbook
    assert "bundle-manifest.json" in operational_runbook
    assert "readiness-manifest-" in operational_runbook
    assert "readiness-summary-" in operational_runbook
    assert "operator-menu.ps1" in operational_runbook
    assert "-BundleManifestPath" in operational_runbook
    assert "operator-status.ps1 -BundleManifestPath" in operational_runbook
    assert "operator-audit.ps1 -BundleManifestPath" in operational_runbook
    assert "operator-stage-report.ps1 -BundleManifestPath" in operational_runbook
    assert "operator-audit-assert.ps1 -BundleManifestPath" in operational_runbook
    assert "stage_failure_reason" in operational_runbook
    assert "-RunOperatorSuite" in operational_runbook
    assert "-OperatorRequireStageTelemetry" in operational_runbook
    assert "-OperatorMaxLlmTransportFallbacks" in operational_runbook
    assert "-OperatorMaxRevisionReplanAttempts" in operational_runbook
    assert "-OperatorAuthorizationOperator" in operational_runbook
    assert "-OperatorRequirePolicyAssertions" in operational_runbook
    assert "-OperatorRequireAuthEvidence" in operational_runbook
    assert "-OperatorExpectedAuthRoles" in operational_runbook
    assert "-OperatorAuthPolicyMode" in operational_runbook
    assert "-OperatorBreakglass" in operational_runbook
    assert "-OperatorBreakglassReason" in operational_runbook
    assert "-OperatorBreakglassActor" in operational_runbook
    assert "-OperatorPolicyMode" in operational_runbook
    assert "-OperatorEnforceModelAllowlist" in operational_runbook
    assert "-OperatorFailOnBackendOverrideMismatch" in operational_runbook
    assert "-OperatorSkipApprovalMode" in operational_runbook
    assert "-OperatorSkipRejectReplanMode" in operational_runbook
    assert "deny_reasons" in operational_runbook
    assert "-RunOpenClawGatewayCheck" in operational_runbook
    assert "-OperatorRequireAuthEvidence" in readme
    assert "-OperatorMaxRevisionReplanAttempts" in readme
    assert "-OperatorAuthorizationOperator" in readme
    assert "-OperatorExpectedAuthRoles" in readme
    assert "-OperatorAuthPolicyMode" in readme
    assert "-OperatorBreakglass" in readme
    assert "-OperatorBreakglassReason" in readme
    assert "-OperatorBreakglassActor" in readme
    assert "-OperatorRequireAuthEvidence" in startup_runbook
    assert "-OperatorMaxRevisionReplanAttempts" in startup_runbook
    assert "-OperatorExpectedAuthRoles" in startup_runbook
    assert "-OperatorAuthPolicyMode" in startup_runbook
    assert "-OperatorBreakglass" in startup_runbook
    assert "-OperatorBreakglassReason" in startup_runbook
    assert "-OperatorBreakglassActor" in startup_runbook
    assert "$continue-workflow" in prompts


def test_requirements_package_docs_exist_and_traceability_mentions_core_artifacts() -> None:
    required_docs = [
        "docs/system_requirements.md",
        "docs/mvp_requirements.md",
        "docs/pre_production_requirements.md",
        "docs/non_goals.md",
        "docs/requirement_traceability_matrix.md",
        "docs/acceptance_criteria.md",
    ]
    for path in required_docs:
        assert (ROOT / path).exists(), path

    traceability = _read("docs/requirement_traceability_matrix.md")
    expected_artifact_terms = [
        "current brief",
        "triage result",
        "trend report",
        "work order",
        "management summary",
        "projected activation decision",
        "approval record",
        "handoff envelope",
    ]
    for term in expected_artifact_terms:
        assert term in traceability, term

    acceptance = _read("docs/acceptance_criteria.md")
    assert "AC-1 Code and logic readiness (offline)" in acceptance
    assert "AC-2 Offline operational readiness" in acceptance
    assert "AC-3 Staging entry criteria" in acceptance
    assert "AC-4 Live validation entry criteria" in acceptance


def test_release_governance_docs_exist_and_include_required_terms() -> None:
    for path in (
        "docs/release_governance_baseline.md",
        "docs/release_notes_template.md",
        "docs/release_notes_phase11_example.md",
        "docs/known_issues_register.md",
        "docs/commercial_launch_support_boundary.md",
        "docs/commercial_launch_sla_lite.md",
        "docs/commercial_launch_go_no_go_checklist.md",
    ):
        assert (ROOT / path).exists(), path

    governance = _read("docs/release_governance_baseline.md")
    notes_template = _read("docs/release_notes_template.md")
    notes_example = _read("docs/release_notes_phase11_example.md")
    known_issues = _read("docs/known_issues_register.md")
    support_boundary = _read("docs/commercial_launch_support_boundary.md")
    sla_lite = _read("docs/commercial_launch_sla_lite.md")
    go_no_go = _read("docs/commercial_launch_go_no_go_checklist.md")

    assert "release_version" in governance
    assert "rollback_signal" in governance
    assert "docs/rollback_checklist.md" in governance
    assert "scripts/self-serve-update-guard.ps1" in governance
    assert "Decision" in notes_template
    assert "GO" in notes_template and "PAUSE" in notes_template and "REVIEW" in notes_template
    assert "Decision" in notes_example and "GO" in notes_example
    assert "operator" in support_boundary and "support_owner" in support_boundary
    assert "P1" in sla_lite and "P2" in sla_lite and "P3" in sla_lite
    assert "GO" in go_no_go and "PAUSE" in go_no_go and "REVIEW" in go_no_go
    assert "Status vocabulary" in known_issues
    assert "open" in known_issues and "resolved" in known_issues and "mitigated" in known_issues


def test_staging_execution_support_docs_exist_and_include_expected_sections() -> None:
    execution_record = _read("docs/staging_execution_record.md")
    evidence = _read("docs/staging_evidence_template.md")
    triage = _read("docs/staging_issue_triage_template.md")
    signoff = _read("docs/staging_signoff_template.md")

    for path in (
        "docs/staging_execution_record.md",
        "docs/staging_evidence_template.md",
        "docs/staging_issue_triage_template.md",
        "docs/staging_signoff_template.md",
    ):
        assert (ROOT / path).exists(), path

    assert "## Step-by-step log" in execution_record
    assert "## Final staging recommendation" in execution_record

    for heading in (
        "### 1. Startup",
        "### 2. Auth",
        "### 3. Provider",
        "### 4. Persistence",
        "### 5. Manual workflow",
        "### 6. Rollback",
    ):
        assert heading in evidence

    assert "- Severity: P0 / P1 / P2 / P3" in triage
    assert "## Go/No-Go effect" in triage

    assert "### Auth signoff" in signoff
    assert "### Provider signoff" in signoff
    assert "### Persistence signoff" in signoff
    assert "### Rollback signoff" in signoff
    assert "## Final release decision" in signoff


def test_operator_workflow_assets_exist_and_sample_brief_has_required_fields() -> None:
    required_paths = [
        "docs/operator_workflow_runbook.md",
        "examples/briefs/sample_brief.json",
        "examples/briefs/phase6_real_brief.json",
        "scripts/test-targets.ps1",
        "scripts/refresh-openapi.ps1",
        "scripts/operator-run.ps1",
        "scripts/operator-status.ps1",
        "scripts/operator-approve.ps1",
        "scripts/operator-reject.ps1",
        "scripts/operator-revise.ps1",
        "scripts/operator-replan.ps1",
        "scripts/operator-audit.ps1",
        "scripts/operator-stage-report.ps1",
        "scripts/operator-audit-assert.ps1",
        "scripts/operator-full-cycle.ps1",
        "scripts/operator-cycle-suite.ps1",
        "scripts/operator-handoff-envelope.ps1",
        "scripts/operator-stage-gate.ps1",
        "scripts/operator-replay-export.ps1",
        "scripts/operator-support-bundle.ps1",
        "scripts/launch-week-trend-review.ps1",
        "scripts/support-recurring-hardening.ps1",
        "scripts/post-launch-triage.ps1",
        "scripts/post-launch-priority-score.ps1",
        "scripts/known-issue-route.ps1",
        "scripts/post-launch-backlog-export.ps1",
        "scripts/release-candidate-promote.ps1",
        "scripts/release-decision-package.ps1",
        "scripts/release-notes-assemble.ps1",
        "scripts/known-issue-publication-route.ps1",
        "scripts/release-train-evidence-export.ps1",
        "scripts/ga-launch-package-execute.ps1",
        "scripts/operator-menu.ps1",
        "scripts/openclaw-gateway-check.ps1",
        "scripts/openclaw-evidence-capture.ps1",
        "scripts/sqlite-backup.ps1",
        "scripts/sqlite-restore.ps1",
        "scripts/sqlite-verify.ps1",
        "scripts/sqlite-export.ps1",
        "scripts/self-serve-preflight.ps1",
        "scripts/self-serve-update-guard.ps1",
        "scripts/self-serve-support-intake.ps1",
        "scripts/self-serve-handoff-package.ps1",
    ]
    for path in required_paths:
        assert (ROOT / path).exists(), path

    sample = _load_json("examples/briefs/sample_brief.json")
    for key in ("objective", "raw_request"):
        assert key in sample

    runbook = _read("docs/operator_workflow_runbook.md")
    assert "waiting_approval" in runbook
    assert "revision_requested" in runbook
    assert "ready_for_planning" in runbook
    assert "completed" in runbook
    assert "Department Stage Summary" in runbook
    assert "operator-stage-report.ps1" in runbook
    assert "operator-audit-assert.ps1" in runbook
    assert "operator-full-cycle.ps1" in runbook
    assert "operator-cycle-suite.ps1" in runbook
    assert "operator-handoff-envelope.ps1" in runbook
    assert "operator-stage-gate.ps1" in runbook
    assert "operator-replay-export.ps1" in runbook
    assert "operator-support-bundle.ps1" in runbook
    assert "openclaw-evidence-capture.ps1" in runbook
    assert "sqlite-backup.ps1" in runbook
    assert "sqlite-restore.ps1" in runbook
    assert "sqlite-verify.ps1" in runbook
    assert "sqlite-export.ps1" in runbook
    assert "operator-support-bundle.ps1" in runbook
    assert "-AuditJsonPath" in runbook
    assert "-NoEventDerivedTelemetry" in runbook
    assert "-SummaryOutPath" in runbook
    assert "status-summary.json" in runbook
    assert "bundle-manifest.json" in runbook
    assert "-BundleManifestPath" in runbook
    assert "operator-status.ps1 -BundleManifestPath" in runbook
    assert "operator-audit.ps1 -BundleManifestPath" in runbook
    assert "operator-stage-report.ps1 -BundleManifestPath" in runbook
    assert "operator-audit-assert.ps1 -BundleManifestPath" in runbook
    assert "models_probe_status_code" in runbook
    assert "telemetry_legacy_fallback_normalizations" in runbook
    assert "Readiness Replay Summary" in runbook
    assert "phase6_real_brief.json" in runbook
    assert "Failure categories" in runbook
    assert "provider_auth" in runbook
    assert "launch-week-trend-review.ps1" in runbook
    assert "support-recurring-hardening.ps1" in runbook
    assert "post-launch-triage.ps1" in runbook
    assert "post-launch-priority-score.ps1" in runbook
    assert "known-issue-route.ps1" in runbook
    assert "post-launch-backlog-export.ps1" in runbook
    assert "release-candidate-promote.ps1" in runbook
    assert "release-decision-package.ps1" in runbook
    assert "release-notes-assemble.ps1" in runbook
    assert "known-issue-publication-route.ps1" in runbook
    assert "release-train-evidence-export.ps1" in runbook


def test_env_example_uses_placeholders_and_expected_keys() -> None:
    env_text = _read(".env.example")
    required_keys = {
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GROK_API_KEY",
        "OPENCLAW_BASE_URL",
        "OPENCLAW_TIMEOUT_SECONDS",
        "OPENCLAW_MAX_RETRIES",
        "OPENCLAW_RETRY_BACKOFF_SECONDS",
        "OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS",
        "OPENCLAW_GATEWAY_PROBE_TIMEOUT_SECONDS",
        "STATE_BACKEND",
        "SQLITE_DB_PATH",
        "SQLITE_BACKUP_DIR",
        "DATABASE_URL",
        "STATE_BACKEND_STRICT",
        "TREND_PROVIDER_STRICT",
        "AUTH_SERVICE_MODE",
        "AUTH_ENABLED",
        "AUTH_TOKEN_SEED",
        "DEV_AUTH_ENABLED",
        "DEV_AUTH_TOKEN_SEED",
        "OPERATOR_API_TIMEOUT_SECONDS",
        "TEST_DATABASE_URL",
    }
    parsed = {}
    for line in env_text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()

    assert required_keys.issubset(set(parsed))
    assert parsed["OPENAI_API_KEY"] == "your_openai_api_key_here"
    assert parsed["GEMINI_API_KEY"] == "your_gemini_api_key_here"
    assert parsed["GROK_API_KEY"] == "your_grok_api_key_here"
    assert parsed["TREND_PROVIDER_STRICT"] == "false"

    combined_values = "\n".join(parsed.values())
    secret_like_patterns = [r"\bsk-proj-", r"\bAIza", r"\bxai-", r"\bsk-ant-"]
    assert all(re.search(pattern, combined_values) is None for pattern in secret_like_patterns)


def test_commercial_auth_env_sample_exists_and_is_cross_linked() -> None:
    sample_path = ROOT / "examples/env/commercial_auth_minimal.env"
    assert sample_path.exists()

    sample_text = sample_path.read_text(encoding="utf-8")
    assert "AUTH_SERVICE_MODE=commercial_token" in sample_text
    assert "AUTH_ENABLED=true" in sample_text
    assert "AUTH_TOKEN_SEED=" in sample_text

    readme = _read("README.md")
    readiness_runbook = _read("docs/operational_readiness_runbook.md")
    startup_runbook = _read("docs/operational_startup_runbook.md")

    assert ".\\examples\\env\\commercial_auth_minimal.env" in readme
    assert ".\\examples\\env\\commercial_auth_minimal.env" in readiness_runbook
    assert ".\\examples\\env\\commercial_auth_minimal.env" in startup_runbook


def test_sqlite_operational_policy_is_explicit_and_consistent_across_docs() -> None:
    readme = _read("README.md")
    readiness_runbook = _read("docs/operational_readiness_runbook.md")
    operator_runbook = _read("docs/operator_workflow_runbook.md")
    startup_runbook = _read("docs/operational_startup_runbook.md")
    env_text = _read(".env.example")

    assert "## SQLite operational policy (local ops)" in readme
    assert "STATE_BACKEND=sqlite" in readme
    assert "STATE_BACKEND_STRICT=true" in readme
    assert "not treated as a production-grade" in readme
    assert "SQLITE_BACKUP_DIR" in readme
    assert "OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS" in readme
    assert "OPERATOR_API_TIMEOUT_SECONDS" in readme
    assert "sqlite-backup.ps1" in readme
    assert "sqlite-restore.ps1" in readme
    assert "sqlite-verify.ps1" in readme
    assert "sqlite-export.ps1" in readme

    assert "## 9. SQLite policy for local operation" in readiness_runbook
    assert "STATE_BACKEND=sqlite" in readiness_runbook
    assert "STATE_BACKEND_STRICT=true" in readiness_runbook
    assert "not a substitute for production-grade" in readiness_runbook
    assert "OPERATOR_API_TIMEOUT_SECONDS" in readiness_runbook
    assert "sqlite-backup.ps1" in readiness_runbook
    assert "sqlite-restore.ps1" in readiness_runbook
    assert "sqlite-verify.ps1" in readiness_runbook
    assert "sqlite-export.ps1" in readiness_runbook
    assert "operator-replay-export.ps1" in readiness_runbook

    assert "Local operation scope:" in operator_runbook
    assert "single-operator use" in operator_runbook
    assert "not optimized for high-concurrency" in operator_runbook
    assert "OPERATOR_API_TIMEOUT_SECONDS" in operator_runbook
    assert "-TimeoutSec" in operator_runbook
    assert "self-serve-update-guard.ps1" in operator_runbook
    assert "self-serve-support-intake.ps1" in operator_runbook
    assert "self-serve-handoff-package.ps1" in operator_runbook

    assert "## Recommended local startup profile" in startup_runbook
    assert "STATE_BACKEND=sqlite" in startup_runbook
    assert "STATE_BACKEND_STRICT=true" in startup_runbook
    assert "not treat SQLite local profile as production database validation" in startup_runbook
    assert "SQLITE_BACKUP_DIR" in startup_runbook
    assert "OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS" in startup_runbook
    assert "OPERATOR_API_TIMEOUT_SECONDS" in startup_runbook
    assert "sqlite-backup.ps1" in startup_runbook
    assert "sqlite-restore.ps1" in startup_runbook
    assert "sqlite-verify.ps1" in startup_runbook
    assert "sqlite-export.ps1" in startup_runbook
    assert "self-serve-preflight.ps1" in startup_runbook
    assert "self-serve-update-guard.ps1" in startup_runbook
    assert "self-serve-support-intake.ps1" in startup_runbook
    assert "self-serve-handoff-package.ps1" in startup_runbook
    assert "operator-replay-export.ps1" in startup_runbook
    assert "stage_failure_reason" in startup_runbook

    parsed = {}
    for line in env_text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    assert parsed.get("STATE_BACKEND") == "sqlite"
    assert parsed.get("STATE_BACKEND_STRICT") == "true"
    assert parsed.get("SQLITE_BACKUP_DIR") == "logs/sqlite-backups"


def test_commercial_pilot_package_docs_exist_and_are_cross_linked() -> None:
    delivery_kit = _read("docs/commercial_pilot_delivery_kit.md")
    support_runbook = _read("docs/commercial_pilot_support_runbook.md")
    scope_doc = _read("docs/commercial_pilot_scope_and_constraints.md")
    acceptance = _read("docs/commercial_pilot_acceptance_checklist.md")
    handoff = _read("docs/commercial_pilot_handoff_checklist.md")
    inquiry = _read("docs/commercial_pilot_inquiry_template.md")
    readme = _read("README.md")
    readiness = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")

    for path in (
        "docs/commercial_pilot_delivery_kit.md",
        "docs/commercial_pilot_support_runbook.md",
        "docs/commercial_pilot_scope_and_constraints.md",
        "docs/commercial_pilot_acceptance_checklist.md",
        "docs/commercial_pilot_handoff_checklist.md",
        "docs/commercial_pilot_inquiry_template.md",
    ):
        assert (ROOT / path).exists(), path

    assert "docs/commercial_pilot_support_runbook.md" in delivery_kit
    assert "scripts\\release-readiness.ps1" in delivery_kit
    assert "scripts\\operator-support-bundle.ps1" in delivery_kit
    assert "failure-classification.json" in support_runbook
    assert "runtime" in support_runbook and "provider_auth" in support_runbook
    assert "out-of-scope" in scope_doc
    assert "Decision: Go / Conditional Go / No-Go" in acceptance
    assert "docs/commercial_pilot_inquiry_template.md" in handoff
    assert "classification hint" in inquiry.lower()

    assert "docs/commercial_pilot_delivery_kit.md" in readme
    assert "docs/commercial_pilot_delivery_kit.md" in readiness
    assert "docs/commercial_pilot_delivery_kit.md" in startup
    assert "docs/commercial_pilot_delivery_kit.md" in operator


def test_self_serve_phase10_docs_exist_and_cover_baseline_controls() -> None:
    distribution = _read("docs/self_serve_distribution_kit_baseline.md")
    guardrails = _read("docs/self_serve_onboarding_guardrails.md")
    rollback = _read("docs/self_serve_update_rollback_safety.md")
    support_safe = _read("docs/self_serve_support_safe_packaging.md")
    handoff = _read("docs/self_serve_commercial_handoff_readiness.md")
    acceptance = _read("docs/self_serve_product_acceptance_checklist.md")
    readme = _read("README.md")
    direction_guard = _load_json("docs/direction_guard.json")
    roadmap = _load_json("docs/roadmap.json")

    for path in (
        "docs/self_serve_distribution_kit_baseline.md",
        "docs/self_serve_onboarding_guardrails.md",
        "docs/self_serve_update_rollback_safety.md",
        "docs/self_serve_support_safe_packaging.md",
        "docs/self_serve_commercial_handoff_readiness.md",
        "docs/self_serve_product_acceptance_checklist.md",
        "scripts/self-serve-preflight.ps1",
        "scripts/self-serve-update-guard.ps1",
        "scripts/self-serve-support-intake.ps1",
        "scripts/self-serve-handoff-package.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "release-readiness.ps1" in distribution
    assert "strict completed-only semantics" in distribution
    assert "self-serve-preflight.ps1" in distribution
    assert "self-serve-update-guard.ps1" in distribution
    assert "self-serve-support-intake.ps1" in distribution
    assert "self-serve-handoff-package.ps1" in distribution
    assert "preflight.ps1" in guardrails
    assert "self-serve-preflight.ps1" in guardrails
    assert "sqlite-verify.ps1" in guardrails
    assert "sqlite-backup.ps1" in rollback
    assert "sqlite-restore.ps1" in rollback
    assert "self-serve-update-guard.ps1" in rollback
    assert "self-serve-support-intake.ps1" in support_safe
    assert "operator-support-bundle.ps1" in support_safe
    assert "self-serve-handoff-package.ps1" in handoff
    assert "ready_for_handoff" in handoff
    assert "self-serve-preflight.ps1" in acceptance
    assert "self-serve-handoff-package.ps1" in acceptance

    assert "docs/self_serve_distribution_kit_baseline.md" in readme
    assert direction_guard["active_phase"] == roadmap["current_phase"]
    assert direction_guard["active_phase"] in {
        "phase_20",
        "phase_21",
        "phase_22",
        "steady_state",
    }
    assert any(
        phase.get("id") == "phase_10" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_11" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_12" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_13" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_14" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_15" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_16" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_17" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_18" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_19" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_20" and phase.get("status") in {"active", "done"}
        for phase in roadmap["phases"]
    )


def test_phase12_launch_week_docs_exist_and_are_cross_linked() -> None:
    trend_review = _read("docs/launch_week_support_trend_review.md")
    backlog = _read("docs/launch_week_runbook_delta_backlog.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")
    support = _read("docs/commercial_pilot_support_runbook.md")

    for path in (
        "docs/launch_week_support_trend_review.md",
        "docs/launch_week_runbook_delta_backlog.md",
        "docs/phase12_recurring_issue_hardening.md",
        "scripts/launch-week-trend-review.ps1",
        "scripts/support-recurring-hardening.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "support_bundle_count" in trend_review
    assert "Top recurring categories" in trend_review
    assert "runbook delta" in trend_review.lower()
    assert "Backlog items" in backlog
    assert "source_trend_manifest" in backlog
    hardening = _read("docs/phase12_recurring_issue_hardening.md")
    assert "Recurring Issue Pattern Hardening" in hardening
    assert "hardening_manifest" in hardening
    assert "Hardening actions" in hardening

    assert "docs/launch_week_support_trend_review.md" in readme
    assert "docs/launch_week_runbook_delta_backlog.md" in readme
    assert "docs/phase12_recurring_issue_hardening.md" in readme
    assert "launch-week-trend-review.ps1" in readme
    assert "support-recurring-hardening.ps1" in readme
    assert "docs/launch_week_support_trend_review.md" in operational
    assert "docs/launch_week_runbook_delta_backlog.md" in operational
    assert "launch-week-trend-review.ps1" in operational
    assert "support-recurring-hardening.ps1" in operational
    assert "docs/launch_week_support_trend_review.md" in startup
    assert "docs/launch_week_runbook_delta_backlog.md" in startup
    assert "launch-week-trend-review.ps1" in startup
    assert "support-recurring-hardening.ps1" in startup
    assert "docs/launch_week_support_trend_review.md" in operator
    assert "docs/launch_week_runbook_delta_backlog.md" in operator
    assert "launch-week-trend-review.ps1" in operator
    assert "support-recurring-hardening.ps1" in operator
    assert "launch-week-trend-review.ps1" in support
    assert "support-recurring-hardening.ps1" in support


def test_phase13_post_launch_feedback_docs_exist_and_are_cross_linked() -> None:
    triage = _read("docs/post_launch_issue_triage.md")
    scoring = _read("docs/post_launch_priority_scoring.md")
    routing = _read("docs/known_issue_routing.md")
    backlog = _read("docs/post_launch_release_backlog_flow.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")
    support = _read("docs/commercial_pilot_support_runbook.md")

    for path in (
        "docs/post_launch_issue_triage.md",
        "docs/post_launch_priority_scoring.md",
        "docs/known_issue_routing.md",
        "docs/post_launch_release_backlog_flow.md",
        "scripts/post-launch-triage.ps1",
        "scripts/post-launch-priority-score.ps1",
        "scripts/known-issue-route.ps1",
        "scripts/post-launch-backlog-export.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "Post-Launch Issue Triage" in triage
    assert "Post-Launch Priority Scoring" in scoring
    assert "Known Issue Routing" in routing
    assert "Post-Launch Release Backlog Flow" in backlog

    assert "docs/post_launch_issue_triage.md" in readme
    assert "docs/post_launch_priority_scoring.md" in readme
    assert "docs/known_issue_routing.md" in readme
    assert "docs/post_launch_release_backlog_flow.md" in readme
    assert "post-launch-triage.ps1" in readme
    assert "post-launch-priority-score.ps1" in readme
    assert "known-issue-route.ps1" in readme
    assert "post-launch-backlog-export.ps1" in readme

    assert "post-launch-triage.ps1" in operational
    assert "post-launch-priority-score.ps1" in operational
    assert "known-issue-route.ps1" in operational
    assert "post-launch-backlog-export.ps1" in operational
    assert "post-launch-triage.ps1" in startup
    assert "post-launch-priority-score.ps1" in startup
    assert "known-issue-route.ps1" in startup
    assert "post-launch-backlog-export.ps1" in startup
    assert "post-launch-triage.ps1" in operator
    assert "post-launch-priority-score.ps1" in operator
    assert "known-issue-route.ps1" in operator
    assert "post-launch-backlog-export.ps1" in operator
    assert "post-launch-triage.ps1" in support
    assert "post-launch-priority-score.ps1" in support
    assert "known-issue-route.ps1" in support
    assert "post-launch-backlog-export.ps1" in support


def test_phase14_release_train_docs_exist_and_are_cross_linked() -> None:
    candidate = _read("docs/release_candidate_promotion.md")
    decision = _read("docs/release_go_hold_rollback_decision.md")
    notes = _read("docs/release_note_publication_flow.md")
    evidence = _read("docs/release_train_evidence_flow.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")
    support = _read("docs/commercial_pilot_support_runbook.md")

    for path in (
        "docs/release_candidate_promotion.md",
        "docs/release_go_hold_rollback_decision.md",
        "docs/release_note_publication_flow.md",
        "docs/release_train_evidence_flow.md",
        "scripts/release-candidate-promote.ps1",
        "scripts/release-decision-package.ps1",
        "scripts/release-notes-assemble.ps1",
        "scripts/known-issue-publication-route.ps1",
        "scripts/release-train-evidence-export.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "Release Candidate Promotion" in candidate
    assert "Release Go/Hold/Rollback Decision" in decision
    assert "Release Notes and Known-Issue Publication Flow" in notes
    assert "Release Train Evidence Flow" in evidence

    assert "release-candidate-promote.ps1" in readme
    assert "release-decision-package.ps1" in readme
    assert "release-notes-assemble.ps1" in readme
    assert "known-issue-publication-route.ps1" in readme
    assert "release-train-evidence-export.ps1" in readme
    assert "release-candidate-promote.ps1" in operational
    assert "release-decision-package.ps1" in operational
    assert "release-notes-assemble.ps1" in operational
    assert "known-issue-publication-route.ps1" in operational
    assert "release-train-evidence-export.ps1" in operational
    assert "release-candidate-promote.ps1" in startup
    assert "release-decision-package.ps1" in startup
    assert "release-notes-assemble.ps1" in startup
    assert "known-issue-publication-route.ps1" in startup
    assert "release-train-evidence-export.ps1" in startup
    assert "release-candidate-promote.ps1" in operator
    assert "release-decision-package.ps1" in operator
    assert "release-notes-assemble.ps1" in operator
    assert "known-issue-publication-route.ps1" in operator
    assert "release-train-evidence-export.ps1" in operator
    assert "release-candidate-promote.ps1" in support
    assert "release-decision-package.ps1" in support
    assert "release-notes-assemble.ps1" in support
    assert "known-issue-publication-route.ps1" in support
    assert "release-train-evidence-export.ps1" in support


def test_phase15_ga_launch_docs_exist_and_are_cross_linked() -> None:
    baseline = _read("docs/ga_launch_execution_baseline.md")
    stabilization = _read("docs/phase15_early_operations_stabilization.md")
    routing = _read("docs/phase15_hotfix_next_release_routing.md")
    closure = _read("docs/phase15_evidence_closure.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")
    support = _read("docs/commercial_pilot_support_runbook.md")

    for path in (
        "docs/ga_launch_execution_baseline.md",
        "docs/phase15_early_operations_stabilization.md",
        "docs/phase15_hotfix_next_release_routing.md",
        "docs/phase15_evidence_closure.md",
        "scripts/ga-launch-package-execute.ps1",
        "scripts/early-ops-incident-loop.ps1",
        "scripts/hotfix-next-release-route.ps1",
        "scripts/phase15-evidence-closeout.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "GA Launch Execution Baseline" in baseline
    assert "phase15_ga_launch_execution_package" in baseline
    assert "Phase 15 Early-Operations Stabilization" in stabilization
    assert "Hotfix and Next-Release Routing" in routing
    assert "phase15_hotfix_next_release_routing" in routing
    assert "Phase 15 Evidence Closure" in closure
    assert "phase15_evidence_closeout" in closure

    assert "ga-launch-package-execute.ps1" in readme
    assert "early-ops-incident-loop.ps1" in readme
    assert "hotfix-next-release-route.ps1" in readme
    assert "phase15-evidence-closeout.ps1" in readme
    assert "ga-launch-package-execute.ps1" in operational
    assert "early-ops-incident-loop.ps1" in operational
    assert "hotfix-next-release-route.ps1" in operational
    assert "phase15-evidence-closeout.ps1" in operational
    assert "ga-launch-package-execute.ps1" in startup
    assert "early-ops-incident-loop.ps1" in startup
    assert "hotfix-next-release-route.ps1" in startup
    assert "phase15-evidence-closeout.ps1" in startup
    assert "ga-launch-package-execute.ps1" in operator
    assert "early-ops-incident-loop.ps1" in operator
    assert "hotfix-next-release-route.ps1" in operator
    assert "phase15-evidence-closeout.ps1" in operator
    assert "ga-launch-package-execute.ps1" in support
    assert "early-ops-incident-loop.ps1" in support
    assert "hotfix-next-release-route.ps1" in support
    assert "phase15-evidence-closeout.ps1" in support


def test_phase16_ga_adoption_docs_exist_and_are_cross_linked() -> None:
    weekly_review = _read("docs/phase16_ga_weekly_reliability_review.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")
    roadmap = _load_json("docs/roadmap.json")
    direction_guard = _load_json("docs/direction_guard.json")

    for path in (
        "docs/phase16_ga_weekly_reliability_review.md",
        "scripts/ga-weekly-reliability-review.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "GA Weekly Reliability Review" in weekly_review
    assert "phase16_ga_weekly_reliability_review" in weekly_review
    assert "ga-weekly-reliability-review.ps1" in readme
    assert "ga-weekly-reliability-review.ps1" in operational
    assert "ga-weekly-reliability-review.ps1" in startup
    assert "ga-weekly-reliability-review.ps1" in operator

    assert direction_guard["active_phase"] == roadmap["current_phase"]
    assert direction_guard["active_phase"] in {
        "phase_20",
        "phase_21",
        "phase_22",
        "steady_state",
    }
    assert any(
        phase.get("id") == "phase_15" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_16" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_17" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_18" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_19" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_20" and phase.get("status") in {"active", "done"}
        for phase in roadmap["phases"]
    )


def test_phase17_monthly_reliability_docs_exist_and_are_cross_linked() -> None:
    monthly = _read("docs/phase17_monthly_reliability_governance.md")
    routing = _read("docs/phase17_closure_sla_routing.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")
    roadmap = _load_json("docs/roadmap.json")
    direction_guard = _load_json("docs/direction_guard.json")

    for path in (
        "docs/phase17_monthly_reliability_governance.md",
        "docs/phase17_closure_sla_routing.md",
        "scripts/ga-monthly-reliability-targets.ps1",
        "scripts/ga-closure-sla-breach-route.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "Phase 17 Monthly Reliability Governance" in monthly
    assert "phase17_ga_monthly_reliability_target_package" in monthly
    assert "Phase 17 Closure-SLA Breach Routing" in routing
    assert "phase17_closure_sla_breach_routing" in routing
    assert "ga-monthly-reliability-targets.ps1" in readme
    assert "ga-closure-sla-breach-route.ps1" in readme
    assert "ga-monthly-reliability-targets.ps1" in operational
    assert "ga-closure-sla-breach-route.ps1" in operational
    assert "ga-monthly-reliability-targets.ps1" in startup
    assert "ga-closure-sla-breach-route.ps1" in startup
    assert "ga-monthly-reliability-targets.ps1" in operator
    assert "ga-closure-sla-breach-route.ps1" in operator

    assert direction_guard["active_phase"] == roadmap["current_phase"]
    assert direction_guard["active_phase"] in {
        "phase_20",
        "phase_21",
        "phase_22",
        "steady_state",
    }
    assert any(
        phase.get("id") == "phase_16" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_17" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_18" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_19" and phase.get("status") == "done"
        for phase in roadmap["phases"]
    )
    assert any(
        phase.get("id") == "phase_20" and phase.get("status") in {"active", "done"}
        for phase in roadmap["phases"]
    )


def test_phase18_quarterly_governance_docs_exist_and_are_cross_linked() -> None:
    quarterly = _read("docs/phase18_quarterly_governance.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")

    for path in (
        "docs/phase18_quarterly_governance.md",
        "scripts/ga-quarterly-reliability-governance.ps1",
        "scripts/ga-quarterly-closure-sla-ownership.ps1",
        "scripts/ga-quarterly-review-package.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "Phase 18 Quarterly Governance" in quarterly
    assert "phase18_quarterly_reliability_governance" in quarterly
    assert "phase18_quarterly_closure_sla_ownership" in quarterly
    assert "phase18_quarterly_review_package" in quarterly

    assert "ga-quarterly-reliability-governance.ps1" in readme
    assert "ga-quarterly-closure-sla-ownership.ps1" in readme
    assert "ga-quarterly-review-package.ps1" in readme
    assert "ga-quarterly-reliability-governance.ps1" in operational
    assert "ga-quarterly-closure-sla-ownership.ps1" in operational
    assert "ga-quarterly-review-package.ps1" in operational
    assert "ga-quarterly-reliability-governance.ps1" in startup
    assert "ga-quarterly-closure-sla-ownership.ps1" in startup
    assert "ga-quarterly-review-package.ps1" in startup
    assert "ga-quarterly-reliability-governance.ps1" in operator
    assert "ga-quarterly-closure-sla-ownership.ps1" in operator
    assert "ga-quarterly-review-package.ps1" in operator


def test_phase19_upgrade_migration_safety_docs_exist_and_are_cross_linked() -> None:
    phase19 = _read("docs/phase19_upgrade_migration_safety.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")

    for path in (
        "docs/phase19_upgrade_migration_safety.md",
        "scripts/ga-upgrade-impact-matrix.ps1",
        "scripts/ga-migration-rehearsal-package.ps1",
        "scripts/ga-upgrade-rollback-safety.ps1",
        "scripts/ga-upgrade-evidence-closeout.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "Phase 19 Upgrade and Migration Safety Operations" in phase19
    assert "phase19_upgrade_impact_matrix" in phase19
    assert "phase19_migration_rehearsal_package" in phase19
    assert "phase19_upgrade_rollback_safety" in phase19
    assert "phase19_upgrade_evidence_closeout" in phase19

    assert "ga-upgrade-impact-matrix.ps1" in readme
    assert "ga-migration-rehearsal-package.ps1" in readme
    assert "ga-upgrade-rollback-safety.ps1" in readme
    assert "ga-upgrade-evidence-closeout.ps1" in readme
    assert "ga-upgrade-impact-matrix.ps1" in operational
    assert "ga-migration-rehearsal-package.ps1" in operational
    assert "ga-upgrade-rollback-safety.ps1" in operational
    assert "ga-upgrade-evidence-closeout.ps1" in operational
    assert "ga-upgrade-impact-matrix.ps1" in startup
    assert "ga-migration-rehearsal-package.ps1" in startup
    assert "ga-upgrade-rollback-safety.ps1" in startup
    assert "ga-upgrade-evidence-closeout.ps1" in startup
    assert "ga-upgrade-impact-matrix.ps1" in operator
    assert "ga-migration-rehearsal-package.ps1" in operator
    assert "ga-upgrade-rollback-safety.ps1" in operator
    assert "ga-upgrade-evidence-closeout.ps1" in operator


def test_steady_state_improvement_backlog_docs_exist_and_are_cross_linked() -> None:
    backlog_doc = _read("docs/steady_state_improvement_backlog.md")
    handbook = _read("docs/steady_state_operations_handbook.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")

    for path in (
        "docs/steady_state_improvement_backlog.md",
        "scripts/ga-steady-state-improvement-backlog.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "Steady-State Improvement Backlog" in backlog_doc
    assert "steady_state_improvement_backlog" in backlog_doc
    assert "ga-steady-state-improvement-backlog.ps1" in handbook
    assert "ga-steady-state-improvement-backlog.ps1" in readme
    assert "ga-steady-state-improvement-backlog.ps1" in operational
    assert "ga-steady-state-improvement-backlog.ps1" in startup
    assert "ga-steady-state-improvement-backlog.ps1" in operator


def test_steady_state_burndown_docs_exist_and_are_cross_linked() -> None:
    burndown_doc = _read("docs/steady_state_burndown_tracking.md")
    handbook = _read("docs/steady_state_operations_handbook.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")

    for path in (
        "docs/steady_state_burndown_tracking.md",
        "scripts/ga-steady-state-burndown.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "Steady-State Burndown Tracking" in burndown_doc
    assert "steady_state_burndown_tracking" in burndown_doc
    assert "ga-steady-state-burndown.ps1" in handbook
    assert "ga-steady-state-burndown.ps1" in readme
    assert "ga-steady-state-burndown.ps1" in operational
    assert "ga-steady-state-burndown.ps1" in startup
    assert "ga-steady-state-burndown.ps1" in operator


def test_steady_state_checkpoint_refresh_docs_exist_and_are_cross_linked() -> None:
    checkpoint_doc = _read("docs/steady_state_checkpoint_refresh.md")
    handbook = _read("docs/steady_state_operations_handbook.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")

    for path in (
        "docs/steady_state_checkpoint_refresh.md",
        "scripts/ga-steady-state-checkpoint-refresh.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "Steady-State Checkpoint Refresh" in checkpoint_doc
    assert "steady_state_checkpoint_refresh" in checkpoint_doc
    assert "ga-steady-state-checkpoint-refresh.ps1" in handbook
    assert "ga-steady-state-checkpoint-refresh.ps1" in readme
    assert "ga-steady-state-checkpoint-refresh.ps1" in operational
    assert "ga-steady-state-checkpoint-refresh.ps1" in startup
    assert "ga-steady-state-checkpoint-refresh.ps1" in operator


def test_steady_state_watchlist_routing_docs_exist_and_are_cross_linked() -> None:
    watchlist_doc = _read("docs/steady_state_watchlist_ownership_routing.md")
    handbook = _read("docs/steady_state_operations_handbook.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")

    for path in (
        "docs/steady_state_watchlist_ownership_routing.md",
        "scripts/ga-steady-state-escalation-watchlist-route.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "Steady-State Escalation Watchlist Ownership Routing" in watchlist_doc
    assert "steady_state_escalation_watchlist_routing" in watchlist_doc
    assert "ga-steady-state-escalation-watchlist-route.ps1" in handbook
    assert "ga-steady-state-escalation-watchlist-route.ps1" in readme
    assert "ga-steady-state-escalation-watchlist-route.ps1" in operational
    assert "ga-steady-state-escalation-watchlist-route.ps1" in startup
    assert "ga-steady-state-escalation-watchlist-route.ps1" in operator


def test_steady_state_runtime_loop_docs_exist_and_are_cross_linked() -> None:
    runtime_loop = _read("docs/steady_state_runtime_loop.md")
    handbook = _read("docs/steady_state_operations_handbook.md")
    readme = _read("README.md")
    operational = _read("docs/operational_readiness_runbook.md")
    startup = _read("docs/operational_startup_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")

    for path in (
        "docs/steady_state_runtime_loop.md",
        "docs/steady_state_runtime_state.json",
        "scripts/steady-state-run.ps1",
    ):
        assert (ROOT / path).exists(), path

    assert "Steady-State Runtime Loop" in runtime_loop
    assert "steady-state-run.ps1" in runtime_loop
    assert "steady-state-run.ps1" in handbook
    assert "steady-state-run.ps1" in readme
    assert "steady-state-run.ps1" in operational
    assert "steady-state-run.ps1" in startup
    assert "steady-state-run.ps1" in operator


def test_openapi_declares_bearer_auth_for_protected_manual_flow_routes() -> None:
    openapi = _load_json("openapi.json")
    from app.api.main import app

    runtime_openapi = app.openapi()
    assert set(openapi.get("paths", {}).keys()) == set(runtime_openapi.get("paths", {}).keys())

    security_schemes = openapi.get("components", {}).get("securitySchemes", {})
    assert security_schemes.get("HTTPBearer") == {"type": "http", "scheme": "bearer"}

    protected_paths = (
        "/orchestrator/resume/approval",
        "/orchestrator/approval/reject",
        "/orchestrator/resume/revision",
        "/orchestrator/replanning/start",
    )
    for path in protected_paths:
        operation = openapi["paths"][path]["post"]
        assert operation.get("security") == [{"HTTPBearer": []}], path
        assert operation.get("parameters") is None, path


def test_commercial_auth_docs_reference_token_store_and_admin_lifecycle_routes() -> None:
    env_example = _read(".env.example")
    readme = _read("README.md")
    startup = _read("docs/operational_startup_runbook.md")
    readiness = _read("docs/operational_readiness_runbook.md")

    assert "AUTH_TOKEN_STORE_PATH=" in env_example
    assert "/auth/tokens" in readme
    assert "/auth/tokens/issue" in readme
    assert "/auth/tokens/revoke" in readme
    assert "/auth/tokens/rotate" in readme
    assert "AUTH_TOKEN_STORE_PATH" in startup
    assert "/auth/tokens/issue" in startup
    assert "AUTH_TOKEN_STORE_PATH" in readiness
    assert "/auth/tokens/rotate" in readiness


def test_openapi_declares_bearer_auth_for_commercial_auth_management_routes() -> None:
    openapi = _load_json("openapi.json")

    assert openapi["paths"]["/auth/tokens"]["get"].get("security") == [{"HTTPBearer": []}]
    assert openapi["paths"]["/auth/tokens/issue"]["post"].get("security") == [{"HTTPBearer": []}]
    assert openapi["paths"]["/auth/tokens/revoke"]["post"].get("security") == [{"HTTPBearer": []}]
    assert openapi["paths"]["/auth/tokens/rotate"]["post"].get("security") == [{"HTTPBearer": []}]


def test_intake_llm_and_live_contract_opt_in_docs_are_explicit() -> None:
    env_example = _read(".env.example")
    readme = _read("README.md")
    operator = _read("docs/operator_workflow_runbook.md")

    assert "INTAKE_USE_LLM=0" in env_example
    assert "INTAKE_MODEL=mock" in env_example
    assert "RUN_LIVE_LLM_CONTRACT=0" in env_example
    assert "OPENCLAW_LIVE_CONTRACT_TIMEOUT_SECONDS=60" in env_example

    assert "Default remains regex-first intake (`INTAKE_USE_LLM=0`)" in readme
    assert "Enable `INTAKE_USE_LLM=1` only when LLM-assisted completion" in readme
    assert "python -m pytest -q tests/test_live_llm_contract_optin.py" in readme
    assert "OPENCLAW_GATEWAY_TOKEN = \"<gateway-token>\"" in readme
    assert "If this test returns `401 Unauthorized`" in readme

    assert "Default is deterministic regex-first intake (`INTAKE_USE_LLM=0`)." in operator
    assert "set `INTAKE_USE_LLM=1`." in operator
    assert "python -m pytest -q tests/test_live_llm_contract_optin.py" in operator
    assert "OPENCLAW_GATEWAY_TOKEN = \"<gateway-token>\"" in operator
    assert "fails with `401 Unauthorized`" in operator


def test_runtime_storage_boundary_doc_is_present_and_cross_linked() -> None:
    boundary = _read("docs/runtime_storage_boundary.md")
    readme = _read("README.md")
    startup = _read("docs/operational_startup_runbook.md")
    readiness = _read("docs/operational_readiness_runbook.md")
    operator = _read("docs/operator_workflow_runbook.md")

    assert "Runtime and Storage Boundary" in boundary
    assert "AI Work System" in boundary
    assert "MacroPulser" in boundary
    assert "app/state/*" in boundary
    assert "app/db/*" in boundary

    assert "docs/runtime_storage_boundary.md" in readme
    assert "docs/runtime_storage_boundary.md" in startup
    assert "docs/runtime_storage_boundary.md" in readiness
    assert "docs/runtime_storage_boundary.md" in operator
