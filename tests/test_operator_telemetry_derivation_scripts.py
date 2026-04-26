import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


def _run_operator_script(script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
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
        timeout=120,
        check=False,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_cycle_manifest(path: Path, *, project_id: str, audit_path: Path) -> None:
    _write_json(
        path,
        {
            "bundle_type": "cycle",
            "project_id": project_id,
            "artifacts": {
                "audit": {
                    "path": str(audit_path),
                    "relative_path": audit_path.name,
                }
            },
        },
    )


def _audit_without_stage_totals(project_id: str = "p-events-derived") -> dict:
    return {
        "project_id": project_id,
        "status": "completed",
        "history": [],
        "events": [
            {
                "event_type": "department_stage_executed",
                "actor": "system",
                "actor_role": "admin",
                "actor_type": "system",
                "timestamp": "2026-04-03T00:00:00Z",
                "reason": "",
                "metadata": {
                    "department": "build",
                    "stage_name": "Architect",
                    "sequence": 1,
                    "stage_success": True,
                    "fallback_used": False,
                    "effective_provider": "openclaw",
                    "effective_model": "openclaw/default",
                    "llm_transport_fallback_used": True,
                    "llm_endpoint": "responses",
                    "llm_http_status": 404,
                    "llm_error_kind": "http_status",
                    "llm_response_mode": "schema_aware_default",
                },
            },
            {
                "event_type": "department_stage_executed",
                "actor": "system",
                "actor_role": "admin",
                "actor_type": "system",
                "timestamp": "2026-04-03T00:00:01Z",
                "reason": "",
                "metadata": {
                    "department": "build",
                    "stage_name": "Coder",
                    "sequence": 2,
                    "parent_stage_name": "Architect",
                    "stage_success": True,
                    "fallback_used": False,
                    "effective_provider": "openclaw",
                    "effective_model": "openclaw/default",
                    "llm_transport_fallback_used": False,
                    "llm_endpoint": "chat/completions",
                    "llm_http_status": 200,
                    "llm_response_mode": "schema_aware_default",
                },
            },
            {
                "event_type": "department_stage_executed",
                "actor": "system",
                "actor_role": "admin",
                "actor_type": "system",
                "timestamp": "2026-04-03T00:00:02Z",
                "reason": "",
                "metadata": {
                    "department": "review",
                    "stage_name": "FinalJudgment",
                    "sequence": 1,
                    "stage_success": False,
                    "fallback_used": True,
                    "stage_failure_reason": "review finding",
                    "effective_provider": "openclaw",
                    "effective_model": "openclaw/default",
                    "llm_transport_fallback_used": False,
                    "llm_endpoint": "responses",
                    "llm_http_status": 200,
                    "llm_response_mode": "schema_aware_default",
                },
            },
        ],
        "approvals": [],
        "reviews": [],
        "checkpoints": [],
    }


def _audit_with_legacy_fallback_only_events(project_id: str = "p-events-legacy-fallback") -> dict:
    return {
        "project_id": project_id,
        "status": "completed",
        "history": [],
        "events": [
            {
                "event_type": "department_stage_executed",
                "actor": "system",
                "actor_role": "admin",
                "actor_type": "system",
                "timestamp": "2026-04-03T01:00:00Z",
                "reason": "",
                "metadata": {
                    "department": "build",
                    "stage_name": "Architect",
                    "sequence": 1,
                    "stage_success": False,
                    "fallback_used": True,
                    "effective_provider": "mock",
                    "effective_model": "mock",
                    "llm_transport_fallback_used": False,
                    "llm_response_mode": "schema_aware_default",
                },
            }
        ],
        "approvals": [],
        "reviews": [],
        "checkpoints": [],
    }


def _audit_with_upstream_rejection_events(project_id: str = "p-events-upstream-rejection") -> dict:
    return {
        "project_id": project_id,
        "status": "completed",
        "history": [],
        "events": [
            {
                "event_type": "department_stage_executed",
                "actor": "system",
                "actor_role": "admin",
                "actor_type": "system",
                "timestamp": "2026-04-08T09:00:00Z",
                "reason": "",
                "metadata": {
                    "department": "build",
                    "stage_name": "Architect",
                    "sequence": 1,
                    "stage_success": False,
                    "fallback_used": True,
                    "stage_failure_reason": "upstream_rejection:anthropic:credit_balance_too_low",
                    "effective_provider": "openclaw",
                    "effective_model": "openclaw/default",
                    "llm_transport_fallback_used": False,
                    "llm_endpoint": "chat/completions",
                    "llm_http_status": 200,
                    "llm_error_kind": "upstream_rejection",
                    "llm_response_mode": "plain_text_upstream_rejection",
                    "llm_content_kind": "upstream_rejection",
                    "llm_backend_override": "openai-codex/gpt-5.2",
                    "llm_upstream_rejection": True,
                    "llm_upstream_provider": "anthropic",
                    "llm_upstream_rejection_reason": "credit_balance_too_low",
                },
            }
        ],
        "approvals": [],
        "reviews": [],
        "checkpoints": [],
    }


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_stage_report_derives_telemetry_from_events_when_totals_missing(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-events-only.json"
    report_path = tmp_path / "stage-report.json"
    _write_json(audit_path, _audit_without_stage_totals())

    result = _run_operator_script(
        "operator-stage-report.ps1",
        "-ProjectId",
        "p-events-derived",
        "-AuditJsonPath",
        str(audit_path),
        "-RequireStageTelemetry",
        "-OutPath",
        str(report_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["telemetry_present"] is True
    assert payload["telemetry_source"] == "events_derived"
    assert payload["telemetry_legacy_fallback_normalizations"] == 0
    assert payload["stage_totals"]["total_stage_executions"] == 3
    assert payload["stage_totals"]["total_successes"] == 2
    assert payload["stage_totals"]["total_failures"] == 1
    assert payload["stage_totals"]["total_fallbacks"] == 1
    assert payload["stage_totals"]["total_llm_transport_fallbacks"] == 1
    assert sorted(payload["stage_totals"]["departments_covered"]) == ["build", "review"]
    assert "responses" in payload["stage_totals"]["llm_endpoints_observed"]
    assert "chat/completions" in payload["stage_totals"]["llm_endpoints_observed"]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_audit_assert_uses_events_derived_telemetry_with_budget_checks(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-events-only.json"
    assert_path = tmp_path / "audit-assert.json"
    _write_json(audit_path, _audit_without_stage_totals())

    result = _run_operator_script(
        "operator-audit-assert.ps1",
        "-ProjectId",
        "p-events-derived",
        "-AuditJsonPath",
        str(audit_path),
        "-ExpectedStatus",
        "completed",
        "-RequireStageTelemetry",
        "-MaxLlmTransportFallbacks",
        "1",
        "-OutPath",
        str(assert_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(assert_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["telemetry_present"] is True
    assert payload["telemetry_source"] == "events_derived"
    assert payload["telemetry_legacy_fallback_normalizations"] == 0
    assert payload["stage_totals"]["total_llm_transport_fallbacks"] == 1

    fail_path = tmp_path / "audit-assert-fail.json"
    fail_result = _run_operator_script(
        "operator-audit-assert.ps1",
        "-ProjectId",
        "p-events-derived",
        "-AuditJsonPath",
        str(audit_path),
        "-ExpectedStatus",
        "completed",
        "-RequireStageTelemetry",
        "-MaxLlmTransportFallbacks",
        "0",
        "-OutPath",
        str(fail_path),
    )
    assert fail_result.returncode != 0
    fail_payload = json.loads(fail_path.read_text(encoding="utf-8"))
    assert fail_payload["passed"] is False
    assert any("llm transport fallback exceeded limit" in item for item in fail_payload["errors"])


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_audit_assert_can_disable_event_derived_telemetry(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-events-only.json"
    assert_path = tmp_path / "audit-assert-no-derive.json"
    _write_json(audit_path, _audit_without_stage_totals())

    result = _run_operator_script(
        "operator-audit-assert.ps1",
        "-ProjectId",
        "p-events-derived",
        "-AuditJsonPath",
        str(audit_path),
        "-ExpectedStatus",
        "completed",
        "-RequireStageTelemetry",
        "-NoEventDerivedTelemetry",
        "-OutPath",
        str(assert_path),
    )
    assert result.returncode != 0
    payload = json.loads(assert_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["telemetry_present"] is False
    assert payload["telemetry_source"] == "none"
    assert any("stage telemetry is missing" in item for item in payload["errors"])


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_stage_report_normalizes_legacy_fallback_only_events_as_success(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-legacy-fallback.json"
    report_path = tmp_path / "stage-report-legacy.json"
    _write_json(audit_path, _audit_with_legacy_fallback_only_events())

    result = _run_operator_script(
        "operator-stage-report.ps1",
        "-ProjectId",
        "p-events-legacy-fallback",
        "-AuditJsonPath",
        str(audit_path),
        "-RequireStageTelemetry",
        "-OutPath",
        str(report_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["telemetry_present"] is True
    assert payload["telemetry_source"] == "events_derived"
    assert payload["telemetry_legacy_fallback_normalizations"] == 1
    assert payload["stage_totals"]["total_stage_executions"] == 1
    assert payload["stage_totals"]["total_successes"] == 1
    assert payload["stage_totals"]["total_failures"] == 0
    assert payload["stage_totals"]["total_fallbacks"] == 1
    assert payload["failing_stages"] == []
    assert len(payload["fallback_stages"]) == 1
    assert any(
        "legacy fallback-only stage event" in note
        for note in payload["telemetry_notes"]
    )


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_stage_report_keeps_explicit_stage_failure_reason_as_failure(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-events-explicit-failure.json"
    report_path = tmp_path / "stage-report-explicit-failure.json"
    _write_json(audit_path, _audit_without_stage_totals(project_id="p-events-explicit-failure"))

    result = _run_operator_script(
        "operator-stage-report.ps1",
        "-ProjectId",
        "p-events-explicit-failure",
        "-AuditJsonPath",
        str(audit_path),
        "-RequireStageTelemetry",
        "-OutPath",
        str(report_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["telemetry_legacy_fallback_normalizations"] == 0
    assert payload["stage_totals"]["total_failures"] == 1
    assert any(
        stage["stage_name"] == "FinalJudgment" and stage["failure_count"] == 1
        for stage in payload["failing_stages"]
    )


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_operator_status_derives_telemetry_from_events_when_totals_missing(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-status-events-only.json"
    summary_path = tmp_path / "operator-status-summary.json"
    _write_json(audit_path, _audit_without_stage_totals(project_id="p-status-events-derived"))

    result = _run_operator_script(
        "operator-status.ps1",
        "-ProjectId",
        "p-status-events-derived",
        "-AuditJsonPath",
        str(audit_path),
        "-SummaryOutPath",
        str(summary_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["project_id"] == "p-status-events-derived"
    assert payload["telemetry_present"] is True
    assert payload["telemetry_source"] == "events_derived"
    assert payload["telemetry_legacy_fallback_normalizations"] == 0
    assert payload["stage_totals"]["total_stage_executions"] == 3
    assert payload["stage_totals"]["total_llm_transport_fallbacks"] == 1
    assert "telemetry   : events_derived" in result.stdout
    assert "summary_out :" in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_operator_status_reports_legacy_fallback_normalization(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-status-legacy.json"
    summary_path = tmp_path / "operator-status-legacy-summary.json"
    _write_json(audit_path, _audit_with_legacy_fallback_only_events(project_id="p-status-legacy"))

    result = _run_operator_script(
        "operator-status.ps1",
        "-ProjectId",
        "p-status-legacy",
        "-AuditJsonPath",
        str(audit_path),
        "-SummaryOutPath",
        str(summary_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["telemetry_present"] is True
    assert payload["telemetry_source"] == "events_derived"
    assert payload["telemetry_legacy_fallback_normalizations"] == 1
    assert payload["stage_totals"]["total_successes"] == 1
    assert payload["stage_totals"]["total_failures"] == 0
    assert "legacy fix  : 1" in result.stdout
    assert any(
        "legacy fallback-only stage event" in note
        for note in payload["telemetry_notes"]
    )


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_operator_status_accepts_cycle_bundle_manifest(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-status-bundle.json"
    manifest_path = tmp_path / "bundle-manifest.json"
    summary_path = tmp_path / "operator-status-bundle-summary.json"
    _write_json(audit_path, _audit_without_stage_totals(project_id="p-status-bundle"))
    _write_cycle_manifest(
        manifest_path,
        project_id="p-status-bundle",
        audit_path=audit_path,
    )

    result = _run_operator_script(
        "operator-status.ps1",
        "-BundleManifestPath",
        str(manifest_path),
        "-SummaryOutPath",
        str(summary_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["project_id"] == "p-status-bundle"
    assert payload["telemetry_source"] == "events_derived"
    assert "telemetry   : events_derived" in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_operator_stage_report_accepts_cycle_bundle_manifest(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-stage-report-bundle.json"
    manifest_path = tmp_path / "bundle-manifest.json"
    report_path = tmp_path / "stage-report-bundle.json"
    _write_json(audit_path, _audit_without_stage_totals(project_id="p-stage-report-bundle"))
    _write_cycle_manifest(
        manifest_path,
        project_id="p-stage-report-bundle",
        audit_path=audit_path,
    )

    result = _run_operator_script(
        "operator-stage-report.ps1",
        "-BundleManifestPath",
        str(manifest_path),
        "-RequireStageTelemetry",
        "-OutPath",
        str(report_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["project_id"] == "p-stage-report-bundle"
    assert payload["telemetry_source"] == "events_derived"
    assert payload["stage_totals"]["total_stage_executions"] == 3


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_operator_audit_assert_accepts_cycle_bundle_manifest(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-assert-bundle.json"
    manifest_path = tmp_path / "bundle-manifest.json"
    assert_path = tmp_path / "audit-assert-bundle-report.json"
    _write_json(audit_path, _audit_without_stage_totals(project_id="p-audit-assert-bundle"))
    _write_cycle_manifest(
        manifest_path,
        project_id="p-audit-assert-bundle",
        audit_path=audit_path,
    )

    result = _run_operator_script(
        "operator-audit-assert.ps1",
        "-BundleManifestPath",
        str(manifest_path),
        "-ExpectedStatus",
        "completed",
        "-RequireStageTelemetry",
        "-MaxLlmTransportFallbacks",
        "1",
        "-OutPath",
        str(assert_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(assert_path.read_text(encoding="utf-8"))
    assert payload["project_id"] == "p-audit-assert-bundle"
    assert payload["telemetry_source"] == "events_derived"
    assert payload["passed"] is True


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_operator_audit_accepts_cycle_bundle_manifest(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-bundle.json"
    manifest_path = tmp_path / "bundle-manifest.json"
    out_path = tmp_path / "audit-bundle-out.json"
    _write_json(audit_path, _audit_without_stage_totals(project_id="p-audit-bundle"))
    _write_cycle_manifest(
        manifest_path,
        project_id="p-audit-bundle",
        audit_path=audit_path,
    )

    result = _run_operator_script(
        "operator-audit.ps1",
        "-BundleManifestPath",
        str(manifest_path),
        "-OutPath",
        str(out_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["project_id"] == "p-audit-bundle"
    assert "PROJECT AUDIT" in result.stdout
    assert "source: events_derived" in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_stage_report_exposes_upstream_rejection_diagnostics_from_events(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit-upstream-rejection.json"
    report_path = tmp_path / "stage-report-upstream-rejection.json"
    _write_json(audit_path, _audit_with_upstream_rejection_events())

    result = _run_operator_script(
        "operator-stage-report.ps1",
        "-ProjectId",
        "p-events-upstream-rejection",
        "-AuditJsonPath",
        str(audit_path),
        "-RequireStageTelemetry",
        "-OutPath",
        str(report_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    stage = payload["stages"][0]
    assert stage["failure_reasons"] == ["upstream_rejection:anthropic:credit_balance_too_low"]
    assert stage["llm_error_kinds"] == ["upstream_rejection"]
    assert stage["llm_response_modes"] == ["plain_text_upstream_rejection"]
    assert stage["llm_content_kinds"] == ["upstream_rejection"]
    assert stage["llm_backend_overrides"] == ["openai-codex/gpt-5.2"]
    assert stage["llm_upstream_providers"] == ["anthropic"]
    assert stage["llm_upstream_rejection_reasons"] == ["credit_balance_too_low"]
    assert stage["llm_backend_override_mismatches"] == ["openai-codex/gpt-5.2->anthropic"]
    assert "backend_overrides=openai-codex/gpt-5.2" in result.stdout
    assert "upstream_providers=anthropic" in result.stdout
    assert "upstream_rejections=credit_balance_too_low" in result.stdout
    assert "backend_override_mismatches=openai-codex/gpt-5.2->anthropic" in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator telemetry derivation script tests.",
)
def test_handoff_envelope_uses_status_summary_artifact_when_cycle_summary_is_thin(
    tmp_path: Path,
) -> None:
    status_summary_path = tmp_path / "status-summary.json"
    cycle_summary_path = tmp_path / "cycle-summary.json"
    manifest_path = tmp_path / "bundle-manifest.json"
    envelope_path = tmp_path / "handoff-envelope.json"
    envelope_markdown_path = tmp_path / "handoff-envelope.md"

    _write_json(
        status_summary_path,
        {
            "project_id": "p-handoff-status-derived",
            "status": "completed",
            "telemetry_present": True,
            "telemetry_source": "summary_derived",
            "telemetry_notes": ["status-summary replay"],
            "telemetry_legacy_fallback_normalizations": 1,
            "stage_totals": {
                "total_stage_executions": 5,
                "total_successes": 4,
                "total_failures": 1,
                "total_fallbacks": 1,
                "total_llm_transport_fallbacks": 1,
                "departments_covered": ["build", "review"],
            },
            "approval_statuses": [
                {"action": "external_api_send", "status": "approved"}
            ],
            "events": 7,
        },
    )
    _write_json(
        cycle_summary_path,
        {
            "mode": "approval",
            "project_id": "p-handoff-status-derived",
            "final_status": "completed",
            "audit_assert_passed": True,
            "files": {
                "status_summary": str(status_summary_path),
            },
        },
    )
    _write_json(
        manifest_path,
        {
            "bundle_type": "cycle",
            "artifacts": {
                "summary": {
                    "path": str(cycle_summary_path),
                    "relative_path": "cycle-summary.json",
                }
            },
            "replay_defaults": {"summary": "summary"},
        },
    )

    result = _run_operator_script(
        "operator-handoff-envelope.ps1",
        "-BundleManifestPath",
        str(manifest_path),
        "-OutPath",
        str(envelope_path),
        "-MarkdownOutPath",
        str(envelope_markdown_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(envelope_path.read_text(encoding="utf-8"))
    assert payload["source_type"] == "cycle"
    assert payload["all_completed"] is True
    assert payload["all_audit_assertions_passed"] is True
    assert payload["total_stage_runs"] == 5
    assert payload["total_stage_failures"] == 1
    assert payload["total_stage_fallbacks"] == 1
    assert payload["total_llm_transport_fallbacks"] == 1
    assert payload["total_stage_legacy_fallback_normalizations"] == 1
    cycles = payload["cycles"]
    if isinstance(cycles, dict):
        cycles = [cycles]
    cycle = cycles[0]
    assert cycle["status_summary_path"] == str(status_summary_path)
    assert cycle["stage_runs"] == 5
    assert cycle["stage_failures"] == 1
    assert cycle["stage_fallbacks"] == 1
    assert cycle["stage_llm_transport_fallbacks"] == 1
    assert cycle["stage_telemetry_source"] == "summary_derived"
    assert cycle["stage_telemetry_present"] is True
    assert cycle["departments_covered"] == ["build", "review"]
    assert cycle["approvals"][0]["status"] == "approved"
    assert envelope_markdown_path.exists()
