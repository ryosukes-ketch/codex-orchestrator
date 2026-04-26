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
        str(ROOT / "scripts" / "ga-monthly-reliability-targets.ps1"),
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
            "| KI-001 | Runtime timeout issue | P1 | open | ops | 2026-04-01T00:00:00Z | retry | triage |\n"
            "| KI-002 | Policy branch issue | P2 | mitigated | ops | 2026-04-02T00:00:00Z | strict rerun | monitor |\n"
            "| KI-003 | Semantic drift issue | P3 | resolved | ops | 2026-04-03T00:00:00Z | n/a | close |\n"
        ),
        encoding="utf-8",
    )


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for GA monthly reliability script tests.",
)
def test_ga_monthly_reliability_targets_aggregates_weekly_and_routing_inputs(
    tmp_path: Path,
) -> None:
    logs_root = tmp_path / "logs"
    now = datetime.now(timezone.utc)

    weekly_1 = logs_root / "ga-adoption" / "weekly-review-1" / "ga-weekly-reliability-review.manifest.json"
    weekly_2 = logs_root / "ga-adoption" / "weekly-review-2" / "ga-weekly-reliability-review.manifest.json"

    _write_json(
        weekly_1,
        {
            "bundle_type": "phase16_ga_weekly_reliability_review",
            "generated_at_utc": (now - timedelta(days=5)).isoformat(),
            "summary": {
                "support_bundle_count": 3,
                "top_recurring_category_count": 1,
                "hardening_action_count": 2,
                "p1_hardening_action_count": 1,
                "schema_issue_count": 0,
                "recommendation": "targeted_hardening_cycle",
            },
            "details": {
                "top_recurring_categories": [
                    {"category": "runtime", "total_occurrences": 3},
                ],
                "hardening_actions": [
                    {
                        "action_id": "P12-HARD-001",
                        "status": "planned",
                        "priority": "P1",
                        "category": "runtime",
                        "runbook_delta": "runtime timeout triage",
                    },
                    {
                        "action_id": "P12-HARD-002",
                        "status": "done",
                        "priority": "P2",
                        "category": "policy",
                        "runbook_delta": "policy deny map",
                    },
                ],
            },
        },
    )
    _write_json(
        weekly_2,
        {
            "bundle_type": "phase16_ga_weekly_reliability_review",
            "generated_at_utc": (now - timedelta(days=2)).isoformat(),
            "summary": {
                "support_bundle_count": 2,
                "top_recurring_category_count": 0,
                "hardening_action_count": 1,
                "p1_hardening_action_count": 0,
                "schema_issue_count": 0,
                "recommendation": "monitor_only_cycle",
            },
            "details": {
                "top_recurring_categories": [],
                "hardening_actions": [
                    {
                        "action_id": "P12-HARD-003",
                        "status": "planned",
                        "priority": "P3",
                        "category": "none",
                        "runbook_delta": "monitor",
                    }
                ],
            },
        },
    )

    route_manifest = logs_root / "ga-launch" / "closeout-1" / "hotfix-next-release-route.manifest.json"
    _write_json(
        route_manifest,
        {
            "bundle_type": "phase15_hotfix_next_release_routing",
            "generated_at_utc": (now - timedelta(days=1)).isoformat(),
            "summary": {
                "routed_item_count": 3,
                "hotfix_candidate_count": 1,
                "next_release_candidate_count": 1,
                "monitoring_only_count": 1,
                "deferred_count": 0,
            },
        },
    )

    known_issues_path = tmp_path / "known_issues_register.md"
    _write_known_issues(known_issues_path)

    output_dir = tmp_path / "monthly-targets"
    out_manifest = tmp_path / "ga-monthly-reliability-targets.manifest.json"
    out_summary = tmp_path / "ga-monthly-reliability-targets.summary.json"

    result = _run_script(
        "-LogsRoot",
        str(logs_root),
        "-KnownIssuesPath",
        str(known_issues_path),
        "-WindowDays",
        "30",
        "-ClosureSlaP1Days",
        "3",
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
        "-Zip",
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))

    assert manifest["bundle_type"] == "phase17_ga_monthly_reliability_target_package"
    assert summary["weekly_review_count"] == 2
    assert summary["support_bundle_count_total"] == 5
    assert summary["routing_summary"]["hotfix_candidate_count"] == 1
    assert summary["known_issue_snapshot"]["open"] == 1
    assert summary["closure_sla"]["overdue_p1_count"] == 1
    assert summary["monthly_decision"] == "escalate"
    assert summary["reliability_health_score"] < 100
    assert (output_dir.with_suffix(".zip")).exists()


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for GA monthly reliability script tests.",
)
def test_ga_monthly_reliability_targets_rejects_invalid_weekly_bundle_type(
    tmp_path: Path,
) -> None:
    logs_root = tmp_path / "logs"
    invalid_weekly = logs_root / "ga-adoption" / "weekly-review-invalid" / "ga-weekly-reliability-review.manifest.json"
    _write_json(
        invalid_weekly,
        {
            "bundle_type": "unexpected_bundle",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "summary": {"support_bundle_count": 0},
            "details": {"top_recurring_categories": [], "hardening_actions": []},
        },
    )

    result = _run_script("-LogsRoot", str(logs_root), "-WindowDays", "30")
    assert result.returncode != 0
    assert "Unsupported weekly bundle_type" in result.stderr

