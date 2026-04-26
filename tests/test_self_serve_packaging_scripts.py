import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.state.repository import SqliteProjectRepository

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
        timeout=240,
        check=False,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for self-serve packaging script tests.",
)
def test_self_serve_update_guard_emits_backup_and_export_manifests(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    repository = SqliteProjectRepository(str(db_path))
    repository.initialize_schema()
    repository.close()

    output_dir = tmp_path / "update-guard"
    manifest_path = tmp_path / "update-guard.manifest.json"
    result = _run_script(
        "self-serve-update-guard.ps1",
        "-SqliteDbPath",
        str(db_path),
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(manifest_path),
    )
    assert result.returncode == 0, result.stderr
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "self_serve_update_guard"
    assert Path(payload["sqlite_verify_report_path"]).exists()
    assert Path(payload["sqlite_backup_manifest_path"]).exists()
    assert Path(payload["sqlite_export_manifest_path"]).exists()
    assert payload["replay_generated"] is False


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for self-serve packaging script tests.",
)
def test_self_serve_support_intake_uses_existing_support_bundle_manifest(
    tmp_path: Path,
) -> None:
    support_dir = tmp_path / "support"
    class_json = support_dir / "failure-classification.json"
    support_manifest = support_dir / "support-bundle.manifest.json"
    replay_manifest = support_dir / "replay-export.manifest.json"

    _write_json(class_json, {
        "classification_status": "no_blocking_issues",
        "has_blocking_findings": False,
        "finding_count": 0,
        "category_counts": {"runtime": 0},
        "severity_counts": {"error": 0},
    })
    _write_json(replay_manifest, {"bundle_type": "operator_replay_export"})
    _write_json(
        support_manifest,
        {
            "bundle_type": "pilot_support_bundle_manifest",
            "failure_classification_json_path": str(class_json),
            "replay_export_manifest_path": str(replay_manifest),
        },
    )

    output_dir = tmp_path / "intake-out"
    intake_manifest = tmp_path / "support-intake.manifest.json"
    result = _run_script(
        "self-serve-support-intake.ps1",
        "-SupportBundleManifestPath",
        str(support_manifest),
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(intake_manifest),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(intake_manifest.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "self_serve_support_intake_manifest"
    assert payload["classification_status"] == "no_blocking_issues"
    assert payload["has_blocking_findings"] is False
    assert Path(payload["support_intake_markdown_path"]).exists()


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for self-serve packaging script tests.",
)
def test_self_serve_handoff_package_ready_for_handoff_with_clean_inputs(
    tmp_path: Path,
) -> None:
    readiness_manifest = tmp_path / "readiness-manifest.json"
    support_intake_manifest = tmp_path / "support-intake.manifest.json"
    support_md = tmp_path / "support-intake.md"
    support_class = tmp_path / "failure-classification.json"

    _write_json(readiness_manifest, {"bundle_type": "readiness"})
    support_md.write_text("# support intake\n", encoding="utf-8")
    _write_json(support_class, {"classification_status": "no_blocking_issues"})
    _write_json(
        support_intake_manifest,
        {
            "bundle_type": "self_serve_support_intake_manifest",
            "classification_status": "no_blocking_issues",
            "has_blocking_findings": False,
            "finding_count": 0,
            "support_intake_markdown_path": str(support_md),
            "failure_classification_json_path": str(support_class),
        },
    )

    output_dir = tmp_path / "handoff"
    handoff_manifest = tmp_path / "handoff-package.manifest.json"
    result = _run_script(
        "self-serve-handoff-package.ps1",
        "-ReadinessManifestPath",
        str(readiness_manifest),
        "-SupportIntakeManifestPath",
        str(support_intake_manifest),
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(handoff_manifest),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(handoff_manifest.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "self_serve_handoff_package"
    assert payload["acceptance_status"] == "ready_for_handoff"
    assert payload["support_intake_summary"]["has_blocking_findings"] is False
    assert Path(payload["handoff_markdown_path"]).exists()
