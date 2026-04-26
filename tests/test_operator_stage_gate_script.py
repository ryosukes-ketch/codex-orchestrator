import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


def _run_stage_gate_raw(*args: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL_EXE is not None
    command = [
        POWERSHELL_EXE,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / "operator-stage-gate.ps1"),
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


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_accepts_cycle_summary(tmp_path: Path) -> None:
    summary_path = tmp_path / "cycle-summary.json"
    _write_json(
        summary_path,
        {
            "mode": "approval",
            "project_id": "p-cycle-1",
            "final_status": "completed",
            "audit_assert_passed": True,
            "stage_runs": 5,
            "stage_failures": 2,
            "stage_fallbacks": 2,
            "stage_llm_transport_fallbacks": 1,
            "stage_legacy_fallback_normalizations": 1,
        },
    )

    out_path = tmp_path / "stage-gate-cycle.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(summary_path),
        "-OutPath",
        str(out_path),
        "-MaxStageFailures",
        "2",
        "-MaxStageFallbacks",
        "2",
        "-MaxLlmTransportFallbacks",
        "1",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["summary_type"] == "cycle"
    assert payload["cycle_count"] == 1
    assert payload["totals"]["stage_runs"] == 5
    assert payload["totals"]["llm_transport_fallbacks"] == 1
    assert payload["totals"]["legacy_fallback_normalizations"] == 1
    assert "stage_telemetry_sources" in payload["totals"]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_accepts_cycle_bundle_manifest(tmp_path: Path) -> None:
    summary_path = tmp_path / "cycle-summary-manifest.json"
    manifest_path = tmp_path / "bundle-manifest.json"
    _write_json(
        summary_path,
        {
            "mode": "approval",
            "project_id": "p-cycle-manifest",
            "final_status": "completed",
            "audit_assert_passed": True,
            "stage_runs": 4,
            "stage_failures": 1,
            "stage_fallbacks": 1,
            "stage_llm_transport_fallbacks": 0,
            "stage_legacy_fallback_normalizations": 1,
        },
    )
    _write_json(
        manifest_path,
        {
            "bundle_type": "cycle",
            "artifacts": {
                "summary": {
                    "path": str(summary_path),
                    "relative_path": "cycle-summary-manifest.json",
                }
            },
            "replay_defaults": {"summary": "summary"},
        },
    )

    out_path = tmp_path / "stage-gate-cycle-manifest.json"
    result = _run_stage_gate_raw(
        "-BundleManifestPath",
        str(manifest_path),
        "-OutPath",
        str(out_path),
        "-MaxStageFailures",
        "1",
        "-MaxStageFallbacks",
        "1",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["summary_type"] == "cycle"
    assert payload["cycle_count"] == 1


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_detects_threshold_violation(tmp_path: Path) -> None:
    summary_path = tmp_path / "cycle-summary-fail.json"
    _write_json(
        summary_path,
        {
            "mode": "approval",
            "project_id": "p-cycle-2",
            "final_status": "completed",
            "audit_assert_passed": True,
            "stage_runs": 6,
            "stage_failures": 1,
            "stage_fallbacks": 3,
            "stage_llm_transport_fallbacks": 2,
            "stage_legacy_fallback_normalizations": 2,
        },
    )

    out_path = tmp_path / "stage-gate-fail.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(summary_path),
        "-OutPath",
        str(out_path),
        "-MaxStageFallbacks",
        "0",
    )
    assert result.returncode != 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["violation_count"] >= 1
    assert any("stage fallbacks exceeded limit" in v for v in payload["violations"])


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_detects_llm_transport_fallback_violation(tmp_path: Path) -> None:
    summary_path = tmp_path / "cycle-summary-llm-fallback.json"
    _write_json(
        summary_path,
        {
            "mode": "approval",
            "project_id": "p-cycle-llm-fb",
            "final_status": "completed",
            "audit_assert_passed": True,
            "stage_runs": 3,
            "stage_failures": 0,
            "stage_fallbacks": 0,
            "stage_llm_transport_fallbacks": 1,
            "stage_legacy_fallback_normalizations": 0,
        },
    )

    out_path = tmp_path / "stage-gate-llm-fallback.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(summary_path),
        "-OutPath",
        str(out_path),
        "-MaxLlmTransportFallbacks",
        "0",
    )
    assert result.returncode != 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert any("llm transport fallbacks exceeded limit" in v for v in payload["violations"])


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_resolves_suite_with_cycle_summary_paths(tmp_path: Path) -> None:
    cycle_approval = tmp_path / "approval" / "summary.json"
    cycle_reject = tmp_path / "reject-replan" / "summary.json"
    _write_json(
        cycle_approval,
        {
            "mode": "approval",
            "project_id": "p-suite-1",
            "final_status": "completed",
            "audit_assert_passed": True,
            "stage_runs": 4,
            "stage_failures": 1,
            "stage_fallbacks": 1,
            "stage_legacy_fallback_normalizations": 1,
        },
    )
    _write_json(
        cycle_reject,
        {
            "mode": "reject-replan",
            "project_id": "p-suite-2",
            "final_status": "completed",
            "audit_assert_passed": True,
            "stage_runs": 7,
            "stage_failures": 2,
            "stage_fallbacks": 2,
            "stage_legacy_fallback_normalizations": 2,
        },
    )

    suite_summary = tmp_path / "suite-summary.json"
    _write_json(
        suite_summary,
        {
            "cycle_count": 2,
            "cycles": [
                {"mode": "approval", "summary_path": str(cycle_approval)},
                {"mode": "reject-replan", "summary_path": str(cycle_reject)},
            ],
        },
    )

    out_path = tmp_path / "stage-gate-suite.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(suite_summary),
        "-OutPath",
        str(out_path),
        "-MaxStageFailures",
        "3",
        "-MaxStageFallbacks",
        "3",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["summary_type"] == "suite"
    assert payload["cycle_count"] == 2
    assert payload["totals"]["stage_runs"] == 11
    assert payload["totals"]["stage_failures"] == 3
    assert payload["totals"]["stage_fallbacks"] == 3
    assert payload["totals"]["legacy_fallback_normalizations"] == 3


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_accepts_suite_bundle_manifest(tmp_path: Path) -> None:
    suite_summary = tmp_path / "suite-summary-manifest.json"
    manifest_path = tmp_path / "suite-bundle-manifest.json"
    _write_json(
        suite_summary,
        {
            "cycle_count": 1,
            "all_completed": True,
            "all_audit_assertions_passed": True,
            "cycles": [
                {
                    "mode": "approval",
                    "project_id": "p-suite-manifest",
                    "final_status": "completed",
                    "audit_assert_passed": True,
                    "stage_runs": 2,
                    "stage_failures": 0,
                    "stage_fallbacks": 0,
                    "stage_llm_transport_fallbacks": 0,
                }
            ],
        },
    )
    _write_json(
        manifest_path,
        {
            "bundle_type": "suite",
            "artifacts": {
                "suite_summary": {
                    "path": str(suite_summary),
                    "relative_path": "suite-summary-manifest.json",
                }
            },
            "replay_defaults": {"suite_summary": "suite_summary"},
        },
    )

    out_path = tmp_path / "stage-gate-suite-manifest.json"
    result = _run_stage_gate_raw(
        "-BundleManifestPath",
        str(manifest_path),
        "-OutPath",
        str(out_path),
        "-MaxStageFailures",
        "0",
        "-MaxStageFallbacks",
        "0",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["summary_type"] == "suite"
    assert payload["cycle_count"] == 1


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_accepts_handoff_envelope_summary(tmp_path: Path) -> None:
    handoff_path = tmp_path / "suite-handoff.json"
    _write_json(
        handoff_path,
        {
            "source_type": "suite",
            "cycles": [
                {
                    "mode": "approval",
                    "project_id": "p-h1",
                    "final_status": "completed",
                    "audit_assert_passed": True,
                    "stage_runs": 3,
                    "stage_failures": 1,
                    "stage_fallbacks": 1,
                    "stage_legacy_fallback_normalizations": 1,
                },
                {
                    "mode": "reject-replan",
                    "project_id": "p-h2",
                    "final_status": "completed",
                    "audit_assert_passed": True,
                    "stage_runs": 5,
                    "stage_failures": 1,
                    "stage_fallbacks": 1,
                    "stage_legacy_fallback_normalizations": 2,
                },
            ],
            "total_stage_runs": 8,
            "total_stage_failures": 2,
            "total_stage_fallbacks": 2,
            "total_stage_legacy_fallback_normalizations": 3,
        },
    )

    out_path = tmp_path / "stage-gate-handoff.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(handoff_path),
        "-OutPath",
        str(out_path),
        "-MaxStageFailures",
        "2",
        "-MaxStageFallbacks",
        "2",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["summary_type"] == "handoff"
    assert payload["cycle_count"] == 2
    assert payload["totals"]["legacy_fallback_normalizations"] == 3


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_resolves_suite_with_status_summary_paths_only(tmp_path: Path) -> None:
    approval_status_summary = tmp_path / "approval" / "status-summary.json"
    reject_status_summary = tmp_path / "reject-replan" / "status-summary.json"
    _write_json(
        approval_status_summary,
        {
            "project_id": "p-suite-status-1",
            "status": "completed",
            "telemetry_present": True,
            "telemetry_source": "summary_derived",
            "telemetry_legacy_fallback_normalizations": 1,
            "stage_totals": {
                "total_stage_executions": 4,
                "total_failures": 1,
                "total_fallbacks": 1,
                "total_llm_transport_fallbacks": 0,
            },
        },
    )
    _write_json(
        reject_status_summary,
        {
            "project_id": "p-suite-status-2",
            "status": "completed",
            "telemetry_present": True,
            "telemetry_source": "events_derived",
            "telemetry_legacy_fallback_normalizations": 2,
            "stage_totals": {
                "total_stage_executions": 6,
                "total_failures": 2,
                "total_fallbacks": 2,
                "total_llm_transport_fallbacks": 1,
            },
        },
    )

    suite_summary = tmp_path / "suite-summary-status-only.json"
    _write_json(
        suite_summary,
        {
            "cycle_count": 2,
            "cycles": [
                {
                    "mode": "approval",
                    "project_id": "p-suite-status-1",
                    "final_status": "completed",
                    "audit_assert_passed": True,
                    "status_summary_path": str(approval_status_summary),
                },
                {
                    "mode": "reject-replan",
                    "project_id": "p-suite-status-2",
                    "final_status": "completed",
                    "audit_assert_passed": True,
                    "status_summary_path": str(reject_status_summary),
                },
            ],
        },
    )

    out_path = tmp_path / "stage-gate-suite-status-only.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(suite_summary),
        "-OutPath",
        str(out_path),
        "-RequireStageTelemetry:$true",
        "-MaxStageFailures",
        "3",
        "-MaxStageFallbacks",
        "3",
        "-MaxLlmTransportFallbacks",
        "1",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["summary_type"] == "suite"
    assert payload["totals"]["stage_runs"] == 10
    assert payload["totals"]["stage_failures"] == 3
    assert payload["totals"]["stage_fallbacks"] == 3
    assert payload["totals"]["llm_transport_fallbacks"] == 1
    assert payload["totals"]["legacy_fallback_normalizations"] == 3
    assert {cycle["status_summary_path"] for cycle in payload["cycles"]} == {
        str(approval_status_summary),
        str(reject_status_summary),
    }


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_resolves_handoff_cycles_with_status_summary_paths_only(tmp_path: Path) -> None:
    approval_status_summary = tmp_path / "handoff-approval-status-summary.json"
    reject_status_summary = tmp_path / "handoff-reject-status-summary.json"
    _write_json(
        approval_status_summary,
        {
            "project_id": "p-handoff-status-1",
            "status": "completed",
            "telemetry_present": True,
            "telemetry_source": "summary_derived",
            "telemetry_legacy_fallback_normalizations": 0,
            "stage_totals": {
                "total_stage_executions": 3,
                "total_failures": 1,
                "total_fallbacks": 1,
                "total_llm_transport_fallbacks": 0,
            },
        },
    )
    _write_json(
        reject_status_summary,
        {
            "project_id": "p-handoff-status-2",
            "status": "completed",
            "telemetry_present": True,
            "telemetry_source": "summary_derived",
            "telemetry_legacy_fallback_normalizations": 1,
            "stage_totals": {
                "total_stage_executions": 5,
                "total_failures": 1,
                "total_fallbacks": 1,
                "total_llm_transport_fallbacks": 1,
            },
        },
    )

    handoff_path = tmp_path / "suite-handoff-status-only.json"
    _write_json(
        handoff_path,
        {
            "source_type": "suite",
            "cycles": [
                {
                    "mode": "approval",
                    "project_id": "p-handoff-status-1",
                    "final_status": "completed",
                    "audit_assert_passed": True,
                    "status_summary_path": str(approval_status_summary),
                },
                {
                    "mode": "reject-replan",
                    "project_id": "p-handoff-status-2",
                    "final_status": "completed",
                    "audit_assert_passed": True,
                    "status_summary_path": str(reject_status_summary),
                },
            ],
        },
    )

    out_path = tmp_path / "stage-gate-handoff-status-only.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(handoff_path),
        "-OutPath",
        str(out_path),
        "-RequireStageTelemetry:$true",
        "-MaxStageFailures",
        "2",
        "-MaxStageFallbacks",
        "2",
        "-MaxLlmTransportFallbacks",
        "1",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["summary_type"] == "handoff"
    assert payload["totals"]["stage_runs"] == 8
    assert payload["totals"]["stage_failures"] == 2
    assert payload["totals"]["stage_fallbacks"] == 2
    assert payload["totals"]["llm_transport_fallbacks"] == 1
    assert payload["totals"]["legacy_fallback_normalizations"] == 1


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_policy_assertions_pass_with_allowlist_flags(tmp_path: Path) -> None:
    audit_assert_path = tmp_path / "audit-assert-pass.json"
    summary_path = tmp_path / "cycle-summary-policy-pass.json"
    _write_json(
        audit_assert_path,
        {
            "passed": True,
            "policy_mode": "strict",
            "enforce_model_allowlist": True,
            "fail_on_backend_override_mismatch": True,
            "errors": [],
        },
    )
    _write_json(
        summary_path,
        {
            "mode": "approval",
            "project_id": "p-policy-pass",
            "final_status": "completed",
            "audit_assert_passed": True,
            "stage_runs": 2,
            "stage_failures": 0,
            "stage_fallbacks": 0,
            "stage_llm_transport_fallbacks": 0,
            "files": {"audit_assert": str(audit_assert_path)},
        },
    )

    out_path = tmp_path / "stage-gate-policy-pass.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(summary_path),
        "-OutPath",
        str(out_path),
        "-RequirePolicyAssertions:$true",
        "-PolicyMode",
        "strict",
        "-EnforceModelAllowlist",
        "-FailOnBackendOverrideMismatch",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["require_policy_assertions"] is True
    assert payload["enforce_model_allowlist"] is True
    assert payload["fail_on_backend_override_mismatch"] is True
    assert payload["deny_reason_count"] == 0


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_policy_assertions_fail_with_deny_reason_capture(tmp_path: Path) -> None:
    audit_assert_path = tmp_path / "audit-assert-fail.json"
    summary_path = tmp_path / "cycle-summary-policy-fail.json"
    _write_json(
        audit_assert_path,
        {
            "passed": False,
            "policy_mode": "strict",
            "enforce_model_allowlist": True,
            "fail_on_backend_override_mismatch": True,
            "errors": [
                "effective model not allowlisted: anthropic/claude-sonnet-4-6",
                "backend override mismatch observed: openai-codex/gpt-5.2->anthropic",
            ],
        },
    )
    _write_json(
        summary_path,
        {
            "mode": "approval",
            "project_id": "p-policy-fail",
            "final_status": "completed",
            "audit_assert_passed": False,
            "stage_runs": 2,
            "stage_failures": 0,
            "stage_fallbacks": 0,
            "stage_llm_transport_fallbacks": 0,
            "files": {"audit_assert": str(audit_assert_path)},
        },
    )

    out_path = tmp_path / "stage-gate-policy-fail.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(summary_path),
        "-OutPath",
        str(out_path),
        "-RequirePolicyAssertions:$true",
        "-PolicyMode",
        "strict",
        "-EnforceModelAllowlist",
        "-FailOnBackendOverrideMismatch",
    )
    assert result.returncode != 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["deny_reason_count"] >= 2
    assert any("effective model not allowlisted" in item for item in payload["deny_reasons"])
    assert any("backend override mismatch observed" in item for item in payload["deny_reasons"])


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_requires_auth_evidence_roles_when_configured(tmp_path: Path) -> None:
    audit_assert_path = tmp_path / "audit-assert-auth-pass.json"
    summary_path = tmp_path / "cycle-summary-auth-pass.json"
    _write_json(
        audit_assert_path,
        {
            "passed": True,
            "auth_evidence_present": True,
            "auth_policy_mode": "strict",
            "expected_auth_roles": ["operator", "approver"],
            "auth_evidence": {
                "roles": {
                    "operator": {
                        "evidence_present": True,
                        "auth_sources": ["token"],
                        "auth_modes": ["bearer"],
                    },
                    "approver": {
                        "evidence_present": True,
                        "auth_sources": ["token"],
                        "auth_modes": ["bearer"],
                    },
                }
            },
            "errors": [],
        },
    )
    _write_json(
        summary_path,
        {
            "mode": "approval",
            "project_id": "p-auth-pass",
            "final_status": "completed",
            "audit_assert_passed": True,
            "stage_runs": 1,
            "stage_failures": 0,
            "stage_fallbacks": 0,
            "stage_llm_transport_fallbacks": 0,
            "files": {"audit_assert": str(audit_assert_path)},
        },
    )

    out_path = tmp_path / "stage-gate-auth-pass.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(summary_path),
        "-OutPath",
        str(out_path),
        "-RequireAuthEvidence:$true",
        "-ExpectedAuthRoles",
        "operator,approver",
        "-AuthPolicyMode",
        "strict",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["require_auth_evidence"] is True
    assert payload["expected_auth_roles"] == ["operator", "approver"]
    assert payload["auth_policy_mode"] == "strict"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_fails_when_required_auth_evidence_is_missing(tmp_path: Path) -> None:
    audit_assert_path = tmp_path / "audit-assert-auth-fail.json"
    summary_path = tmp_path / "cycle-summary-auth-fail.json"
    _write_json(
        audit_assert_path,
        {
            "passed": True,
            "auth_evidence_present": False,
            "auth_policy_mode": "strict",
            "expected_auth_roles": ["operator", "approver"],
            "auth_evidence": {
                "roles": {
                    "operator": {
                        "evidence_present": False,
                        "auth_sources": [],
                        "auth_modes": [],
                    },
                    "approver": {
                        "evidence_present": True,
                        "auth_sources": ["token"],
                        "auth_modes": ["bearer"],
                    },
                }
            },
            "errors": [],
        },
    )
    _write_json(
        summary_path,
        {
            "mode": "approval",
            "project_id": "p-auth-fail",
            "final_status": "completed",
            "audit_assert_passed": True,
            "stage_runs": 1,
            "stage_failures": 0,
            "stage_fallbacks": 0,
            "stage_llm_transport_fallbacks": 0,
            "files": {"audit_assert": str(audit_assert_path)},
        },
    )

    out_path = tmp_path / "stage-gate-auth-fail.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(summary_path),
        "-OutPath",
        str(out_path),
        "-RequireAuthEvidence:$true",
        "-ExpectedAuthRoles",
        "operator,approver",
        "-AuthPolicyMode",
        "strict",
    )
    assert result.returncode != 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["deny_reason_count"] >= 1
    assert any(
        "auth evidence missing" in item or "auth role evidence missing" in item
        for item in payload["deny_reasons"]
    )


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_breakglass_requires_reason_and_actor_markers(tmp_path: Path) -> None:
    audit_assert_path = tmp_path / "audit-assert-breakglass-pass.json"
    summary_path = tmp_path / "cycle-summary-breakglass-pass.json"
    _write_json(
        audit_assert_path,
        {
            "passed": True,
            "breakglass_used": True,
            "breakglass_reason": "temporary remediation",
            "breakglass_actor": "ops-user",
            "errors": [],
        },
    )
    _write_json(
        summary_path,
        {
            "mode": "approval",
            "project_id": "p-breakglass-pass",
            "final_status": "completed",
            "audit_assert_passed": True,
            "stage_runs": 1,
            "stage_failures": 0,
            "stage_fallbacks": 0,
            "stage_llm_transport_fallbacks": 0,
            "files": {"audit_assert": str(audit_assert_path)},
        },
    )

    out_path = tmp_path / "stage-gate-breakglass-pass.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(summary_path),
        "-OutPath",
        str(out_path),
        "-Breakglass",
        "-BreakglassReason",
        "temporary remediation",
        "-BreakglassActor",
        "ops-user",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["breakglass_used"] is True
    assert payload["breakglass_reason"] == "temporary remediation"
    assert payload["breakglass_actor"] == "ops-user"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for stage gate script tests.",
)
def test_stage_gate_breakglass_fails_when_reason_or_actor_missing(tmp_path: Path) -> None:
    audit_assert_path = tmp_path / "audit-assert-breakglass-fail.json"
    summary_path = tmp_path / "cycle-summary-breakglass-fail.json"
    _write_json(
        audit_assert_path,
        {
            "passed": True,
            "breakglass_used": False,
            "breakglass_reason": "",
            "breakglass_actor": "",
            "errors": [],
        },
    )
    _write_json(
        summary_path,
        {
            "mode": "approval",
            "project_id": "p-breakglass-fail",
            "final_status": "completed",
            "audit_assert_passed": True,
            "stage_runs": 1,
            "stage_failures": 0,
            "stage_fallbacks": 0,
            "stage_llm_transport_fallbacks": 0,
            "files": {"audit_assert": str(audit_assert_path)},
        },
    )

    out_path = tmp_path / "stage-gate-breakglass-fail.json"
    result = _run_stage_gate_raw(
        "-SummaryPath",
        str(summary_path),
        "-OutPath",
        str(out_path),
        "-Breakglass",
    )
    assert result.returncode != 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert any(
        "breakglass evidence missing" in item or "breakglass reason missing" in item
        for item in payload["deny_reasons"]
    )
