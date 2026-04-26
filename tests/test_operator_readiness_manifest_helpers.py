import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="PowerShell helper tests are Windows-only.")
@pytest.mark.skipif(POWERSHELL_EXE is None, reason="PowerShell is required.")
def test_readiness_and_suite_manifest_helpers_resolve_paths(tmp_path: Path) -> None:
    approval_dir = tmp_path / "approval"
    reject_dir = tmp_path / "reject-replan"
    suite_dir = tmp_path / "suite"

    for file_path in (
        approval_dir / "summary.json",
        approval_dir / "status-summary.json",
        approval_dir / "bundle-manifest.json",
        reject_dir / "summary.json",
        reject_dir / "status-summary.json",
        reject_dir / "bundle-manifest.json",
        suite_dir / "suite-summary.json",
        suite_dir / "suite-stage-gate.json",
        suite_dir / "suite-handoff.json",
        suite_dir / "readiness-summary.json",
        suite_dir / "live-smoke.json",
        suite_dir / "seed-log.json",
    ):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("{}", encoding="utf-8")

    suite_manifest_path = suite_dir / "bundle-manifest.json"
    readiness_manifest_path = suite_dir / "readiness-manifest.json"

    _write_json(
        suite_manifest_path,
        {
            "bundle_type": "suite",
            "bundle_version": 1,
            "artifacts": {
                "suite_summary": {"path": str(suite_dir / "suite-summary.json")},
                "stage_gate": {"path": str(suite_dir / "suite-stage-gate.json")},
                "handoff_json": {"path": str(suite_dir / "suite-handoff.json")},
            },
            "cycles": [
                {
                    "mode": "approval",
                    "summary_path": str(approval_dir / "summary.json"),
                    "status_summary_path": str(approval_dir / "status-summary.json"),
                    "bundle_manifest_path": str(approval_dir / "bundle-manifest.json"),
                    "project_id": "approval-project",
                    "final_status": "completed",
                },
                {
                    "mode": "reject-replan",
                    "summary_path": str(reject_dir / "summary.json"),
                    "status_summary_path": str(reject_dir / "status-summary.json"),
                    "bundle_manifest_path": str(reject_dir / "bundle-manifest.json"),
                    "project_id": "reject-project",
                    "final_status": "completed",
                },
            ],
        },
    )
    _write_json(
        readiness_manifest_path,
        {
            "bundle_type": "readiness",
            "bundle_version": 1,
            "artifacts": {
                "readiness_summary": {"path": str(suite_dir / "readiness-summary.json")},
                "live_smoke_log": {"path": str(suite_dir / "live-smoke.json")},
                "full_live_flow_seed_log": {"path": str(suite_dir / "seed-log.json")},
                "operator_suite_manifest": {"path": str(suite_manifest_path)},
                "operator_suite_summary": {"path": str(suite_dir / "suite-summary.json")},
                "operator_suite_stage_gate": {"path": str(suite_dir / "suite-stage-gate.json")},
                "operator_suite_handoff": {"path": str(suite_dir / "suite-handoff.json")},
            },
        },
    )

    common_script = ROOT / "scripts" / "operator-common.ps1"
    command_text = " ".join(
        [
            f". '{common_script}';",
            (
                "$readiness = Resolve-ReadinessBundleContext "
                f"-ReadinessManifestPath '{readiness_manifest_path}' "
                f"-RepoRoot '{ROOT}';"
            ),
            (
                "$suite = Resolve-OperatorSuiteBundleContext "
                "-BundleManifestPath $readiness.operator_suite_manifest_path "
                f"-RepoRoot '{ROOT}';"
            ),
            "$payload = [pscustomobject]@{",
            "readiness_summary = $readiness.summary_path;",
            "suite_manifest = $readiness.operator_suite_manifest_path;",
            "stage_gate = $readiness.operator_suite_stage_gate_path;",
            "handoff = $readiness.operator_suite_handoff_path;",
            "cycle_modes = @($suite.cycles | ForEach-Object { $_.mode });",
            (
                "approval_manifest = ($suite.cycles | Where-Object "
                "{ $_.mode -eq 'approval' } | Select-Object -First 1).bundle_manifest_path;"
            ),
            (
                "reject_manifest = ($suite.cycles | Where-Object "
                "{ $_.mode -eq 'reject-replan' } | Select-Object -First 1).bundle_manifest_path"
            ),
            "};",
            "$payload | ConvertTo-Json -Depth 10",
        ]
    )

    command = [
        POWERSHELL_EXE,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command_text,
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert Path(payload["readiness_summary"]) == suite_dir / "readiness-summary.json"
    assert Path(payload["suite_manifest"]) == suite_manifest_path
    assert Path(payload["stage_gate"]) == suite_dir / "suite-stage-gate.json"
    assert Path(payload["handoff"]) == suite_dir / "suite-handoff.json"
    assert set(payload["cycle_modes"]) == {"approval", "reject-replan"}
    assert Path(payload["approval_manifest"]) == approval_dir / "bundle-manifest.json"
    assert Path(payload["reject_manifest"]) == reject_dir / "bundle-manifest.json"
