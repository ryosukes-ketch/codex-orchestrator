import json
import os
import shutil
import subprocess
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
        timeout=180,
        check=False,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator replay export tests.",
)
def test_operator_replay_export_collects_readiness_and_cycle_artifacts(tmp_path: Path) -> None:
    cycle_dir = tmp_path / "cycle-approval"
    suite_dir = tmp_path / "suite"
    readiness_dir = tmp_path / "readiness"

    cycle_summary = cycle_dir / "summary.json"
    cycle_status = cycle_dir / "status.json"
    cycle_status_summary = cycle_dir / "status-summary.json"
    cycle_audit = cycle_dir / "audit.json"
    cycle_stage_report = cycle_dir / "stage-report.json"
    cycle_audit_assert = cycle_dir / "audit-assert.json"
    cycle_manifest = cycle_dir / "bundle-manifest.json"

    _write_json(cycle_summary, {"project_id": "p-export", "final_status": "completed"})
    _write_json(cycle_status, {"project_id": "p-export", "status": "completed"})
    _write_json(cycle_status_summary, {"project_id": "p-export", "status": "completed"})
    _write_json(cycle_audit, {"project_id": "p-export", "status": "completed"})
    _write_json(cycle_stage_report, {"project_id": "p-export", "stage_totals": {}})
    _write_json(cycle_audit_assert, {"project_id": "p-export", "passed": True, "errors": []})
    _write_json(
        cycle_manifest,
        {
            "bundle_type": "cycle",
            "project_id": "p-export",
            "artifacts": {
                "summary": {"path": str(cycle_summary)},
                "status": {"path": str(cycle_status)},
                "status_summary": {"path": str(cycle_status_summary)},
                "audit": {"path": str(cycle_audit)},
                "stage_report": {"path": str(cycle_stage_report)},
                "audit_assert": {"path": str(cycle_audit_assert)},
            },
        },
    )

    suite_summary = suite_dir / "suite-summary.json"
    suite_stage_gate = suite_dir / "suite-stage-gate.json"
    suite_handoff = suite_dir / "suite-handoff.json"
    suite_manifest = suite_dir / "bundle-manifest.json"
    _write_json(suite_summary, {"cycle_count": 1, "all_completed": True})
    _write_json(suite_stage_gate, {"passed": True})
    _write_json(suite_handoff, {"source_type": "suite"})
    _write_json(
        suite_manifest,
        {
            "bundle_type": "suite",
            "artifacts": {
                "suite_summary": {"path": str(suite_summary)},
                "stage_gate": {"path": str(suite_stage_gate)},
                "handoff_json": {"path": str(suite_handoff)},
            },
            "cycles": [
                {
                    "mode": "approval",
                    "summary_path": str(cycle_summary),
                    "status_summary_path": str(cycle_status_summary),
                    "bundle_manifest_path": str(cycle_manifest),
                    "project_id": "p-export",
                    "final_status": "completed",
                }
            ],
        },
    )

    readiness_summary = readiness_dir / "readiness-summary.json"
    live_smoke_log = readiness_dir / "live-smoke.json"
    seed_log = readiness_dir / "seed-log.json"
    readiness_manifest = readiness_dir / "readiness-manifest.json"
    _write_json(readiness_summary, {"result": "ok"})
    _write_json(live_smoke_log, {"result": "ok"})
    _write_json(seed_log, {"result": "ok"})
    _write_json(
        readiness_manifest,
        {
            "bundle_type": "readiness",
            "artifacts": {
                "readiness_summary": {"path": str(readiness_summary)},
                "live_smoke_log": {"path": str(live_smoke_log)},
                "full_live_flow_seed_log": {"path": str(seed_log)},
                "operator_suite_manifest": {"path": str(suite_manifest)},
                "operator_suite_summary": {"path": str(suite_summary)},
                "operator_suite_stage_gate": {"path": str(suite_stage_gate)},
                "operator_suite_handoff": {"path": str(suite_handoff)},
            },
        },
    )

    output_dir = tmp_path / "replay-export"
    export_manifest = tmp_path / "replay-export.manifest.json"
    result = _run_script(
        "operator-replay-export.ps1",
        "-ReadinessManifestPath",
        str(readiness_manifest),
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(export_manifest),
    )
    assert result.returncode == 0, result.stderr
    assert output_dir.exists()
    assert export_manifest.exists()

    payload = json.loads(export_manifest.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "operator_replay_export"
    assert payload["source_type"] == "readiness"
    assert payload["artifact_count"] >= 8
    assert payload["missing_artifact_count"] == 0
    roles = {entry["role"] for entry in payload["artifacts"]}
    assert "readiness_manifest" in roles
    assert "suite_bundle_manifest" in roles
    assert "cycle_approval_summary" in roles
