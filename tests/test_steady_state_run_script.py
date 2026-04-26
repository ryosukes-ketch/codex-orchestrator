import json
import os
import shutil
import subprocess
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
        str(ROOT / "scripts" / "steady-state-run.ps1"),
        *args,
    ]
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for steady-state runtime loop tests.",
)
def test_steady_state_run_daily_contract(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    state_path = tmp_path / "steady_state_runtime_state.json"
    known_issues_path = tmp_path / "known_issues_register.md"
    staging_path = tmp_path / "staging_execution_record.md"
    out_dir = tmp_path / "steady-state-run"
    out_manifest = out_dir / "steady-state-run.manifest.json"
    out_summary = out_dir / "steady-state-run.summary.json"
    owner_ack_path = tmp_path / "owner-ack.json"
    _write_json(owner_ack_path, {"rules": []})

    _write_json(
        logs_root / "ga-adoption" / "monthly" / "ga-monthly-reliability-targets.manifest.json",
        {
            "bundle_type": "phase17_ga_monthly_reliability_target_package",
            "summary": {"monthly_decision": "go", "monthly_decision_reasons": ["monthly healthy"]},
        },
    )
    _write_json(
        logs_root / "ga-adoption" / "quarterly" / "ga-quarterly-review-package.manifest.json",
        {
            "bundle_type": "phase18_quarterly_review_package",
            "summary": {
                "quarterly_review_decision": "watch",
                "quarterly_review_decision_reasons": ["quarterly watch posture"],
            },
        },
    )
    _write_json(
        logs_root / "release-train" / "evidence" / "release-train-evidence.manifest.json",
        {
            "bundle_type": "phase14_release_train_evidence",
            "summary": {"decision": "HOLD"},
            "next_steps": ["release hold reason"],
        },
    )

    result = _run_script(
        "-Mode",
        "daily",
        "-LogsRoot",
        str(logs_root),
        "-StatePath",
        str(state_path),
        "-KnownIssuesPath",
        str(known_issues_path),
        "-StagingRecordPath",
        str(staging_path),
        "-OutputDir",
        str(out_dir),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
        "-WatchlistOwnerAckPath",
        str(owner_ack_path),
        "-Zip",
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert manifest["bundle_type"] == "steady_state_runtime_loop"
    assert summary["mode"] == "daily"
    assert summary["overall_checkpoint_decision"] == "escalate"
    assert summary["overall_watchlist_decision"] == "escalate"
    assert summary["known_issue_update_count"] >= 1
    assert state["last_status"] in {"ok", "paused"}
    assert state["last_checkpoint_manifest"] != ""
    assert state["last_watchlist_manifest"] != ""
    assert known_issues_path.exists()
    known_issues_text = known_issues_path.read_text(encoding="utf-8")
    assert "KI-STEADY-RELEASE-OWNER-PENDING" in known_issues_text
    staging_text = staging_path.read_text(encoding="utf-8")
    assert "Steady-state runtime loop cycle" in staging_text


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for steady-state runtime loop tests.",
)
def test_steady_state_run_pauses_on_repeated_escalation(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    state_path = tmp_path / "steady_state_runtime_state.json"
    known_issues_path = tmp_path / "known_issues_register.md"
    staging_path = tmp_path / "staging_execution_record.md"
    out_dir = tmp_path / "steady-state-run"
    out_manifest = out_dir / "steady-state-run.manifest.json"
    out_summary = out_dir / "steady-state-run.summary.json"
    owner_ack_path = tmp_path / "owner-ack.json"
    _write_json(owner_ack_path, {"rules": []})

    _write_json(
        state_path,
        {
            "last_run_at": "2026-04-24T00:00:00Z",
            "last_status": "ok",
            "last_cycle_id": "previous-cycle",
            "last_checkpoint_manifest": "",
            "last_watchlist_manifest": "",
            "last_known_issue_update": "",
            "consecutive_escalate_count": 1,
            "open_watch_count": 1,
            "open_escalate_count": 1,
            "last_owner_assignment_pending_count": 1,
            "paused_reason": "",
            "consecutive_external_blocker_count": 0,
        },
    )
    _write_json(
        logs_root / "ga-adoption" / "monthly" / "ga-monthly-reliability-targets.manifest.json",
        {
            "bundle_type": "phase17_ga_monthly_reliability_target_package",
            "summary": {"monthly_decision": "go", "monthly_decision_reasons": ["monthly healthy"]},
        },
    )
    _write_json(
        logs_root / "ga-adoption" / "quarterly" / "ga-quarterly-review-package.manifest.json",
        {
            "bundle_type": "phase18_quarterly_review_package",
            "summary": {
                "quarterly_review_decision": "watch",
                "quarterly_review_decision_reasons": ["quarterly watch posture"],
            },
        },
    )
    _write_json(
        logs_root / "release-train" / "evidence" / "release-train-evidence.manifest.json",
        {
            "bundle_type": "phase14_release_train_evidence",
            "summary": {"decision": "HOLD"},
            "next_steps": ["release hold reason"],
        },
    )

    result = _run_script(
        "-Mode",
        "daily",
        "-LogsRoot",
        str(logs_root),
        "-StatePath",
        str(state_path),
        "-KnownIssuesPath",
        str(known_issues_path),
        "-StagingRecordPath",
        str(staging_path),
        "-OutputDir",
        str(out_dir),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
        "-WatchlistOwnerAckPath",
        str(owner_ack_path),
        "-MaxConsecutiveEscalateCount",
        "2",
        "-MaxOwnerAssignmentPendingCount",
        "99",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert summary["paused"] is True
    assert "repeated escalation threshold reached" in summary["paused_reason"]
    assert state["last_status"] == "paused"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for steady-state runtime loop tests.",
)
def test_steady_state_run_owner_ack_prevents_repeated_escalation_pause(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    state_path = tmp_path / "steady_state_runtime_state.json"
    known_issues_path = tmp_path / "known_issues_register.md"
    staging_path = tmp_path / "staging_execution_record.md"
    out_dir = tmp_path / "steady-state-run"
    out_manifest = out_dir / "steady-state-run.manifest.json"
    out_summary = out_dir / "steady-state-run.summary.json"
    owner_ack_path = tmp_path / "owner-ack.json"

    _write_json(
        owner_ack_path,
        {
            "rules": [
                {
                    "id": "release-lane-owner-ack",
                    "enabled": True,
                    "checkpoint_lane": "release",
                    "decision": "escalate",
                    "source_bundle_type": "phase14_release_train_evidence",
                    "status": "tracking",
                    "owner": "release_ops_owner",
                }
            ]
        },
    )
    _write_json(
        state_path,
        {
            "last_run_at": "2026-04-24T00:00:00Z",
            "last_status": "ok",
            "last_cycle_id": "previous-cycle",
            "last_checkpoint_manifest": "",
            "last_watchlist_manifest": "",
            "last_known_issue_update": "",
            "consecutive_escalate_count": 5,
            "open_watch_count": 1,
            "open_escalate_count": 1,
            "last_owner_assignment_pending_count": 1,
            "paused_reason": "",
            "consecutive_external_blocker_count": 0,
        },
    )
    _write_json(
        logs_root / "ga-adoption" / "monthly" / "ga-monthly-reliability-targets.manifest.json",
        {
            "bundle_type": "phase17_ga_monthly_reliability_target_package",
            "summary": {"monthly_decision": "go", "monthly_decision_reasons": ["monthly healthy"]},
        },
    )
    _write_json(
        logs_root / "ga-adoption" / "quarterly" / "ga-quarterly-review-package.manifest.json",
        {
            "bundle_type": "phase18_quarterly_review_package",
            "summary": {
                "quarterly_review_decision": "watch",
                "quarterly_review_decision_reasons": ["quarterly watch posture"],
            },
        },
    )
    _write_json(
        logs_root / "release-train" / "evidence" / "release-train-evidence.manifest.json",
        {
            "bundle_type": "phase14_release_train_evidence",
            "summary": {"decision": "HOLD"},
            "next_steps": ["release hold reason"],
        },
    )

    result = _run_script(
        "-Mode",
        "daily",
        "-LogsRoot",
        str(logs_root),
        "-StatePath",
        str(state_path),
        "-KnownIssuesPath",
        str(known_issues_path),
        "-StagingRecordPath",
        str(staging_path),
        "-OutputDir",
        str(out_dir),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
        "-WatchlistOwnerAckPath",
        str(owner_ack_path),
        "-MaxConsecutiveEscalateCount",
        "2",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert summary["overall_checkpoint_decision"] == "escalate"
    assert summary["owner_assignment_pending_count"] == 0
    assert summary["owner_ack_applied_count"] == 1
    assert summary["consecutive_escalate_count"] == 0
    assert summary["paused"] is False
    assert state["last_status"] == "ok"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for steady-state runtime loop tests.",
)
def test_steady_state_run_with_openclaw_check_writes_evidence_fields(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    state_path = tmp_path / "steady_state_runtime_state.json"
    known_issues_path = tmp_path / "known_issues_register.md"
    staging_path = tmp_path / "staging_execution_record.md"
    out_dir = tmp_path / "steady-state-run"
    out_manifest = out_dir / "steady-state-run.manifest.json"
    out_summary = out_dir / "steady-state-run.summary.json"
    owner_ack_path = tmp_path / "owner-ack.json"
    openclaw_script = tmp_path / "openclaw-evidence-capture-mock.ps1"

    _write_json(owner_ack_path, {"rules": []})
    _write_json(
        logs_root / "ga-adoption" / "monthly" / "ga-monthly-reliability-targets.manifest.json",
        {
            "bundle_type": "phase17_ga_monthly_reliability_target_package",
            "summary": {"monthly_decision": "go", "monthly_decision_reasons": ["monthly healthy"]},
        },
    )
    _write_json(
        logs_root / "ga-adoption" / "quarterly" / "ga-quarterly-review-package.manifest.json",
        {
            "bundle_type": "phase18_quarterly_review_package",
            "summary": {
                "quarterly_review_decision": "watch",
                "quarterly_review_decision_reasons": ["quarterly watch posture"],
            },
        },
    )
    _write_json(
        logs_root / "release-train" / "evidence" / "release-train-evidence.manifest.json",
        {
            "bundle_type": "phase14_release_train_evidence",
            "summary": {"decision": "HOLD"},
            "next_steps": ["release hold reason"],
        },
    )

    openclaw_script.write_text(
        "\n".join(
            [
                "param(",
                "  [string]$GatewayBaseUrl = '',",
                "  [string]$AgentId = 'default',",
                "  [string]$BackendModel = '',",
                "  [string]$AuthToken = '',",
                "  [int]$TimeoutSec = 0,",
                "  [int]$ProbeTimeoutSec = 0,",
                "  [string]$EvidenceOutPath = '',",
                "  [string]$VerifiedBy = '',",
                "  [switch]$NoAppendStagingRecord",
                ")",
                "$dir = Split-Path -Parent $EvidenceOutPath",
                "if (-not [string]::IsNullOrWhiteSpace($dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }",
                "$payload = @{",
                "  gateway_response_success = $true",
                "  models_probe_control_html = $false",
                "  used_endpoint = 'chat/completions'",
                "}",
                "$json = $payload | ConvertTo-Json -Depth 5",
                "Set-Content -Path $EvidenceOutPath -Value $json -Encoding UTF8",
                "Write-Host '[done] mock openclaw evidence'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_script(
        "-Mode",
        "daily",
        "-LogsRoot",
        str(logs_root),
        "-StatePath",
        str(state_path),
        "-KnownIssuesPath",
        str(known_issues_path),
        "-StagingRecordPath",
        str(staging_path),
        "-OutputDir",
        str(out_dir),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
        "-WatchlistOwnerAckPath",
        str(owner_ack_path),
        "-RunOpenClawGatewayCheck",
        "-OpenClawEvidenceCaptureScriptPath",
        str(openclaw_script),
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert summary["openclaw_check_enabled"] is True
    assert summary["openclaw_check_status"] == "passed"
    assert summary["openclaw_evidence_path"]
    assert Path(summary["openclaw_evidence_path"]).exists()
    assert state["last_openclaw_status"] == "passed"
    assert Path(state["last_openclaw_evidence_path"]).exists()
    openclaw_artifact = manifest["artifacts"]["openclaw_evidence"]
    assert openclaw_artifact["path"] == summary["openclaw_evidence_path"]
