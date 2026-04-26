import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


def _run_audit_assert_raw(*args: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL_EXE is not None
    command = [
        POWERSHELL_EXE,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / "operator-audit-assert.ps1"),
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


def _audit_payload(
    *,
    project_id: str = "p-audit-allowlist",
    status: str = "completed",
    provider: str = "openclaw",
    model: str = "openclaw/codex-orchestrator@openai-codex/gpt-5.2",
    mismatches: list[str] | None = None,
) -> dict:
    mismatch_values = mismatches or []
    return {
        "project_id": project_id,
        "status": status,
        "history": [],
        "events": [],
        "approvals": [],
        "reviews": [],
        "checkpoints": [],
        "department_stage_summary": [
            {
                "department": "research",
                "stage_name": "ScopeFraming",
                "sequence": 1,
                "parent_stage_name": "",
                "execution_count": 1,
                "success_count": 1,
                "failure_count": 0,
                "fallback_count": 0,
                "llm_transport_fallback_count": 0,
                "failure_reasons": [],
                "effective_providers": [provider],
                "effective_models": [model],
                "llm_endpoints": ["chat/completions"],
                "llm_http_statuses": [200],
                "llm_error_kinds": [],
                "llm_response_modes": ["json_text"],
                "llm_content_kinds": ["json_text"],
                "llm_backend_overrides": ["openai-codex/gpt-5.2"],
                "llm_upstream_providers": [],
                "llm_upstream_rejection_reasons": [],
                "llm_backend_override_mismatches": mismatch_values,
            }
        ],
        "department_stage_totals": {
            "total_stage_executions": 1,
            "total_successes": 1,
            "total_failures": 0,
            "total_fallbacks": 0,
            "total_llm_transport_fallbacks": 0,
            "departments_covered": ["research"],
            "llm_endpoints_observed": ["chat/completions"],
            "has_failures": False,
            "has_fallbacks": False,
        },
    }


def _auth_events(
    *,
    operator_identity: str = "operator@example.com",
    approver_identity: str = "approver@example.com",
    include_operator: bool = True,
    include_approver: bool = True,
) -> list[dict]:
    events: list[dict] = []

    def _extend_role(role: str, actor: str, actor_type: str) -> None:
        events.extend(
            [
                {
                    "event_type": "authentication_succeeded",
                    "actor": actor,
                    "actor_role": role,
                    "actor_type": actor_type,
                    "timestamp": "2026-04-12T00:00:00Z",
                    "reason": "",
                    "metadata": {"auth_source": "token", "auth_mode": "bearer"},
                },
                {
                    "event_type": "actor_resolved",
                    "actor": actor,
                    "actor_role": role,
                    "actor_type": actor_type,
                    "timestamp": "2026-04-12T00:00:01Z",
                    "reason": "",
                    "metadata": {"auth_source": "token", "auth_mode": "bearer"},
                },
                {
                    "event_type": "authorization_granted",
                    "actor": actor,
                    "actor_role": role,
                    "actor_type": actor_type,
                    "timestamp": "2026-04-12T00:00:02Z",
                    "reason": "",
                    "metadata": {"auth_source": "token", "auth_mode": "bearer"},
                },
            ]
        )

    if include_operator:
        _extend_role("operator", operator_identity, "operator")
    if include_approver:
        _extend_role("approver", approver_identity, "approver")
    return events


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator audit assert script tests.",
)
def test_operator_audit_assert_allowlist_passes_when_observed_values_are_allowed(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.json"
    out_path = tmp_path / "audit-assert.json"
    _write_json(audit_path, _audit_payload())

    result = _run_audit_assert_raw(
        "-ProjectId",
        "p-audit-allowlist",
        "-AuditJsonPath",
        str(audit_path),
        "-ExpectedStatus",
        "completed",
        "-EnforceModelAllowlist",
        "-AllowedEffectiveProviders",
        "openclaw",
        "-AllowedEffectiveModels",
        "openclaw/codex-orchestrator@openai-codex/gpt-5.2",
        "-AllowedOpenClawAgents",
        "codex-orchestrator",
        "-FailOnBackendOverrideMismatch",
        "-OutPath",
        str(out_path),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["enforce_model_allowlist"] is True
    assert payload["observed_effective_models"] == [
        "openclaw/codex-orchestrator@openai-codex/gpt-5.2"
    ]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator audit assert script tests.",
)
def test_operator_audit_assert_allowlist_fails_when_effective_model_not_allowed(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit-model-mismatch.json"
    out_path = tmp_path / "audit-assert-model-mismatch.json"
    _write_json(audit_path, _audit_payload())

    result = _run_audit_assert_raw(
        "-ProjectId",
        "p-audit-allowlist",
        "-AuditJsonPath",
        str(audit_path),
        "-ExpectedStatus",
        "completed",
        "-EnforceModelAllowlist",
        "-AllowedEffectiveProviders",
        "openclaw",
        "-AllowedEffectiveModels",
        "openclaw/codex-orchestrator@openai-codex/gpt-5.4",
        "-AllowedOpenClawAgents",
        "codex-orchestrator",
        "-OutPath",
        str(out_path),
    )
    assert result.returncode != 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert any("effective model not allowlisted" in item for item in payload["errors"])


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator audit assert script tests.",
)
def test_operator_audit_assert_policy_mode_strict_denies_backend_override_mismatch(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit-backend-mismatch.json"
    out_path = tmp_path / "audit-assert-backend-mismatch.json"
    policy_path = tmp_path / "model-routing-policy.json"
    _write_json(
        audit_path,
        _audit_payload(mismatches=["openai-codex/gpt-5.2->anthropic"]),
    )
    _write_json(
        policy_path,
        {
            "live_run_policy": {
                "modes": {
                    "strict": {
                        "enforce_allowlist": True,
                        "allowed_effective_providers": ["openclaw"],
                        "allowed_effective_models": [
                            "openclaw/codex-orchestrator@openai-codex/gpt-5.2"
                        ],
                        "allowed_openclaw_agents": ["codex-orchestrator"],
                        "deny_on_backend_override_mismatch": True,
                    }
                }
            }
        },
    )

    result = _run_audit_assert_raw(
        "-ProjectId",
        "p-audit-allowlist",
        "-AuditJsonPath",
        str(audit_path),
        "-ExpectedStatus",
        "completed",
        "-EnforceModelAllowlist",
        "-FailOnBackendOverrideMismatch",
        "-PolicyMode",
        "strict",
        "-ModelRoutingPolicyPath",
        str(policy_path),
        "-OutPath",
        str(out_path),
    )
    assert result.returncode != 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["enforce_model_allowlist"] is True
    assert payload["fail_on_backend_override_mismatch"] is True
    assert "openai-codex/gpt-5.2->anthropic" in payload["observed_backend_override_mismatches"]
    assert any("backend override mismatch observed" in item for item in payload["errors"])


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator audit assert script tests.",
)
def test_operator_audit_assert_require_auth_evidence_passes_with_role_evidence(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit-auth-pass.json"
    out_path = tmp_path / "audit-auth-pass-report.json"
    payload = _audit_payload(project_id="p-audit-auth-pass")
    payload["events"] = _auth_events()
    _write_json(audit_path, payload)

    result = _run_audit_assert_raw(
        "-ProjectId",
        "p-audit-auth-pass",
        "-AuditJsonPath",
        str(audit_path),
        "-ExpectedStatus",
        "completed",
        "-RequireAuthEvidence",
        "-ExpectedAuthRoles",
        "operator,approver",
        "-AuthPolicyMode",
        "strict",
        "-OutPath",
        str(out_path),
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["require_auth_evidence"] is True
    assert report["expected_auth_roles"] == ["operator", "approver"]
    assert report["auth_policy_mode"] == "strict"
    assert report["auth_evidence_present"] is True
    assert report["auth_evidence"]["roles"]["operator"]["evidence_present"] is True
    assert report["auth_evidence"]["roles"]["approver"]["evidence_present"] is True


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator audit assert script tests.",
)
def test_operator_audit_assert_require_auth_evidence_fails_when_role_missing(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit-auth-missing-role.json"
    out_path = tmp_path / "audit-auth-missing-role-report.json"
    payload = _audit_payload(project_id="p-audit-auth-missing")
    payload["events"] = _auth_events(include_operator=False, include_approver=True)
    _write_json(audit_path, payload)

    result = _run_audit_assert_raw(
        "-ProjectId",
        "p-audit-auth-missing",
        "-AuditJsonPath",
        str(audit_path),
        "-ExpectedStatus",
        "completed",
        "-RequireAuthEvidence",
        "-ExpectedAuthRoles",
        "operator,approver",
        "-AuthPolicyMode",
        "strict",
        "-OutPath",
        str(out_path),
    )
    assert result.returncode != 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert any(
        ("required auth evidence missing" in item) or ("auth role evidence missing" in item)
        for item in report["errors"]
    )


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator audit assert script tests.",
)
def test_operator_audit_assert_strict_auth_boundary_denies_identity_overlap(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit-auth-overlap.json"
    out_path = tmp_path / "audit-auth-overlap-report.json"
    payload = _audit_payload(project_id="p-audit-auth-overlap")
    payload["events"] = _auth_events(
        operator_identity="shared@example.com",
        approver_identity="shared@example.com",
    )
    _write_json(audit_path, payload)

    result = _run_audit_assert_raw(
        "-ProjectId",
        "p-audit-auth-overlap",
        "-AuditJsonPath",
        str(audit_path),
        "-ExpectedStatus",
        "completed",
        "-RequireAuthEvidence",
        "-ExpectedAuthRoles",
        "operator,approver",
        "-AuthPolicyMode",
        "strict",
        "-OutPath",
        str(out_path),
    )
    assert result.returncode != 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert any("auth boundary violation" in item for item in report["errors"])


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator audit assert script tests.",
)
def test_operator_audit_assert_breakglass_requires_reason(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit-breakglass.json"
    out_path = tmp_path / "audit-breakglass-report.json"
    payload = _audit_payload(project_id="p-audit-breakglass")
    payload["events"] = _auth_events()
    _write_json(audit_path, payload)

    result = _run_audit_assert_raw(
        "-ProjectId",
        "p-audit-breakglass",
        "-AuditJsonPath",
        str(audit_path),
        "-ExpectedStatus",
        "completed",
        "-Breakglass",
        "-OutPath",
        str(out_path),
    )
    assert result.returncode != 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert any("breakglass reason is required" in item for item in report["errors"])
