import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


def _run_script(script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL_EXE is not None
    command = [
        POWERSHELL_EXE,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / script_name),
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
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for quarterly governance script tests.",
)
def test_ga_quarterly_reliability_governance_aggregates_monthly_inputs(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    monthly_1 = tmp_path / "m1.manifest.json"
    monthly_2 = tmp_path / "m2.manifest.json"
    _write_json(
        monthly_1,
        {
            "bundle_type": "phase17_ga_monthly_reliability_target_package",
            "generated_at_utc": (now - timedelta(days=20)).isoformat(),
            "summary": {
                "monthly_decision": "watch",
                "recommendation_counts": {
                    "urgent_hardening_cycle": 0,
                    "targeted_hardening_cycle": 1,
                    "monitor_only_cycle": 0,
                },
                "support_bundle_count_total": 4,
                "hardening_action_count_total": 2,
                "closure_sla": {"overdue_action_count": 1, "overdue_p1_count": 0},
                "reliability_health_score": 90,
                "known_issue_snapshot": {"open": 1, "mitigated": 0, "resolved": 0},
            },
        },
    )
    _write_json(
        monthly_2,
        {
            "bundle_type": "phase17_ga_monthly_reliability_target_package",
            "generated_at_utc": (now - timedelta(days=5)).isoformat(),
            "summary": {
                "monthly_decision": "go",
                "recommendation_counts": {
                    "urgent_hardening_cycle": 0,
                    "targeted_hardening_cycle": 0,
                    "monitor_only_cycle": 1,
                },
                "support_bundle_count_total": 3,
                "hardening_action_count_total": 1,
                "closure_sla": {"overdue_action_count": 0, "overdue_p1_count": 0},
                "reliability_health_score": 100,
                "known_issue_snapshot": {"open": 0, "mitigated": 1, "resolved": 0},
            },
        },
    )

    out_manifest = tmp_path / "quarterly.manifest.json"
    out_summary = tmp_path / "quarterly.summary.json"
    result = _run_script(
        "ga-quarterly-reliability-governance.ps1",
        "-MonthlyManifestPaths",
        f"{monthly_1},{monthly_2}",
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "phase18_quarterly_reliability_governance"
    assert summary["monthly_package_count"] == 2
    assert summary["monthly_decision_counts"]["watch"] == 1
    assert summary["support_bundle_count_total"] == 7
    assert summary["quarterly_decision"] == "watch"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for quarterly governance script tests.",
)
def test_ga_quarterly_closure_sla_ownership_generates_owner_commitments(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    routing_1 = tmp_path / "r1.manifest.json"
    routing_2 = tmp_path / "r2.manifest.json"
    _write_json(
        routing_1,
        {
            "bundle_type": "phase17_closure_sla_breach_routing",
            "generated_at_utc": (now - timedelta(days=15)).isoformat(),
            "details": {
                "closure_sla_routed_actions": [
                    {
                        "action_id": "A-1",
                        "owner": "runtime_ops",
                        "status": "planned",
                        "route": "immediate_escalation",
                        "overdue": True,
                        "due_at_utc": "2026-04-10T00:00:00Z",
                    },
                    {
                        "action_id": "A-2",
                        "owner": "policy_ops",
                        "status": "planned",
                        "route": "targeted_hardening",
                        "overdue": True,
                        "due_at_utc": "2026-04-20T00:00:00Z",
                    },
                ]
            },
        },
    )
    _write_json(
        routing_2,
        {
            "bundle_type": "phase17_closure_sla_breach_routing",
            "generated_at_utc": (now - timedelta(days=3)).isoformat(),
            "details": {
                "closure_sla_routed_actions": [
                    {
                        "action_id": "A-1",
                        "owner": "runtime_ops",
                        "status": "planned",
                        "route": "immediate_escalation",
                        "overdue": True,
                        "due_at_utc": "2026-04-10T00:00:00Z",
                    },
                ]
            },
        },
    )

    out_manifest = tmp_path / "ownership.manifest.json"
    out_summary = tmp_path / "ownership.summary.json"
    result = _run_script(
        "ga-quarterly-closure-sla-ownership.ps1",
        "-ClosureRoutingManifestPaths",
        f"{routing_1},{routing_2}",
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "phase18_quarterly_closure_sla_ownership"
    assert summary["routing_manifest_count"] == 2
    assert summary["route_totals"]["immediate_escalation"] == 2
    assert summary["carry_over_action_count"] == 1
    assert summary["quarterly_closure_decision"] == "escalate"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for quarterly governance script tests.",
)
def test_ga_quarterly_review_package_combines_reliability_and_closure_outputs(tmp_path: Path) -> None:
    reliability_manifest = tmp_path / "q-reliability.manifest.json"
    closure_manifest = tmp_path / "q-closure.manifest.json"
    _write_json(
        reliability_manifest,
        {
            "bundle_type": "phase18_quarterly_reliability_governance",
            "summary": {"quarterly_decision": "go", "reliability_health_score_average": 97},
        },
    )
    _write_json(
        closure_manifest,
        {
            "bundle_type": "phase18_quarterly_closure_sla_ownership",
            "summary": {"quarterly_closure_decision": "watch", "carry_over_action_count": 2},
            "details": {
                "owner_commitments": [
                    {"owner": "runtime_ops", "commitment_status": "at_risk"},
                    {"owner": "policy_ops", "commitment_status": "on_track"},
                ]
            },
        },
    )

    out_manifest = tmp_path / "q-review.manifest.json"
    out_summary = tmp_path / "q-review.summary.json"
    result = _run_script(
        "ga-quarterly-review-package.ps1",
        "-ReliabilityManifestPath",
        str(reliability_manifest),
        "-ClosureOwnershipManifestPath",
        str(closure_manifest),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "phase18_quarterly_review_package"
    assert summary["reliability_quarterly_decision"] == "go"
    assert summary["closure_quarterly_decision"] == "watch"
    assert summary["quarterly_review_decision"] == "watch"
    assert summary["owner_at_risk_count"] == 1
