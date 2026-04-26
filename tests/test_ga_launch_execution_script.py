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


def _write_known_issues(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "# Known Issues Register\n\n"
            "| Issue ID | Title | Severity | Status | Owner | First Seen (UTC) | Workaround | Next Action |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| KI-20260424-001 | Example issue | P2 | open | owner | 2026-04-24T00:00:00Z | manual workaround | monitor |\n"
        ),
        encoding="utf-8",
    )


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for GA launch script tests.",
)
def test_ga_launch_package_execute_generates_phase15_bundle(tmp_path: Path) -> None:
    backlog_manifest = tmp_path / "post-launch-backlog-export.manifest.json"
    readiness_manifest = tmp_path / "readiness-manifest.json"
    readiness_summary = tmp_path / "readiness-summary.json"
    known_issues = tmp_path / "known_issues_register.md"
    output_dir = tmp_path / "ga-launch"
    out_manifest = tmp_path / "ga-launch-package.manifest.json"
    summary_out = tmp_path / "ga-launch-summary.json"

    _write_json(
        backlog_manifest,
        {
            "bundle_type": "phase13_post_launch_release_backlog_package",
            "release_candidates": [
                {
                    "triage_id": "TRIAGE-100",
                    "category": "operator_flow",
                    "tier": "Medium",
                    "score": 9,
                    "backlog_lane": "next_release",
                    "route_rationale": "sample",
                }
            ],
            "runbook_patches": [],
            "monitoring_only": [],
            "deferred_items": [],
        },
    )
    _write_json(readiness_summary, {"overall_status": "passed"})
    _write_json(
        readiness_manifest,
        {
            "bundle_type": "readiness",
            "artifacts": {"readiness_summary": {"path": str(readiness_summary)}},
        },
    )
    _write_known_issues(known_issues)

    result = _run(
        "ga-launch-package-execute.ps1",
        "-BacklogExportManifestPath",
        str(backlog_manifest),
        "-KnownIssuesPath",
        str(known_issues),
        "-ReadinessManifestPath",
        str(readiness_manifest),
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(summary_out),
    )
    assert result.returncode == 0, result.stderr

    manifest_payload = json.loads(out_manifest.read_text(encoding="utf-8"))
    assert manifest_payload["bundle_type"] == "phase15_ga_launch_execution_package"
    assert manifest_payload["summary"]["decision"] in {
        "GO",
        "HOLD",
        "ROLLBACK_READY",
        "ROLLBACK_REQUIRED",
    }
    assert Path(manifest_payload["artifacts"]["release_candidate_manifest"]["path"]).exists()
    assert Path(manifest_payload["artifacts"]["release_decision_manifest"]["path"]).exists()
    assert Path(manifest_payload["artifacts"]["release_notes_manifest"]["path"]).exists()
    assert Path(manifest_payload["artifacts"]["known_issue_publication_manifest"]["path"]).exists()
    assert Path(manifest_payload["artifacts"]["release_train_evidence_manifest"]["path"]).exists()
    assert summary_out.exists()
