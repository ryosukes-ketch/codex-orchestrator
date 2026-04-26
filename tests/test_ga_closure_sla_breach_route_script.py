import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL_EXE is not None
    command = [
        POWERSHELL_EXE,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / "ga-closure-sla-breach-route.ps1"),
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
    reason="PowerShell is required for closure-SLA breach route script tests.",
)
def test_ga_closure_sla_breach_route_generates_owner_and_route_fields(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    monthly_manifest = tmp_path / "ga-monthly-reliability-targets.manifest.json"
    _write_json(
        monthly_manifest,
        {
            "bundle_type": "phase17_ga_monthly_reliability_target_package",
            "generated_at_utc": now,
            "summary": {"monthly_decision": "watch"},
            "details": {
                "closure_sla_open_actions": [
                    {
                        "action_id": "P12-HARD-101",
                        "category": "runtime",
                        "priority": "P1",
                        "status": "planned",
                        "owner": "unassigned",
                        "observed_at_utc": "2026-04-01T00:00:00Z",
                        "age_days": 25,
                        "sla_days": 7,
                        "overdue": True,
                        "runbook_delta": "runtime timeout decision tree",
                    },
                    {
                        "action_id": "P12-HARD-102",
                        "category": "policy",
                        "priority": "P2",
                        "status": "planned",
                        "owner": "unassigned",
                        "observed_at_utc": "2026-04-20T00:00:00Z",
                        "age_days": 3,
                        "sla_days": 14,
                        "overdue": False,
                        "runbook_delta": "policy deny branch tightening",
                    },
                ]
            },
        },
    )

    out_manifest = tmp_path / "ga-closure-sla-routing.manifest.json"
    out_summary = tmp_path / "ga-closure-sla-routing.summary.json"
    out_dir = tmp_path / "routing"

    result = _run_script(
        "-MonthlyManifestPath",
        str(monthly_manifest),
        "-OutputDir",
        str(out_dir),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
        "-Zip",
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))

    assert manifest["bundle_type"] == "phase17_closure_sla_breach_routing"
    assert summary["open_action_count"] == 2
    assert summary["route_counts"]["immediate_escalation"] == 1
    assert summary["closure_sla_decision"] == "escalate"

    routed = manifest["details"]["closure_sla_routed_actions"]
    assert len(routed) == 2
    assert all("owner" in row and "status" in row for row in routed)
    assert any(row["owner"] == "runtime_ops" and row["route"] == "immediate_escalation" for row in routed)
    assert any(row["owner"] == "policy_ops" for row in routed)
    assert (out_dir.with_suffix(".zip")).exists()


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for closure-SLA breach route script tests.",
)
def test_ga_closure_sla_breach_route_rejects_invalid_monthly_bundle_type(tmp_path: Path) -> None:
    invalid_manifest = tmp_path / "invalid-monthly.manifest.json"
    _write_json(
        invalid_manifest,
        {
            "bundle_type": "unexpected_bundle",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "summary": {},
            "details": {"closure_sla_open_actions": []},
        },
    )

    result = _run_script("-MonthlyManifestPath", str(invalid_manifest))
    assert result.returncode != 0
    assert "Unsupported monthly bundle_type" in result.stderr
