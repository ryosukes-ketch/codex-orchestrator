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
    reason="PowerShell is required for phase21/22 script tests.",
)
def test_phase21_script_contracts(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"

    # Seed minimal artifacts for traceability and ledger.
    _write_json(
        logs_root / "operational-readiness" / "readiness-manifest-test.json",
        {"bundle_type": "readiness", "summary": {"readiness_decision": "GO"}},
    )
    _write_json(
        logs_root / "release-train" / "x" / "release-train-evidence.manifest.json",
        {"bundle_type": "phase14_release_train_evidence_export"},
    )
    _write_json(
        logs_root / "ga-ops" / "x" / "phase20-environment-support-closeout.manifest.json",
        {"bundle_type": "phase20_environment_support_closeout"},
    )
    _write_json(
        logs_root / "self-serve" / "x" / "support-intake.manifest.json",
        {"bundle_type": "self_serve_support_intake_manifest"},
    )
    _write_json(
        logs_root / "ga-ops" / "x" / "ga-support-intake-normalization.manifest.json",
        {
            "bundle_type": "phase20_support_intake_normalization",
            "summary": {
                "normalization_decision": "go",
                "blocking_manifest_count": 0,
                "finding_count_total": 1,
                "missing_required_field_count": 0,
            },
        },
    )
    _write_json(
        logs_root / "post-launch-ops" / "x" / "post-launch-backlog-export.manifest.json",
        {
            "bundle_type": "phase13_post_launch_release_backlog_export",
            "summary": {
                "runbook_backlog_count": 1,
                "product_backlog_count": 1,
                "release_backlog_count": 1,
            },
        },
    )

    retention_manifest = tmp_path / "retention.manifest.json"
    retention_summary = tmp_path / "retention.summary.json"
    retention = _run_script(
        "ga-artifact-retention-coverage.ps1",
        "-LogsRoot",
        str(logs_root),
        "-OutputDir",
        str(tmp_path / "retention"),
        "-OutPath",
        str(retention_manifest),
        "-SummaryOutPath",
        str(retention_summary),
    )
    assert retention.returncode == 0, retention.stderr
    assert json.loads(retention_manifest.read_text(encoding="utf-8"))["bundle_type"] == (
        "phase21_artifact_retention_export_coverage"
    )

    trace_manifest = tmp_path / "trace.manifest.json"
    trace_summary = tmp_path / "trace.summary.json"
    trace = _run_script(
        "ga-audit-traceability-index.ps1",
        "-RetentionManifestPath",
        str(retention_manifest),
        "-LogsRoot",
        str(logs_root),
        "-OutputDir",
        str(tmp_path / "trace"),
        "-OutPath",
        str(trace_manifest),
        "-SummaryOutPath",
        str(trace_summary),
    )
    assert trace.returncode == 0, trace.stderr
    assert json.loads(trace_manifest.read_text(encoding="utf-8"))["bundle_type"] == (
        "phase21_audit_traceability_index"
    )

    ledger_manifest = tmp_path / "ledger.manifest.json"
    ledger_summary = tmp_path / "ledger.summary.json"
    ledger = _run_script(
        "ga-incident-change-ledger.ps1",
        "-SupportNormalizationManifestPath",
        str(logs_root / "ga-ops" / "x" / "ga-support-intake-normalization.manifest.json"),
        "-BacklogExportManifestPath",
        str(logs_root / "post-launch-ops" / "x" / "post-launch-backlog-export.manifest.json"),
        "-LogsRoot",
        str(logs_root),
        "-OutputDir",
        str(tmp_path / "ledger"),
        "-OutPath",
        str(ledger_manifest),
        "-SummaryOutPath",
        str(ledger_summary),
    )
    assert ledger.returncode == 0, ledger.stderr
    assert json.loads(ledger_manifest.read_text(encoding="utf-8"))["bundle_type"] == (
        "phase21_incident_change_ledger"
    )

    closeout_manifest = tmp_path / "phase21.manifest.json"
    closeout_summary = tmp_path / "phase21.summary.json"
    closeout = _run_script(
        "ga-auditability-closeout.ps1",
        "-RetentionManifestPath",
        str(retention_manifest),
        "-TraceabilityManifestPath",
        str(trace_manifest),
        "-LedgerManifestPath",
        str(ledger_manifest),
        "-LogsRoot",
        str(logs_root),
        "-OutputDir",
        str(tmp_path / "phase21"),
        "-OutPath",
        str(closeout_manifest),
        "-SummaryOutPath",
        str(closeout_summary),
    )
    assert closeout.returncode == 0, closeout.stderr
    closeout_payload = json.loads(closeout_manifest.read_text(encoding="utf-8"))
    assert closeout_payload["bundle_type"] == "phase21_auditability_closeout"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for phase21/22 script tests.",
)
def test_phase22_script_contracts(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    _write_json(
        logs_root / "ga-ops" / "x" / "phase20-environment-support-closeout.manifest.json",
        {"bundle_type": "phase20_environment_support_closeout"},
    )
    _write_json(
        logs_root / "ga-compliance" / "x" / "phase21-auditability-closeout.manifest.json",
        {"bundle_type": "phase21_auditability_closeout"},
    )
    _write_json(
        logs_root / "operational-readiness" / "readiness-manifest-test.json",
        {"bundle_type": "readiness", "summary": {"readiness_decision": "GO"}},
    )

    handbook_manifest = tmp_path / "handbook.manifest.json"
    handbook_summary = tmp_path / "handbook.summary.json"
    handbook = _run_script(
        "ga-steady-state-operations-handbook.ps1",
        "-OutputDir",
        str(tmp_path / "handbook"),
        "-OutPath",
        str(handbook_manifest),
        "-SummaryOutPath",
        str(handbook_summary),
    )
    assert handbook.returncode == 0, handbook.stderr
    assert json.loads(handbook_manifest.read_text(encoding="utf-8"))["bundle_type"] == (
        "phase22_steady_state_operations_handbook"
    )

    cadence_manifest = tmp_path / "cadence.manifest.json"
    cadence_summary = tmp_path / "cadence.summary.json"
    cadence = _run_script(
        "ga-release-ops-cadence-baseline.ps1",
        "-OutputDir",
        str(tmp_path / "cadence"),
        "-OutPath",
        str(cadence_manifest),
        "-SummaryOutPath",
        str(cadence_summary),
    )
    assert cadence.returncode == 0, cadence.stderr
    assert json.loads(cadence_manifest.read_text(encoding="utf-8"))["bundle_type"] == (
        "phase22_release_ops_cadence_baseline"
    )

    e2e_manifest = tmp_path / "e2e.manifest.json"
    e2e_summary = tmp_path / "e2e.summary.json"
    e2e = _run_script(
        "ga-end-to-end-operations-evidence.ps1",
        "-EnvironmentCloseoutManifestPath",
        str(logs_root / "ga-ops" / "x" / "phase20-environment-support-closeout.manifest.json"),
        "-AuditabilityCloseoutManifestPath",
        str(logs_root / "ga-compliance" / "x" / "phase21-auditability-closeout.manifest.json"),
        "-ReadinessManifestPath",
        str(logs_root / "operational-readiness" / "readiness-manifest-test.json"),
        "-LogsRoot",
        str(logs_root),
        "-OutputDir",
        str(tmp_path / "e2e"),
        "-OutPath",
        str(e2e_manifest),
        "-SummaryOutPath",
        str(e2e_summary),
    )
    assert e2e.returncode == 0, e2e.stderr
    assert json.loads(e2e_manifest.read_text(encoding="utf-8"))["bundle_type"] == (
        "phase22_end_to_end_operations_evidence"
    )

    closeout_manifest = tmp_path / "phase22.manifest.json"
    closeout_summary = tmp_path / "phase22.summary.json"
    closeout = _run_script(
        "ga-steady-state-closeout.ps1",
        "-HandbookManifestPath",
        str(handbook_manifest),
        "-CadenceManifestPath",
        str(cadence_manifest),
        "-EndToEndEvidenceManifestPath",
        str(e2e_manifest),
        "-LogsRoot",
        str(logs_root),
        "-OutputDir",
        str(tmp_path / "phase22"),
        "-OutPath",
        str(closeout_manifest),
        "-SummaryOutPath",
        str(closeout_summary),
    )
    assert closeout.returncode == 0, closeout.stderr
    closeout_payload = json.loads(closeout_manifest.read_text(encoding="utf-8"))
    assert closeout_payload["bundle_type"] == "phase22_steady_state_closeout"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for phase21/22 script tests.",
)
def test_steady_state_improvement_backlog_contract(tmp_path: Path) -> None:
    phase20_manifest = tmp_path / "phase20.manifest.json"
    phase21_manifest = tmp_path / "phase21.manifest.json"
    phase22_manifest = tmp_path / "phase22.manifest.json"
    _write_json(
        phase20_manifest,
        {
            "bundle_type": "phase20_environment_support_closeout",
            "summary": {
                "closeout_decision": "go",
                "closeout_decision_reasons": ["phase20 ok"],
            },
        },
    )
    _write_json(
        phase21_manifest,
        {
            "bundle_type": "phase21_auditability_closeout",
            "summary": {
                "closeout_decision": "watch",
                "closeout_decision_reasons": ["traceability follow-up needed"],
            },
        },
    )
    _write_json(
        phase22_manifest,
        {
            "bundle_type": "phase22_steady_state_closeout",
            "summary": {
                "closeout_decision": "go",
                "closeout_decision_reasons": ["steady-state activation ready"],
            },
        },
    )

    out_manifest = tmp_path / "steady-state-backlog.manifest.json"
    out_summary = tmp_path / "steady-state-backlog.summary.json"
    result = _run_script(
        "ga-steady-state-improvement-backlog.ps1",
        "-Phase20CloseoutManifestPath",
        str(phase20_manifest),
        "-Phase21CloseoutManifestPath",
        str(phase21_manifest),
        "-Phase22CloseoutManifestPath",
        str(phase22_manifest),
        "-OutputDir",
        str(tmp_path / "steady-state-backlog"),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "steady_state_improvement_backlog"
    assert summary["backlog_item_count"] == 1
    assert summary["steady_state_improvement_decision"] == "watch"
    backlog_items = manifest["details"]["backlog_items"]
    assert len(backlog_items) == 1
    assert backlog_items[0]["lane"] == "auditability_retention"
    assert backlog_items[0]["priority"] == "medium"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for steady-state script tests.",
)
def test_steady_state_burndown_contract(tmp_path: Path) -> None:
    backlog_manifest = tmp_path / "improvement-backlog.manifest.json"
    previous_burndown_manifest = tmp_path / "previous-burndown.manifest.json"
    _write_json(
        backlog_manifest,
        {
            "bundle_type": "steady_state_improvement_backlog",
            "details": {
                "backlog_items": [
                    {
                        "backlog_id": "b1",
                        "lane": "auditability_retention",
                        "status": "open",
                        "priority": "medium",
                    },
                    {
                        "backlog_id": "b2",
                        "lane": "environment_support",
                        "status": "done",
                        "priority": "medium",
                    },
                ]
            },
        },
    )
    _write_json(
        previous_burndown_manifest,
        {
            "bundle_type": "steady_state_burndown_tracking",
            "summary": {
                "open_item_count": 3,
            },
        },
    )

    out_manifest = tmp_path / "burndown.manifest.json"
    out_summary = tmp_path / "burndown.summary.json"
    result = _run_script(
        "ga-steady-state-burndown.ps1",
        "-ImprovementBacklogManifestPath",
        str(backlog_manifest),
        "-PreviousBurndownManifestPath",
        str(previous_burndown_manifest),
        "-OutputDir",
        str(tmp_path / "burndown"),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "steady_state_burndown_tracking"
    assert summary["open_item_count"] == 1
    assert summary["closed_item_count"] == 1
    assert summary["previous_open_item_count"] == 3
    assert summary["delta_open_item_count"] == -2
    assert summary["closed_since_previous_count"] == 2
    assert summary["burndown_decision"] == "watch"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for steady-state script tests.",
)
def test_steady_state_checkpoint_refresh_contract(tmp_path: Path) -> None:
    monthly_manifest = tmp_path / "monthly.manifest.json"
    quarterly_manifest = tmp_path / "quarterly.manifest.json"
    release_manifest = tmp_path / "release.manifest.json"
    previous_manifest = tmp_path / "previous-checkpoint.manifest.json"

    _write_json(
        monthly_manifest,
        {
            "bundle_type": "phase17_ga_monthly_reliability_target_package",
            "summary": {
                "monthly_decision": "go",
                "monthly_decision_reasons": ["monthly healthy"],
            },
        },
    )
    _write_json(
        quarterly_manifest,
        {
            "bundle_type": "phase18_quarterly_review_package",
            "summary": {
                "quarterly_review_decision": "watch",
                "quarterly_review_decision_reasons": ["quarterly watch"],
            },
        },
    )
    _write_json(
        release_manifest,
        {
            "bundle_type": "phase14_release_train_evidence",
            "summary": {
                "decision": "HOLD",
            },
            "next_steps": ["release hold due to unresolved blocker"],
        },
    )
    _write_json(
        previous_manifest,
        {
            "bundle_type": "steady_state_checkpoint_refresh",
            "summary": {
                "overall_checkpoint_decision": "watch",
            },
        },
    )

    out_manifest = tmp_path / "checkpoint.manifest.json"
    out_summary = tmp_path / "checkpoint.summary.json"
    result = _run_script(
        "ga-steady-state-checkpoint-refresh.ps1",
        "-MonthlyCheckpointManifestPath",
        str(monthly_manifest),
        "-QuarterlyCheckpointManifestPath",
        str(quarterly_manifest),
        "-ReleaseCheckpointManifestPath",
        str(release_manifest),
        "-PreviousCheckpointManifestPath",
        str(previous_manifest),
        "-OutputDir",
        str(tmp_path / "checkpoint"),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "steady_state_checkpoint_refresh"
    assert summary["checkpoint_count"] == 3
    assert summary["missing_checkpoint_count"] == 0
    assert summary["monthly_checkpoint_decision"] == "go"
    assert summary["quarterly_checkpoint_decision"] == "watch"
    assert summary["release_checkpoint_decision"] == "escalate"
    assert summary["overall_checkpoint_decision"] == "escalate"
    assert summary["overall_checkpoint_decision_delta"] == "regressed"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for steady-state script tests.",
)
def test_steady_state_watchlist_routing_contract(tmp_path: Path) -> None:
    checkpoint_manifest = tmp_path / "checkpoint.manifest.json"
    previous_watchlist_manifest = tmp_path / "previous-watchlist.manifest.json"
    owner_ack_path = tmp_path / "owner-ack.json"

    _write_json(
        checkpoint_manifest,
        {
            "bundle_type": "steady_state_checkpoint_refresh",
            "details": {
                "checkpoints": [
                    {
                        "checkpoint_lane": "monthly",
                        "source_manifest_path": "logs/monthly.manifest.json",
                        "source_bundle_type": "phase17_ga_monthly_reliability_target_package",
                        "checkpoint_decision": "watch",
                        "decision_reasons": ["monthly watch posture"],
                    },
                    {
                        "checkpoint_lane": "release",
                        "source_manifest_path": "logs/release.manifest.json",
                        "source_bundle_type": "phase14_release_train_evidence",
                        "checkpoint_decision": "escalate",
                        "decision_reasons": ["release lane escalation"],
                    },
                ]
            },
        },
    )
    _write_json(
        previous_watchlist_manifest,
        {
            "bundle_type": "steady_state_escalation_watchlist_routing",
            "summary": {
                "watchlist_item_count": 3,
            },
        },
    )
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

    out_manifest = tmp_path / "watchlist.manifest.json"
    out_summary = tmp_path / "watchlist.summary.json"
    result = _run_script(
        "ga-steady-state-escalation-watchlist-route.ps1",
        "-CheckpointManifestPath",
        str(checkpoint_manifest),
        "-PreviousRoutingManifestPath",
        str(previous_watchlist_manifest),
        "-OutputDir",
        str(tmp_path / "watchlist"),
        "-OutPath",
        str(out_manifest),
        "-SummaryOutPath",
        str(out_summary),
        "-OwnerAckPath",
        str(owner_ack_path),
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    summary = json.loads(out_summary.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "steady_state_escalation_watchlist_routing"
    assert summary["watchlist_item_count"] == 2
    assert summary["previous_watchlist_item_count"] == 3
    assert summary["delta_watchlist_item_count"] == -1
    assert summary["decision_counts"]["watch"] == 1
    assert summary["decision_counts"]["escalate"] == 1
    assert summary["overall_watchlist_decision"] == "escalate"
    assert summary["owner_ack_rules_count"] == 1
    assert summary["owner_ack_applied_count"] == 1

    item_fields = {
        "owner",
        "status",
        "eta_utc",
        "next_review_utc",
        "sla_days",
        "escalation_reason",
    }
    for item in manifest["details"]["watchlist_items"]:
        assert item_fields.issubset(set(item.keys()))
    release_items = [
        item
        for item in manifest["details"]["watchlist_items"]
        if item["checkpoint_lane"] == "release"
    ]
    assert release_items
    assert release_items[0]["status"] == "tracking"
    assert release_items[0]["owner_ack_applied"] is True
