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
        str(ROOT / "scripts" / "ga-weekly-reliability-review.ps1"),
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
    reason="PowerShell is required for GA weekly reliability review tests.",
)
def test_ga_weekly_reliability_review_aggregates_trend_and_hardening_inputs(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    trend_manifest = tmp_path / "trend.manifest.json"
    hardening_manifest = tmp_path / "hardening.manifest.json"
    output_dir = tmp_path / "weekly-review"
    out_manifest = tmp_path / "weekly-review.manifest.json"
    out_summary = tmp_path / "weekly-review.summary.json"

    _write_json(
        trend_manifest,
        {
            "bundle_type": "phase12_launch_week_support_trend_review",
            "analysis_window_utc": {"start": now, "end": now, "days": 7},
            "support_bundle_count": 4,
            "top_recurring_categories": [
                {"category": "runtime", "total_occurrences": 3, "impacted_bundle_count": 2}
            ],
        },
    )
    _write_json(
        hardening_manifest,
        {
            "bundle_type": "phase12_recurring_issue_pattern_hardening",
            "evidence_quality": {"schema_issue_count": 1},
            "schema_issues": [{"issue_kind": "missing_failure_classification_json"}],
            "hardening_actions": [
                {
                    "action_id": "P12-HARD-001",
                    "priority": "P1",
                    "runbook_delta": "runtime timeout triage",
                },
                {
                    "action_id": "P12-HARD-002",
                    "priority": "P2",
                    "runbook_delta": "policy decision tree tune",
                },
            ],
        },
    )

    result = _run_script(
        "-TrendManifestPath",
        str(trend_manifest),
        "-HardeningManifestPath",
        str(hardening_manifest),
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
        "-Zip",
    )
    assert result.returncode == 0, result.stderr

    payload = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "phase16_ga_weekly_reliability_review"
    assert summary["support_bundle_count"] == 4
    assert summary["top_recurring_category_count"] == 1
    assert summary["hardening_action_count"] == 2
    assert summary["p1_hardening_action_count"] == 1
    assert summary["schema_issue_count"] == 1
    assert summary["recommendation"] == "urgent_hardening_cycle"
    assert (output_dir.with_suffix(".zip")).exists()


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for GA weekly reliability review tests.",
)
def test_ga_weekly_reliability_review_rejects_invalid_bundle_types(tmp_path: Path) -> None:
    invalid_trend = tmp_path / "invalid-trend.manifest.json"
    _write_json(
        invalid_trend,
        {
            "bundle_type": "unexpected_bundle",
            "support_bundle_count": 0,
        },
    )

    result = _run_script("-TrendManifestPath", str(invalid_trend))
    assert result.returncode != 0
    assert "Unsupported trend bundle_type" in result.stderr
