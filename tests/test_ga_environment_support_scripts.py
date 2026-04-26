import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
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
    reason="PowerShell is required for phase20 environment/support script tests.",
)
def test_ga_supported_environment_matrix_contract(tmp_path: Path) -> None:
    out_manifest = tmp_path / "matrix.manifest.json"
    out_summary = tmp_path / "matrix.summary.json"
    result = _run_script(
        "ga-supported-environment-matrix.ps1",
        "-OutputDir",
        str(tmp_path / "matrix"),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "phase20_supported_environment_matrix"
    assert summary["supported_environment_count"] >= 1
    assert summary["compatibility_baseline_decision"] == "go"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for phase20 environment/support script tests.",
)
def test_ga_compatibility_preflight_contract(tmp_path: Path) -> None:
    matrix_manifest = tmp_path / "matrix.manifest.json"
    _write_json(
        matrix_manifest,
        {
            "bundle_type": "phase20_supported_environment_matrix",
            "summary": {
                "supported_environment_count": 2,
                "unsupported_environment_count": 1,
                "compatibility_baseline_decision": "go",
            },
        },
    )
    readiness_manifest = tmp_path / "readiness-manifest.json"
    _write_json(
        readiness_manifest,
        {
            "bundle_type": "readiness",
            "summary": {"readiness_decision": "GO"},
        },
    )

    out_manifest = tmp_path / "preflight.manifest.json"
    out_summary = tmp_path / "preflight.summary.json"
    result = _run_script(
        "ga-compatibility-preflight.ps1",
        "-EnvironmentMatrixManifestPath",
        str(matrix_manifest),
        "-ReadinessManifestPath",
        str(readiness_manifest),
        "-OutputDir",
        str(tmp_path / "preflight"),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "phase20_compatibility_preflight_report"
    assert summary["required_check_count"] >= 1
    assert summary["compatibility_decision"] in {"go", "watch", "escalate"}


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for phase20 environment/support script tests.",
)
def test_ga_support_intake_normalization_contract(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs" / "self-serve"
    now = datetime.now(timezone.utc).isoformat()

    intake1 = logs_root / "run-1" / "support-intake.manifest.json"
    _write_json(
        intake1,
        {
            "bundle_type": "self_serve_support_intake_manifest",
            "generated_at_utc": now,
            "support_bundle_manifest_path": "x",
            "failure_classification_json_path": "y",
            "classification_status": "ok",
            "has_blocking_findings": False,
            "finding_count": 1,
            "required_attachments": ["a", "b"],
            "category_counts": {"runtime": 1},
            "severity_counts": {"high": 1},
        },
    )
    intake2 = logs_root / "run-2" / "support-intake.manifest.json"
    _write_json(
        intake2,
        {
            "bundle_type": "self_serve_support_intake_manifest",
            "generated_at_utc": now,
            "support_bundle_manifest_path": "x2",
            "failure_classification_json_path": "y2",
            "classification_status": "watch",
            "has_blocking_findings": True,
            "finding_count": 2,
            "required_attachments": ["c"],
            "category_counts": {"policy": 1},
            "severity_counts": {"critical": 1},
        },
    )

    out_manifest = tmp_path / "normalization.manifest.json"
    out_summary = tmp_path / "normalization.summary.json"
    result = _run_script(
        "ga-support-intake-normalization.ps1",
        "-LogsRoot",
        str(tmp_path / "logs"),
        "-WindowDays",
        "30",
        "-OutputDir",
        str(tmp_path / "normalization"),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "phase20_support_intake_normalization"
    assert summary["support_intake_manifest_count"] == 2
    assert summary["finding_count_total"] == 3
    assert summary["normalization_decision"] in {"go", "watch", "escalate"}


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for phase20 environment/support script tests.",
)
def test_ga_environment_support_closeout_contract(tmp_path: Path) -> None:
    matrix_manifest = tmp_path / "matrix.manifest.json"
    _write_json(
        matrix_manifest,
        {
            "bundle_type": "phase20_supported_environment_matrix",
            "summary": {"compatibility_baseline_decision": "go"},
        },
    )
    preflight_manifest = tmp_path / "preflight.manifest.json"
    _write_json(
        preflight_manifest,
        {
            "bundle_type": "phase20_compatibility_preflight_report",
            "summary": {"compatibility_decision": "go"},
        },
    )
    normalization_manifest = tmp_path / "normalization.manifest.json"
    _write_json(
        normalization_manifest,
        {
            "bundle_type": "phase20_support_intake_normalization",
            "summary": {"normalization_decision": "go"},
        },
    )

    out_manifest = tmp_path / "closeout.manifest.json"
    out_summary = tmp_path / "closeout.summary.json"
    result = _run_script(
        "ga-environment-support-closeout.ps1",
        "-EnvironmentMatrixManifestPath",
        str(matrix_manifest),
        "-CompatibilityManifestPath",
        str(preflight_manifest),
        "-SupportNormalizationManifestPath",
        str(normalization_manifest),
        "-OutputDir",
        str(tmp_path / "closeout"),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "phase20_environment_support_closeout"
    assert summary["closeout_decision"] == "go"

