import json
import os
import shutil
import subprocess
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
        timeout=300,
        check=False,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(POWERSHELL_EXE is None, reason="PowerShell is required.")
def test_phase15_early_ops_incident_loop_uses_support_bundle_input(tmp_path: Path) -> None:
    source_dir = tmp_path / "support-source"
    source_dir.mkdir(parents=True, exist_ok=True)
    classification_path = source_dir / "failure-classification.json"
    replay_path = source_dir / "replay-export.manifest.json"
    support_manifest_path = source_dir / "support-bundle.manifest.json"
    output_dir = tmp_path / "phase15-incident"
    out_manifest = tmp_path / "phase15-incident.manifest.json"
    out_summary = tmp_path / "phase15-incident-summary.json"

    _write_json(
        classification_path,
        {
            "classification_status": "issues_detected",
            "has_blocking_findings": False,
            "finding_count": 2,
            "category_counts": {
                "runtime": 2,
                "provider_auth": 0,
                "policy": 0,
                "semantic_output": 0,
                "persistence_restore": 0,
                "operator_flow": 0,
                "unknown": 0,
            },
            "severity_counts": {"error": 1, "warning": 1, "info": 0},
            "findings": [
                {"category": "runtime", "severity": "error", "message": "timeout waiting upstream"},
                {"category": "runtime", "severity": "warning", "message": "retry recovered once"},
            ],
            "next_steps": ["step1", "step2", "step3"],
        },
    )
    _write_json(replay_path, {"bundle_type": "operator_replay_export"})
    _write_json(
        support_manifest_path,
        {
            "bundle_type": "pilot_support_bundle_manifest",
            "classification_status": "issues_detected",
            "has_blocking_findings": False,
            "finding_count": 2,
            "failure_classification_json_path": str(classification_path),
            "replay_export_manifest_path": str(replay_path),
        },
    )

    result = _run(
        "early-ops-incident-loop.ps1",
        "-SupportBundleManifestPath",
        str(support_manifest_path),
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
        "-WindowDays",
        "7",
    )
    assert result.returncode == 0, result.stderr

    payload = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "phase15_early_operations_incident_loop"
    assert payload["summary"]["support_bundle_finding_count"] == 2
    assert payload["summary"]["recurring_hardening_action_count"] >= 1
    assert summary["launch_week_support_bundle_count"] >= 1
    assert Path(payload["artifacts"]["support_bundle_manifest"]["path"]).exists()
    assert Path(payload["artifacts"]["launch_week_trend_manifest"]["path"]).exists()
    assert Path(payload["artifacts"]["recurring_hardening_manifest"]["path"]).exists()


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(POWERSHELL_EXE is None, reason="PowerShell is required.")
def test_phase15_hotfix_next_release_route_generates_lane_summary(tmp_path: Path) -> None:
    recurring_manifest = tmp_path / "recurring-issue-hardening.manifest.json"
    known_issues = tmp_path / "known_issues_register.md"
    output_dir = tmp_path / "phase15-routing"
    out_manifest = tmp_path / "phase15-routing.manifest.json"
    out_summary = tmp_path / "phase15-routing-summary.json"

    _write_json(
        recurring_manifest,
        {
            "bundle_type": "phase12_recurring_issue_pattern_hardening",
            "hardening_actions": [
                {
                    "action_id": "P12-HARD-001",
                    "action_type": "recurring_category_hardening",
                    "category": "runtime",
                    "priority": "P1",
                    "runbook_delta": "runtime hardening",
                    "source_signal_count": 3,
                    "source_bundle_count": 2,
                    "target_docs": ["docs/operator_workflow_runbook.md"],
                    "recommended_script_checks": ["scripts/openclaw-gateway-check.ps1"],
                }
            ],
        },
    )
    known_issues.write_text(
        (
            "# Known Issues Register\n\n"
            "| Issue ID | Title | Severity | Status | Owner | First Seen (UTC) | Workaround | Next Action |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| KI-20260424-001 | Example issue | P2 | open | owner | 2026-04-24T00:00:00Z | manual | monitor |\n"
        ),
        encoding="utf-8",
    )

    result = _run(
        "hotfix-next-release-route.ps1",
        "-RecurringHardeningManifestPath",
        str(recurring_manifest),
        "-KnownIssuesPath",
        str(known_issues),
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    payload = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "phase15_hotfix_next_release_routing"
    assert summary["routed_item_count"] >= 1
    assert summary["hotfix_candidate_count"] >= 1
    assert summary["stabilization_recommendation"] in {
        "prioritize_hotfix_lane",
        "prioritize_next_release_lane",
        "monitor_only_cycle",
    }
    assert Path(payload["artifacts"]["routing_manifest"]["path"]).exists()
    assert Path(payload["artifacts"]["backlog_export_manifest"]["path"]).exists()


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(POWERSHELL_EXE is None, reason="PowerShell is required.")
def test_phase15_evidence_closeout_aggregates_existing_manifests(tmp_path: Path) -> None:
    ga_manifest = tmp_path / "ga-launch-package.manifest.json"
    early_manifest = tmp_path / "early-ops-incident-loop.manifest.json"
    routing_manifest = tmp_path / "hotfix-next-release-route.manifest.json"
    out_manifest = tmp_path / "phase15-closeout.manifest.json"
    out_summary = tmp_path / "phase15-closeout-summary.json"

    _write_json(
        ga_manifest,
        {
            "bundle_type": "phase15_ga_launch_execution_package",
            "summary": {"decision": "GO", "rollback_signal": "none"},
        },
    )
    _write_json(
        early_manifest,
        {
            "bundle_type": "phase15_early_operations_incident_loop",
            "summary": {
                "support_bundle_has_blocking_findings": False,
                "support_bundle_finding_count": 0,
                "recurring_hardening_action_count": 1,
            },
        },
    )
    _write_json(
        routing_manifest,
        {
            "bundle_type": "phase15_hotfix_next_release_routing",
            "summary": {
                "hotfix_candidate_count": 1,
                "next_release_candidate_count": 2,
                "stabilization_recommendation": "prioritize_hotfix_lane",
            },
        },
    )

    result = _run(
        "phase15-evidence-closeout.ps1",
        "-GaLaunchManifestPath",
        str(ga_manifest),
        "-EarlyOpsManifestPath",
        str(early_manifest),
        "-RoutingManifestPath",
        str(routing_manifest),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    payload = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "phase15_evidence_closeout"
    assert summary["ga_launch_decision"] == "GO"
    assert summary["routing_hotfix_candidate_count"] == 1
    assert summary["routing_next_release_candidate_count"] == 2
    assert summary["phase15_completion_ready"] is True
