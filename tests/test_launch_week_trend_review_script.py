import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
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
        str(ROOT / "scripts" / "launch-week-trend-review.ps1"),
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
    reason="PowerShell is required for launch-week trend review script tests.",
)
def test_launch_week_trend_review_generates_manifest_and_backlog(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    now = datetime.now(timezone.utc)

    def create_support_bundle(
        name: str,
        *,
        generated_at: datetime,
        category_counts: dict,
        severity_counts: dict,
        findings: list[dict],
    ) -> None:
        bundle_dir = logs_root / name
        class_path = bundle_dir / "failure-classification.json"
        manifest_path = bundle_dir / "support-bundle.manifest.json"
        _write_json(
            class_path,
            {
                "classification_status": "issues_detected",
                "finding_count": len(findings),
                "category_counts": category_counts,
                "severity_counts": severity_counts,
                "findings": findings,
            },
        )
        _write_json(
            manifest_path,
            {
                "bundle_type": "pilot_support_bundle_manifest",
                "generated_at_utc": generated_at.isoformat(),
                "failure_classification_json_path": str(class_path),
            },
        )

    create_support_bundle(
        "recent-runtime-policy",
        generated_at=now - timedelta(days=1),
        category_counts={"runtime": 2, "policy": 1, "semantic_output": 0},
        severity_counts={"error": 2, "warning": 1},
        findings=[
            {"category": "runtime", "message": "gateway timeout", "severity": "error"},
            {"category": "runtime", "message": "gateway timeout", "severity": "error"},
            {"category": "policy", "message": "allowlist mismatch", "severity": "warning"},
        ],
    )
    create_support_bundle(
        "recent-semantic",
        generated_at=now - timedelta(days=2),
        category_counts={"runtime": 1, "semantic_output": 2},
        severity_counts={"error": 1, "warning": 2},
        findings=[
            {"category": "semantic_output", "message": "non_json_response", "severity": "warning"},
            {"category": "semantic_output", "message": "non_json_response", "severity": "warning"},
            {"category": "runtime", "message": "responses timeout", "severity": "error"},
        ],
    )
    create_support_bundle(
        "old-ignored",
        generated_at=now - timedelta(days=10),
        category_counts={"policy": 4},
        severity_counts={"error": 4},
        findings=[
            {"category": "policy", "message": "old issue", "severity": "error"},
        ],
    )

    output_dir = tmp_path / "trend-out"
    manifest_path = tmp_path / "launch-week-trend.manifest.json"
    trend_doc_path = tmp_path / "launch_week_support_trend_review.md"
    backlog_doc_path = tmp_path / "launch_week_runbook_delta_backlog.md"
    result = _run_script(
        "-LogsRoot",
        str(logs_root),
        "-WindowDays",
        "7",
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(manifest_path),
        "-TrendDocPath",
        str(trend_doc_path),
        "-BacklogDocPath",
        str(backlog_doc_path),
    )

    assert result.returncode == 0, result.stderr
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "phase12_launch_week_support_trend_review"
    assert payload["support_bundle_count"] == 2
    assert payload["aggregate_category_counts"]["runtime"] == 3
    assert payload["aggregate_category_counts"]["semantic_output"] == 2
    assert payload["aggregate_category_counts"]["policy"] == 1
    assert len(payload["top_recurring_categories"]) >= 2
    assert len(payload["runbook_delta_backlog"]) >= 2
    assert trend_doc_path.exists()
    assert backlog_doc_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for launch-week trend review script tests.",
)
def test_launch_week_trend_review_handles_empty_window_without_failure(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)
    output_dir = tmp_path / "empty-out"
    manifest_path = tmp_path / "empty.manifest.json"
    trend_doc_path = tmp_path / "empty-trend.md"
    backlog_doc_path = tmp_path / "empty-backlog.md"
    result = _run_script(
        "-LogsRoot",
        str(logs_root),
        "-WindowDays",
        "7",
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(manifest_path),
        "-TrendDocPath",
        str(trend_doc_path),
        "-BacklogDocPath",
        str(backlog_doc_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["support_bundle_count"] == 0
    assert payload["top_recurring_categories"] == []
    assert payload["runbook_delta_backlog"] == []
    assert trend_doc_path.exists()
    assert backlog_doc_path.exists()
