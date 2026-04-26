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
        str(ROOT / "scripts" / "support-recurring-hardening.ps1"),
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
    reason="PowerShell is required for recurring hardening script tests.",
)
def test_support_recurring_hardening_generates_actions_for_recurring_and_schema_issues(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    now = datetime.now(timezone.utc).isoformat()

    bundle_a = logs_root / "bundle-a"
    class_a = bundle_a / "failure-classification.json"
    manifest_a = bundle_a / "support-bundle.manifest.json"
    _write_json(
        class_a,
        {
            "classification_status": "issues_detected",
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
            "severity_counts": {"error": 2, "warning": 0, "info": 0},
            "findings": [
                {"category": "runtime", "message": "gateway timeout 123", "severity": "error"},
                {"category": "runtime", "message": "gateway timeout 999", "severity": "error"},
            ],
            "next_steps": ["a", "b", "c"],
        },
    )
    _write_json(
        manifest_a,
        {
            "bundle_type": "pilot_support_bundle_manifest",
            "generated_at_utc": now,
            "failure_classification_json_path": str(class_a),
        },
    )

    bundle_b = logs_root / "bundle-b"
    class_b = bundle_b / "failure-classification.json"
    manifest_b = bundle_b / "support-bundle.manifest.json"
    # intentionally missing severity key "info" to create schema issue
    _write_json(
        class_b,
        {
            "classification_status": "issues_detected",
            "finding_count": 1,
            "category_counts": {
                "runtime": 1,
                "provider_auth": 0,
                "policy": 0,
                "semantic_output": 0,
                "persistence_restore": 0,
                "operator_flow": 0,
                "unknown": 0,
            },
            "severity_counts": {"error": 1, "warning": 0},
            "findings": [
                {"category": "runtime", "message": "gateway timeout 42", "severity": "error"},
            ],
            "next_steps": ["a", "b", "c"],
        },
    )
    _write_json(
        manifest_b,
        {
            "bundle_type": "pilot_support_bundle_manifest",
            "generated_at_utc": now,
            "failure_classification_json_path": str(class_b),
        },
    )

    trend_manifest = tmp_path / "launch-week-trend.manifest.json"
    _write_json(
        trend_manifest,
        {
            "bundle_type": "phase12_launch_week_support_trend_review",
            "analysis_window_utc": {"start": now, "end": now, "days": 7},
            "support_bundle_count": 2,
            "source_support_bundles": [
                {
                    "support_bundle_manifest_path": str(manifest_a),
                    "failure_classification_path": str(class_a),
                    "generated_at_utc": now,
                },
                {
                    "support_bundle_manifest_path": str(manifest_b),
                    "failure_classification_path": str(class_b),
                    "generated_at_utc": now,
                },
            ],
            "top_recurring_categories": [
                {
                    "rank": 1,
                    "category": "runtime",
                    "total_occurrences": 3,
                    "impacted_bundle_count": 2,
                }
            ],
        },
    )

    out_manifest = tmp_path / "recurring-hardening.manifest.json"
    out_doc = tmp_path / "phase12_recurring_issue_hardening.md"
    output_dir = tmp_path / "hardening-out"

    result = _run_script(
        "-TrendManifestPath",
        str(trend_manifest),
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(out_manifest),
        "-ReportDocPath",
        str(out_doc),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out_manifest.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "phase12_recurring_issue_pattern_hardening"
    assert payload["checked_support_bundle_count"] == 2
    assert payload["recurring_signal_count"] >= 1
    assert payload["evidence_quality"]["schema_issue_count"] >= 1
    action_types = {item["action_type"] for item in payload["hardening_actions"]}
    assert "recurring_category_hardening" in action_types
    assert "support_evidence_schema_hardening" in action_types
    assert out_doc.exists()


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for recurring hardening script tests.",
)
def test_support_recurring_hardening_handles_empty_inputs_with_baseline_action(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    trend_manifest = tmp_path / "launch-week-trend-empty.manifest.json"
    _write_json(
        trend_manifest,
        {
            "bundle_type": "phase12_launch_week_support_trend_review",
            "analysis_window_utc": {"start": now, "end": now, "days": 7},
            "support_bundle_count": 0,
            "source_support_bundles": [],
            "top_recurring_categories": [],
        },
    )

    out_manifest = tmp_path / "recurring-empty.manifest.json"
    result = _run_script(
        "-TrendManifestPath",
        str(trend_manifest),
        "-OutPath",
        str(out_manifest),
        "-ReportDocPath",
        str(tmp_path / "phase12_recurring_issue_hardening.md"),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(out_manifest.read_text(encoding="utf-8"))
    assert payload["checked_support_bundle_count"] == 0
    assert payload["recurring_signal_count"] == 0
    assert len(payload["hardening_actions"]) == 1
    assert payload["hardening_actions"][0]["action_type"] == "baseline_monitoring"
