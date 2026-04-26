import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL_EXE is not None
    command = [
        POWERSHELL_EXE,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / script),
        *args,
    ]
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for phase13 feedback script tests.",
)
def test_phase13_feedback_pipeline_exports_release_backlog_package(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()

    hardening_manifest = tmp_path / "recurring-issue-hardening.manifest.json"
    _write_json(
        hardening_manifest,
        {
            "bundle_type": "phase12_recurring_issue_pattern_hardening",
            "generated_at_utc": now,
            "hardening_actions": [
                {
                    "action_id": "P12-HARD-001",
                    "action_type": "recurring_category_hardening",
                    "category": "runtime",
                    "priority": "P1",
                    "runbook_delta": "runtime decision tree",
                    "source_signal_count": 4,
                    "source_bundle_count": 2,
                    "target_docs": ["docs/operator_workflow_runbook.md"],
                    "recommended_script_checks": ["scripts/openclaw-gateway-check.ps1"],
                },
                {
                    "action_id": "P12-HARD-002",
                    "action_type": "support_evidence_schema_hardening",
                    "category": "support_evidence",
                    "priority": "P2",
                    "runbook_delta": "schema enforcement",
                    "source_signal_count": 2,
                    "source_bundle_count": 1,
                    "target_docs": ["docs/commercial_pilot_support_runbook.md"],
                    "recommended_script_checks": ["scripts/operator-support-bundle.ps1"],
                },
            ],
        },
    )

    known_issues = tmp_path / "known_issues_register.md"
    known_issues.write_text(
        """
# Known Issues Register

| Issue ID | Title | Severity | Status | Owner | First Seen (UTC) | Workaround | Next Action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| KI-20260423-001 | Sample | P2 | open | owner | 2026-04-23T00:00:00Z | n/a | monitor |
""".strip()
        + "\n",
        encoding="utf-8",
    )

    triage_manifest = tmp_path / "post-launch-triage.manifest.json"
    score_manifest = tmp_path / "post-launch-priority-score.manifest.json"
    route_manifest = tmp_path / "known-issue-routing.manifest.json"
    export_manifest = tmp_path / "post-launch-backlog-export.manifest.json"

    triage_result = _run(
        "post-launch-triage.ps1",
        "-RecurringHardeningManifestPath",
        str(hardening_manifest),
        "-KnownIssuesPath",
        str(known_issues),
        "-OutPath",
        str(triage_manifest),
        "-TriageDocPath",
        str(tmp_path / "post_launch_issue_triage.md"),
    )
    assert triage_result.returncode == 0, triage_result.stderr
    triage_payload = json.loads(triage_manifest.read_text(encoding="utf-8"))
    assert triage_payload["bundle_type"] == "phase13_post_launch_issue_triage"
    assert triage_payload["triage_item_count"] == 2
    assert triage_payload["triage_bucket_counts"]["release_backlog"] >= 1

    score_result = _run(
        "post-launch-priority-score.ps1",
        "-TriageManifestPath",
        str(triage_manifest),
        "-OutPath",
        str(score_manifest),
        "-ScoringDocPath",
        str(tmp_path / "post_launch_priority_scoring.md"),
    )
    assert score_result.returncode == 0, score_result.stderr
    score_payload = json.loads(score_manifest.read_text(encoding="utf-8"))
    assert score_payload["bundle_type"] == "phase13_post_launch_priority_scoring"
    assert score_payload["scored_item_count"] == 2
    assert score_payload["tier_counts"]["High"] >= 1

    route_result = _run(
        "known-issue-route.ps1",
        "-PriorityManifestPath",
        str(score_manifest),
        "-KnownIssuesPath",
        str(known_issues),
        "-OutPath",
        str(route_manifest),
        "-RoutingDocPath",
        str(tmp_path / "known_issue_routing.md"),
    )
    assert route_result.returncode == 0, route_result.stderr
    route_payload = json.loads(route_manifest.read_text(encoding="utf-8"))
    assert route_payload["bundle_type"] == "phase13_known_issue_routing"
    assert route_payload["routed_item_count"] == 2
    assert route_payload["route_counts"]["hotfix_candidate"] >= 1

    export_result = _run(
        "post-launch-backlog-export.ps1",
        "-RoutingManifestPath",
        str(route_manifest),
        "-OutPath",
        str(export_manifest),
        "-BacklogDocPath",
        str(tmp_path / "post_launch_release_backlog_flow.md"),
    )
    assert export_result.returncode == 0, export_result.stderr
    export_payload = json.loads(export_manifest.read_text(encoding="utf-8"))
    assert export_payload["bundle_type"] == "phase13_post_launch_release_backlog_package"
    assert export_payload["summary"]["release_candidate_count"] >= 1


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for phase13 feedback script tests.",
)
def test_post_launch_triage_maps_baseline_monitoring_to_monitoring_only(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    hardening_manifest = tmp_path / "recurring-issue-hardening-empty.manifest.json"
    _write_json(
        hardening_manifest,
        {
            "bundle_type": "phase12_recurring_issue_pattern_hardening",
            "generated_at_utc": now,
            "hardening_actions": [
                {
                    "action_id": "P12-HARD-001",
                    "action_type": "baseline_monitoring",
                    "category": "none",
                    "priority": "P3",
                    "runbook_delta": "monitor",
                    "source_signal_count": 0,
                    "source_bundle_count": 0,
                    "target_docs": ["docs/launch_week_support_trend_review.md"],
                    "recommended_script_checks": ["scripts/launch-week-trend-review.ps1"],
                }
            ],
        },
    )

    triage_manifest = tmp_path / "triage-empty.manifest.json"
    result = _run(
        "post-launch-triage.ps1",
        "-RecurringHardeningManifestPath",
        str(hardening_manifest),
        "-OutPath",
        str(triage_manifest),
        "-TriageDocPath",
        str(tmp_path / "post_launch_issue_triage.md"),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(triage_manifest.read_text(encoding="utf-8"))
    assert payload["triage_item_count"] == 1
    assert payload["triage_bucket_counts"]["monitoring_only"] == 1
    assert payload["triage_items"][0]["decision"] == "monitor_only"
