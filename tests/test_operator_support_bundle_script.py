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
        timeout=180,
        check=False,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for support bundle script tests.",
)
def test_operator_support_bundle_reports_no_blocking_issues_for_clean_cycle(tmp_path: Path) -> None:
    cycle_dir = tmp_path / "cycle-approval"
    suite_dir = tmp_path / "suite"
    readiness_dir = tmp_path / "readiness"

    cycle_summary = cycle_dir / "summary.json"
    cycle_status = cycle_dir / "status.json"
    cycle_status_summary = cycle_dir / "status-summary.json"
    cycle_audit = cycle_dir / "audit.json"
    cycle_stage_report = cycle_dir / "stage-report.json"
    cycle_audit_assert = cycle_dir / "audit-assert.json"
    cycle_manifest = cycle_dir / "bundle-manifest.json"

    _write_json(cycle_summary, {"project_id": "p-clean", "final_status": "completed", "mode": "approval"})
    _write_json(cycle_status, {"project_id": "p-clean", "status": "completed"})
    _write_json(cycle_status_summary, {"project_id": "p-clean", "status": "completed"})
    _write_json(cycle_audit, {"project_id": "p-clean", "status": "completed"})
    _write_json(
        cycle_stage_report,
        {
            "project_id": "p-clean",
            "telemetry_source": "audit_totals",
            "failing_stages": [],
        },
    )
    _write_json(cycle_audit_assert, {"project_id": "p-clean", "passed": True, "errors": []})
    _write_json(
        cycle_manifest,
        {
            "bundle_type": "cycle",
            "project_id": "p-clean",
            "artifacts": {
                "summary": {"path": str(cycle_summary)},
                "status": {"path": str(cycle_status)},
                "status_summary": {"path": str(cycle_status_summary)},
                "audit": {"path": str(cycle_audit)},
                "stage_report": {"path": str(cycle_stage_report)},
                "audit_assert": {"path": str(cycle_audit_assert)},
            },
        },
    )

    suite_summary = suite_dir / "suite-summary.json"
    suite_stage_gate = suite_dir / "suite-stage-gate.json"
    suite_handoff = suite_dir / "suite-handoff.json"
    suite_manifest = suite_dir / "bundle-manifest.json"
    _write_json(suite_summary, {"cycle_count": 1, "all_completed": True})
    _write_json(suite_stage_gate, {"passed": True, "deny_reasons": [], "violations": []})
    _write_json(suite_handoff, {"source_type": "suite"})
    _write_json(
        suite_manifest,
        {
            "bundle_type": "suite",
            "artifacts": {
                "suite_summary": {"path": str(suite_summary)},
                "stage_gate": {"path": str(suite_stage_gate)},
                "handoff_json": {"path": str(suite_handoff)},
            },
            "cycles": [
                {
                    "mode": "approval",
                    "summary_path": str(cycle_summary),
                    "status_summary_path": str(cycle_status_summary),
                    "bundle_manifest_path": str(cycle_manifest),
                    "project_id": "p-clean",
                    "final_status": "completed",
                }
            ],
        },
    )

    readiness_summary = readiness_dir / "readiness-summary.json"
    readiness_manifest = readiness_dir / "readiness-manifest.json"
    _write_json(readiness_summary, {"result": "ok"})
    _write_json(
        readiness_manifest,
        {
            "bundle_type": "readiness",
            "artifacts": {
                "readiness_summary": {"path": str(readiness_summary)},
                "operator_suite_manifest": {"path": str(suite_manifest)},
                "operator_suite_summary": {"path": str(suite_summary)},
                "operator_suite_stage_gate": {"path": str(suite_stage_gate)},
                "operator_suite_handoff": {"path": str(suite_handoff)},
            },
        },
    )

    output_dir = tmp_path / "support-bundle-clean"
    manifest_path = tmp_path / "support-bundle-clean.manifest.json"
    result = _run_script(
        "operator-support-bundle.ps1",
        "-ReadinessManifestPath",
        str(readiness_manifest),
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(manifest_path),
    )

    assert result.returncode == 0, result.stderr
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["classification_status"] == "no_blocking_issues"
    assert payload["has_blocking_findings"] is False
    assert payload["category_counts"]["runtime"] == 0
    assert payload["category_counts"]["policy"] == 0

    class_payload = json.loads(
        Path(payload["failure_classification_json_path"]).read_text(encoding="utf-8")
    )
    assert class_payload["finding_count"] == 0


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for support bundle script tests.",
)
def test_operator_support_bundle_classifies_policy_and_semantic_failures(tmp_path: Path) -> None:
    cycle_dir = tmp_path / "cycle-reject-replan"
    suite_dir = tmp_path / "suite"
    readiness_dir = tmp_path / "readiness"

    cycle_summary = cycle_dir / "summary.json"
    cycle_status = cycle_dir / "status.json"
    cycle_status_summary = cycle_dir / "status-summary.json"
    cycle_audit = cycle_dir / "audit.json"
    cycle_stage_report = cycle_dir / "stage-report.json"
    cycle_audit_assert = cycle_dir / "audit-assert.json"
    cycle_manifest = cycle_dir / "bundle-manifest.json"

    _write_json(
        cycle_summary,
        {
            "project_id": "p-policy",
            "final_status": "revision_requested",
            "mode": "reject-replan",
            "stage_llm_transport_fallbacks": 1,
        },
    )
    _write_json(cycle_status, {"project_id": "p-policy", "status": "revision_requested"})
    _write_json(cycle_status_summary, {"project_id": "p-policy", "status": "revision_requested"})
    _write_json(cycle_audit, {"project_id": "p-policy", "status": "revision_requested"})
    _write_json(
        cycle_stage_report,
        {
            "project_id": "p-policy",
            "telemetry_source": "events_derived",
            "failing_stages": [
                {
                    "department": "research",
                    "stage_name": "RiskChallenge",
                    "failure_reasons": ["non_json_response"],
                }
            ],
        },
    )
    _write_json(
        cycle_audit_assert,
        {
            "project_id": "p-policy",
            "passed": False,
            "errors": [
                "required auth evidence missing: role=operator",
                "effective provider not allowlisted: mock",
            ],
        },
    )
    _write_json(
        cycle_manifest,
        {
            "bundle_type": "cycle",
            "project_id": "p-policy",
            "artifacts": {
                "summary": {"path": str(cycle_summary)},
                "status": {"path": str(cycle_status)},
                "status_summary": {"path": str(cycle_status_summary)},
                "audit": {"path": str(cycle_audit)},
                "stage_report": {"path": str(cycle_stage_report)},
                "audit_assert": {"path": str(cycle_audit_assert)},
            },
        },
    )

    suite_summary = suite_dir / "suite-summary.json"
    suite_stage_gate = suite_dir / "suite-stage-gate.json"
    suite_handoff = suite_dir / "suite-handoff.json"
    suite_manifest = suite_dir / "bundle-manifest.json"
    _write_json(suite_summary, {"cycle_count": 1, "all_completed": False})
    _write_json(
        suite_stage_gate,
        {
            "passed": False,
            "deny_reasons": ["policy assertion failed: mode=reject-replan project_id=p-policy"],
            "violations": ["cycle not completed: mode=reject-replan project_id=p-policy final_status=revision_requested"],
        },
    )
    _write_json(suite_handoff, {"source_type": "suite"})
    _write_json(
        suite_manifest,
        {
            "bundle_type": "suite",
            "artifacts": {
                "suite_summary": {"path": str(suite_summary)},
                "stage_gate": {"path": str(suite_stage_gate)},
                "handoff_json": {"path": str(suite_handoff)},
            },
            "cycles": [
                {
                    "mode": "reject-replan",
                    "summary_path": str(cycle_summary),
                    "status_summary_path": str(cycle_status_summary),
                    "bundle_manifest_path": str(cycle_manifest),
                    "project_id": "p-policy",
                    "final_status": "revision_requested",
                }
            ],
        },
    )

    openclaw_evidence = readiness_dir / "openclaw-evidence.json"
    readiness_summary = readiness_dir / "readiness-summary.json"
    readiness_manifest = readiness_dir / "readiness-manifest.json"
    _write_json(
        openclaw_evidence,
        {
            "gateway_response_success": True,
            "upstream_rejection_detected": True,
            "upstream_provider": "anthropic",
            "upstream_rejection_reason": "credit_balance_too_low",
            "backend_override_provider_mismatch": True,
            "backend_override_provider": "openai",
            "used_endpoint": "responses",
            "status_code": 200,
        },
    )
    _write_json(readiness_summary, {"result": "failed"})
    _write_json(
        readiness_manifest,
        {
            "bundle_type": "readiness",
            "artifacts": {
                "readiness_summary": {"path": str(readiness_summary)},
                "operator_suite_manifest": {"path": str(suite_manifest)},
                "operator_suite_summary": {"path": str(suite_summary)},
                "operator_suite_stage_gate": {"path": str(suite_stage_gate)},
                "operator_suite_handoff": {"path": str(suite_handoff)},
                "openclaw_evidence": {"path": str(openclaw_evidence)},
            },
        },
    )

    output_dir = tmp_path / "support-bundle-fail"
    manifest_path = tmp_path / "support-bundle-fail.manifest.json"
    result = _run_script(
        "operator-support-bundle.ps1",
        "-ReadinessManifestPath",
        str(readiness_manifest),
        "-OutputDir",
        str(output_dir),
        "-OutPath",
        str(manifest_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["classification_status"] == "issues_detected"
    assert payload["has_blocking_findings"] is True
    assert payload["category_counts"]["policy"] >= 1
    assert payload["category_counts"]["semantic_output"] >= 1
    assert payload["category_counts"]["provider_auth"] >= 1

    class_payload = json.loads(
        Path(payload["failure_classification_json_path"]).read_text(encoding="utf-8")
    )
    assert class_payload["finding_count"] >= 4
    assert "next_steps" in class_payload
    assert len(class_payload["next_steps"]) >= 3
