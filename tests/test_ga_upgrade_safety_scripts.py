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
        timeout=300,
        check=False,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for phase19 upgrade safety script tests.",
)
def test_ga_upgrade_impact_matrix_generates_expected_manifest(tmp_path: Path) -> None:
    quarterly_manifest = tmp_path / "ga-quarterly-review-package.manifest.json"
    _write_json(
        quarterly_manifest,
        {
            "bundle_type": "phase18_quarterly_review_package",
            "summary": {
                "quarterly_review_decision": "watch",
                "owner_at_risk_count": 1,
                "carry_over_action_count": 2,
            },
        },
    )
    known_issues = tmp_path / "known_issues_register.md"
    known_issues.write_text(
        "| id | status |\n|---|---|\n| KI-1 | open |\n| KI-2 | mitigated |\n",
        encoding="utf-8",
    )

    out_manifest = tmp_path / "impact.manifest.json"
    out_summary = tmp_path / "impact.summary.json"
    result = _run_script(
        "ga-upgrade-impact-matrix.ps1",
        "-QuarterlyReviewManifestPath",
        str(quarterly_manifest),
        "-KnownIssuesPath",
        str(known_issues),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "phase19_upgrade_impact_matrix"
    assert summary["quarterly_review_decision"] == "watch"
    assert summary["known_issue_status_counts"]["open"] == 1
    assert summary["upgrade_impact_decision"] == "watch"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for phase19 upgrade safety script tests.",
)
def test_ga_migration_rehearsal_package_contract(tmp_path: Path) -> None:
    impact_manifest = tmp_path / "impact.manifest.json"
    _write_json(
        impact_manifest,
        {
            "bundle_type": "phase19_upgrade_impact_matrix",
            "summary": {"upgrade_impact_decision": "go"},
        },
    )
    readiness_manifest = tmp_path / "readiness-manifest-test.json"
    _write_json(
        readiness_manifest,
        {
            "summary": {"readiness_decision": "GO"},
        },
    )

    out_manifest = tmp_path / "rehearsal.manifest.json"
    out_summary = tmp_path / "rehearsal.summary.json"
    result = _run_script(
        "ga-migration-rehearsal-package.ps1",
        "-UpgradeImpactManifestPath",
        str(impact_manifest),
        "-ReadinessManifestPath",
        str(readiness_manifest),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "phase19_migration_rehearsal_package"
    assert summary["rehearsal_step_count"] >= 4
    assert summary["missing_required_script_count"] == 0


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for phase19 upgrade safety script tests.",
)
def test_ga_upgrade_rollback_safety_contract(tmp_path: Path) -> None:
    impact_manifest = tmp_path / "impact.manifest.json"
    _write_json(
        impact_manifest,
        {
            "bundle_type": "phase19_upgrade_impact_matrix",
            "summary": {"upgrade_impact_decision": "go"},
        },
    )
    rehearsal_manifest = tmp_path / "rehearsal.manifest.json"
    _write_json(
        rehearsal_manifest,
        {
            "bundle_type": "phase19_migration_rehearsal_package",
            "summary": {"rehearsal_ready": True},
        },
    )

    out_manifest = tmp_path / "rollback.manifest.json"
    out_summary = tmp_path / "rollback.summary.json"
    result = _run_script(
        "ga-upgrade-rollback-safety.ps1",
        "-UpgradeImpactManifestPath",
        str(impact_manifest),
        "-MigrationRehearsalManifestPath",
        str(rehearsal_manifest),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "phase19_upgrade_rollback_safety"
    assert summary["required_control_count"] >= 4
    assert summary["rollback_safety_decision"] == "go"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for phase19 upgrade safety script tests.",
)
def test_ga_upgrade_evidence_closeout_executes_full_chain(tmp_path: Path) -> None:
    quarterly_manifest = tmp_path / "ga-quarterly-review-package.manifest.json"
    _write_json(
        quarterly_manifest,
        {
            "bundle_type": "phase18_quarterly_review_package",
            "summary": {
                "quarterly_review_decision": "go",
                "owner_at_risk_count": 0,
                "carry_over_action_count": 0,
            },
        },
    )
    known_issues = tmp_path / "known_issues_register.md"
    known_issues.write_text("| id | status |\n|---|---|\n| KI-1 | mitigated |\n", encoding="utf-8")
    readiness_manifest = tmp_path / "readiness-manifest-test.json"
    _write_json(
        readiness_manifest,
        {
            "summary": {"readiness_decision": "GO"},
        },
    )

    out_dir = tmp_path / "phase19-closeout"
    out_manifest = out_dir / "closeout.manifest.json"
    out_summary = out_dir / "closeout.summary.json"
    result = _run_script(
        "ga-upgrade-evidence-closeout.ps1",
        "-QuarterlyReviewManifestPath",
        str(quarterly_manifest),
        "-KnownIssuesPath",
        str(known_issues),
        "-ReadinessManifestPath",
        str(readiness_manifest),
        "-OutputDir",
        str(out_dir),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "phase19_upgrade_evidence_closeout"
    assert summary["impact_decision"] == "go"
    assert summary["rollback_decision"] == "go"
    assert summary["closeout_decision"] == "go"
