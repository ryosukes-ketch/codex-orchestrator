import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")
EXPECTED_STAGE_TELEMETRY_SOURCES = {
    "audit_totals",
    "summary_derived",
    "events_derived",
    "none",
}


def _get_free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(url: str, *, timeout_sec: int, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("API server exited before health check succeeded.")
        try:
            with urlopen(url, timeout=2) as response:
                body = response.read().decode("utf-8")
                if response.status == 200 and '"status":"ok"' in body:
                    return
        except URLError:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for health endpoint: {url}")


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _start_test_server(tmp_path: Path) -> tuple[subprocess.Popen[str], str]:
    db_path = tmp_path / "operator-e2e.sqlite3"
    port = _get_free_tcp_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "STATE_BACKEND": "sqlite",
            "SQLITE_DB_PATH": str(db_path),
            "STATE_BACKEND_STRICT": "true",
            "DEV_AUTH_ENABLED": "true",
            "TREND_PROVIDER_STRICT": "false",
        }
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    _wait_for_health(f"{base_url}/health", timeout_sec=30, process=process)
    return process, base_url


def _run_operator_script(script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
    result = _run_operator_script_raw(script_name, *args)
    if result.returncode != 0:
        pytest.fail(
            "Operator script failed:\n"
            f"script={script_name}\n"
            f"args={list(args)}\n"
            f"stdout=\n{result.stdout}\n"
            f"stderr=\n{result.stderr}"
        )
    return result


def _run_operator_script_raw(script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
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
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return result


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator script E2E tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for operator script E2E tests.",
)
def test_operator_scripts_e2e_approval_chain(tmp_path: Path) -> None:
    process, base_url = _start_test_server(tmp_path)
    try:
        run_out = tmp_path / "operator-run-approval.json"
        _run_operator_script(
            "operator-run.ps1",
            "-ApiBaseUrl",
            base_url,
            "-BriefPath",
            str(ROOT / "examples" / "briefs" / "sample_brief.json"),
            "-TrendProvider",
            "gemini-flash-lite-latest",
            "-TimeoutSec",
            "45",
            "-OutPath",
            str(run_out),
        )
        run_payload = json.loads(run_out.read_text(encoding="utf-8"))
        project_id = run_payload["summary"]["project_id"]
        assert run_payload["summary"]["status"] == "waiting_approval"

        status_before = _run_operator_script(
            "operator-status.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-TimeoutSec",
            "45",
            "-SummaryOutPath",
            str(tmp_path / "operator-status-before-summary.json"),
        )
        assert "status            : waiting_approval" in status_before.stdout
        status_before_summary = _read_json(tmp_path / "operator-status-before-summary.json")
        assert status_before_summary["status"] == "waiting_approval"
        assert status_before_summary["telemetry_source"] in EXPECTED_STAGE_TELEMETRY_SOURCES
        assert status_before_summary["telemetry_present"] is True
        assert status_before_summary["stage_totals"]["total_stage_executions"] >= 1

        _run_operator_script(
            "operator-approve.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-Authorization",
            "Bearer dev-approver-token",
            "-TimeoutSec",
            "45",
        )

        audit_out = tmp_path / "operator-audit-approval.json"
        _run_operator_script(
            "operator-audit.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-TimeoutSec",
            "45",
            "-OutPath",
            str(audit_out),
        )
        audit_payload = json.loads(audit_out.read_text(encoding="utf-8"))
        assert audit_payload["status"] == "completed"
        assert any(item["status"] == "approved" for item in audit_payload["approvals"])
        assert audit_payload["department_stage_summary"]
        assert any(
            item["department"] == "review" and item["stage_name"] == "FinalJudgment"
            for item in audit_payload["department_stage_summary"]
        )

        stage_report_out = tmp_path / "operator-stage-report-approval.json"
        _run_operator_script(
            "operator-stage-report.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-TimeoutSec",
            "45",
            "-OutPath",
            str(stage_report_out),
        )
        stage_report = json.loads(stage_report_out.read_text(encoding="utf-8"))
        assert stage_report["project_id"] == project_id
        assert stage_report["stage_totals"]["total_stage_executions"] >= 1
        assert "total_llm_transport_fallbacks" in stage_report["stage_totals"]
        assert (
            stage_report["stage_totals"]["total_successes"]
            + stage_report["stage_totals"]["total_failures"]
            == stage_report["stage_totals"]["total_stage_executions"]
        )

        assert_out = tmp_path / "operator-audit-assert-approval.json"
        _run_operator_script(
            "operator-audit-assert.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-ExpectedStatus",
            "completed",
            "-RequireDepartments",
            "build,review",
            "-TimeoutSec",
            "45",
            "-OutPath",
            str(assert_out),
        )
        assert_report = _read_json(assert_out)
        assert assert_report["passed"] is True
        assert assert_report["error_count"] == 0
    finally:
        _terminate_process(process)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator script E2E tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for operator script E2E tests.",
)
def test_operator_scripts_e2e_reject_revision_replanning_chain(tmp_path: Path) -> None:
    process, base_url = _start_test_server(tmp_path)
    try:
        run_out = tmp_path / "operator-run-reject.json"
        _run_operator_script(
            "operator-run.ps1",
            "-ApiBaseUrl",
            base_url,
            "-BriefPath",
            str(ROOT / "examples" / "briefs" / "sample_brief.json"),
            "-TrendProvider",
            "gemini-flash-lite-latest",
            "-TimeoutSec",
            "45",
            "-OutPath",
            str(run_out),
        )
        run_payload = json.loads(run_out.read_text(encoding="utf-8"))
        project_id = run_payload["summary"]["project_id"]
        assert run_payload["summary"]["status"] == "waiting_approval"

        _run_operator_script(
            "operator-reject.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-Reason",
            "Security policy",
            "-Authorization",
            "Bearer dev-approver-token",
            "-TimeoutSec",
            "45",
        )
        _run_operator_script(
            "operator-revise.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-ResumeMode",
            "replanning",
            "-Authorization",
            "Bearer dev-operator-token",
            "-TimeoutSec",
            "45",
        )
        _run_operator_script(
            "operator-replan.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-Authorization",
            "Bearer dev-operator-token",
            "-TimeoutSec",
            "45",
        )

        status_after = _run_operator_script(
            "operator-status.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-TimeoutSec",
            "45",
            "-SummaryOutPath",
            str(tmp_path / "operator-status-after-summary.json"),
        )
        assert "status            : completed" in status_after.stdout
        assert "telemetry   :" in status_after.stdout
        status_after_summary = _read_json(tmp_path / "operator-status-after-summary.json")
        assert status_after_summary["status"] == "completed"
        assert status_after_summary["telemetry_source"] in EXPECTED_STAGE_TELEMETRY_SOURCES
        assert "total_llm_transport_fallbacks" in status_after_summary["stage_totals"]

        audit_out = tmp_path / "operator-audit-reject.json"
        _run_operator_script(
            "operator-audit.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-TimeoutSec",
            "45",
            "-OutPath",
            str(audit_out),
        )
        audit_payload = json.loads(audit_out.read_text(encoding="utf-8"))
        assert audit_payload["status"] == "completed"
        assert any(item["status"] == "rejected" for item in audit_payload["approvals"])
        assert audit_payload["department_stage_summary"]
        assert any(
            item["department"] == "build" and item["stage_name"] == "Tester"
            for item in audit_payload["department_stage_summary"]
        )

        stage_report_out = tmp_path / "operator-stage-report-reject.json"
        _run_operator_script(
            "operator-stage-report.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-TimeoutSec",
            "45",
            "-OutPath",
            str(stage_report_out),
        )
        stage_report = json.loads(stage_report_out.read_text(encoding="utf-8"))
        assert stage_report["project_id"] == project_id
        assert stage_report["stage_totals"]["total_stage_executions"] >= 1
        assert "total_llm_transport_fallbacks" in stage_report["stage_totals"]

        assert_out = tmp_path / "operator-audit-assert-reject.json"
        _run_operator_script(
            "operator-audit-assert.ps1",
            "-ApiBaseUrl",
            base_url,
            "-ProjectId",
            project_id,
            "-ExpectedStatus",
            "completed",
            "-RequireDepartments",
            "build,review",
            "-TimeoutSec",
            "45",
            "-OutPath",
            str(assert_out),
        )
        assert_report = _read_json(assert_out)
        assert assert_report["passed"] is True
        assert assert_report["error_count"] == 0
    finally:
        _terminate_process(process)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator script E2E tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for operator script E2E tests.",
)
def test_operator_full_cycle_script_approval_mode(tmp_path: Path) -> None:
    process, base_url = _start_test_server(tmp_path)
    try:
        output_dir = tmp_path / "cycle-approval"
        _run_operator_script(
            "operator-full-cycle.ps1",
            "-Mode",
            "approval",
            "-ApiBaseUrl",
            base_url,
            "-BriefPath",
            str(ROOT / "examples" / "briefs" / "sample_brief.json"),
            "-RunTrendProvider",
            "gemini-flash-lite-latest",
            "-TimeoutSec",
            "45",
            "-OutputDir",
            str(output_dir),
        )

        summary_path = output_dir / "summary.json"
        assert summary_path.exists()
        summary = _read_json(summary_path)
        assert summary["mode"] == "approval"
        assert summary["final_status"] == "completed"
        assert summary["project_id"]
        assert summary["files"]["run"]
        assert summary["files"]["approve"]
        assert summary["files"]["audit"]
        assert summary["files"]["status"]
        assert summary["files"]["status_summary"]
        assert summary["files"]["audit_assert"]
        assert summary["files"]["bundle_manifest"]
        assert summary["audit_assert_passed"] is True
        assert summary["require_auth_evidence"] is False
        assert summary["expected_auth_roles"] == []
        assert summary["auth_policy_mode"] == "strict"
        assert summary["breakglass_used"] is False
        assert summary["breakglass_reason"] == ""
        assert summary["breakglass_actor"] == ""
        assert isinstance(summary["auth_evidence_present"], bool)
        assert summary["stage_telemetry_source"] in EXPECTED_STAGE_TELEMETRY_SOURCES
        assert isinstance(summary["stage_telemetry_notes"], list)
        assert isinstance(summary["stage_legacy_fallback_normalizations"], int)
        assert summary["stage_legacy_fallback_normalizations"] >= 0
        bundle_manifest = _read_json(Path(summary["files"]["bundle_manifest"]))
        assert bundle_manifest["bundle_type"] == "cycle"
        assert bundle_manifest["bundle_version"] == 1
        assert bundle_manifest["project_id"] == summary["project_id"]
        assert Path(bundle_manifest["artifacts"]["summary"]["path"]).name == "summary.json"
        assert (
            Path(bundle_manifest["artifacts"]["status_summary"]["path"]).name
            == "status-summary.json"
        )
        assert Path(bundle_manifest["artifacts"]["audit"]["path"]).name == "audit.json"
        assert (
            Path(bundle_manifest["artifacts"]["bundle_manifest"]["path"]).name
            == "bundle-manifest.json"
        )
        status_summary = _read_json(Path(summary["files"]["status_summary"]))
        assert status_summary["status"] == "completed"
        assert status_summary["telemetry_source"] in EXPECTED_STAGE_TELEMETRY_SOURCES
        assert status_summary["telemetry_present"] is True

        audit_payload = _read_json(Path(summary["files"]["audit"]))
        assert audit_payload["status"] == "completed"
        assert any(item["status"] == "approved" for item in audit_payload["approvals"])

        stage_report_path = Path(summary["files"]["stage_report"])
        assert stage_report_path.exists()
        stage_report = _read_json(stage_report_path)
        assert stage_report["stage_totals"]["total_stage_executions"] >= 1
        assert "total_llm_transport_fallbacks" in stage_report["stage_totals"]
    finally:
        _terminate_process(process)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator script E2E tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for operator script E2E tests.",
)
def test_operator_full_cycle_approval_collects_operator_auth_evidence_when_required(
    tmp_path: Path,
) -> None:
    process, base_url = _start_test_server(tmp_path)
    try:
        output_dir = tmp_path / "cycle-approval-auth"
        _run_operator_script(
            "operator-full-cycle.ps1",
            "-Mode",
            "approval",
            "-ApiBaseUrl",
            base_url,
            "-BriefPath",
            str(ROOT / "examples" / "briefs" / "sample_brief.json"),
            "-RunTrendProvider",
            "gemini-flash-lite-latest",
            "-TimeoutSec",
            "45",
            "-OutputDir",
            str(output_dir),
            "-RequireAuthEvidence",
            "-ExpectedAuthRoles",
            "operator,approver",
            "-AuthPolicyMode",
            "strict",
        )

        summary = _read_json(output_dir / "summary.json")
        assert summary["final_status"] == "completed"
        assert summary["audit_assert_passed"] is True
        assert summary["require_auth_evidence"] is True
        assert summary["expected_auth_roles"] == ["operator", "approver"]
        assert summary["auth_policy_mode"] == "strict"
        assert summary["auth_evidence_present"] is True
        assert Path(summary["files"]["operator_auth_probe"]).exists()

        audit_assert = _read_json(Path(summary["files"]["audit_assert"]))
        assert audit_assert["passed"] is True
        operator_role = audit_assert["auth_evidence"]["roles"]["operator"]
        approver_role = audit_assert["auth_evidence"]["roles"]["approver"]
        assert operator_role["evidence_present"] is True
        assert approver_role["evidence_present"] is True
    finally:
        _terminate_process(process)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator script E2E tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for operator script E2E tests.",
)
def test_operator_full_cycle_script_reject_replan_mode(tmp_path: Path) -> None:
    process, base_url = _start_test_server(tmp_path)
    try:
        output_dir = tmp_path / "cycle-reject-replan"
        _run_operator_script(
            "operator-full-cycle.ps1",
            "-Mode",
            "reject-replan",
            "-ApiBaseUrl",
            base_url,
            "-BriefPath",
            str(ROOT / "examples" / "briefs" / "sample_brief.json"),
            "-RunTrendProvider",
            "gemini-flash-lite-latest",
            "-TimeoutSec",
            "45",
            "-OutputDir",
            str(output_dir),
        )

        summary_path = output_dir / "summary.json"
        assert summary_path.exists()
        summary = _read_json(summary_path)
        assert summary["mode"] == "reject-replan"
        assert summary["final_status"] == "completed"
        assert summary["files"]["run"]
        assert summary["files"]["reject"]
        assert summary["files"]["revise"]
        assert summary["files"]["replan"]
        assert summary["files"]["audit"]
        assert summary["files"]["status"]
        assert summary["files"]["status_summary"]
        assert summary["files"]["audit_assert"]
        assert summary["files"]["bundle_manifest"]
        assert summary["audit_assert_passed"] is True
        assert summary["require_auth_evidence"] is False
        assert summary["expected_auth_roles"] == []
        assert summary["auth_policy_mode"] == "strict"
        assert summary["breakglass_used"] is False
        assert summary["breakglass_reason"] == ""
        assert summary["breakglass_actor"] == ""
        assert isinstance(summary["auth_evidence_present"], bool)
        assert summary["stage_telemetry_source"] in EXPECTED_STAGE_TELEMETRY_SOURCES
        assert isinstance(summary["stage_telemetry_notes"], list)
        assert isinstance(summary["stage_legacy_fallback_normalizations"], int)
        assert summary["stage_legacy_fallback_normalizations"] >= 0
        bundle_manifest = _read_json(Path(summary["files"]["bundle_manifest"]))
        assert bundle_manifest["bundle_type"] == "cycle"
        assert bundle_manifest["bundle_version"] == 1
        assert bundle_manifest["project_id"] == summary["project_id"]
        assert Path(bundle_manifest["artifacts"]["summary"]["path"]).name == "summary.json"
        assert (
            Path(bundle_manifest["artifacts"]["status_summary"]["path"]).name
            == "status-summary.json"
        )
        assert Path(bundle_manifest["artifacts"]["audit"]["path"]).name == "audit.json"
        assert (
            Path(bundle_manifest["artifacts"]["bundle_manifest"]["path"]).name
            == "bundle-manifest.json"
        )
        status_summary = _read_json(Path(summary["files"]["status_summary"]))
        assert status_summary["status"] == "completed"
        assert status_summary["telemetry_source"] in EXPECTED_STAGE_TELEMETRY_SOURCES
        assert status_summary["telemetry_present"] is True

        audit_payload = _read_json(Path(summary["files"]["audit"]))
        assert audit_payload["status"] == "completed"
        assert any(item["status"] == "rejected" for item in audit_payload["approvals"])

        stage_report_path = Path(summary["files"]["stage_report"])
        assert stage_report_path.exists()
        stage_report = _read_json(stage_report_path)
        assert stage_report["stage_totals"]["total_stage_executions"] >= 1
    finally:
        _terminate_process(process)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell operator scripts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for operator script E2E tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for operator script E2E tests.",
)
def test_operator_cycle_suite_and_handoff_envelope(tmp_path: Path) -> None:
    process, base_url = _start_test_server(tmp_path)
    try:
        suite_dir = tmp_path / "operator-suite"
        _run_operator_script(
            "operator-cycle-suite.ps1",
            "-ApiBaseUrl",
            base_url,
            "-BriefPath",
            str(ROOT / "examples" / "briefs" / "sample_brief.json"),
            "-RunTrendProvider",
            "gemini-flash-lite-latest",
            "-TimeoutSec",
            "45",
            "-OutputDir",
            str(suite_dir),
        )

        suite_summary_path = suite_dir / "suite-summary.json"
        suite_handoff_json_path = suite_dir / "suite-handoff.json"
        suite_handoff_md_path = suite_dir / "suite-handoff.md"
        suite_stage_gate_path = suite_dir / "suite-stage-gate.json"

        assert suite_summary_path.exists()
        assert suite_handoff_json_path.exists()
        assert suite_handoff_md_path.exists()
        assert suite_stage_gate_path.exists()

        suite_summary = _read_json(suite_summary_path)
        assert suite_summary["cycle_count"] == 2
        assert suite_summary["all_completed"] is True
        assert suite_summary["all_audit_assertions_passed"] is True
        assert suite_summary["stage_gate_passed"] is True
        assert suite_summary["require_auth_evidence"] is False
        assert suite_summary["expected_auth_roles"] == []
        assert suite_summary["auth_policy_mode"] == ""
        assert suite_summary["breakglass_used"] is False
        assert suite_summary["breakglass_reason"] == ""
        assert suite_summary["breakglass_actor"] == ""
        assert "total_llm_transport_fallbacks" in suite_summary
        assert "total_stage_legacy_fallback_normalizations" in suite_summary
        assert "stage_telemetry_sources" in suite_summary
        assert set(suite_summary["modes"]) == {"approval", "reject-replan"}
        assert "bundle_manifest" in suite_summary["files"]
        assert "status_summaries" in suite_summary["files"]
        assert set(suite_summary["files"]["status_summaries"].keys()) == {
            "approval",
            "reject-replan",
        }
        assert "cycle_manifests" in suite_summary["files"]
        assert set(suite_summary["files"]["cycle_manifests"].keys()) == {
            "approval",
            "reject-replan",
        }
        for cycle in suite_summary["cycles"]:
            assert Path(cycle["summary_path"]).exists()
            assert Path(cycle["status_summary_path"]).exists()
            assert Path(cycle["bundle_manifest_path"]).exists()
            assert cycle["final_status"] == "completed"
            assert cycle["audit_assert_passed"] is True
            assert cycle["require_auth_evidence"] is False
            assert cycle["expected_auth_roles"] == []
            assert cycle["auth_policy_mode"] == "strict"
            assert cycle["breakglass_used"] is False
            assert cycle["breakglass_reason"] == ""
            assert cycle["breakglass_actor"] == ""
            assert isinstance(cycle["auth_evidence_present"], bool)
            assert "stage_legacy_fallback_normalizations" in cycle

        suite_manifest = _read_json(Path(suite_summary["files"]["bundle_manifest"]))
        assert suite_manifest["bundle_type"] == "suite"
        assert suite_manifest["bundle_version"] == 1
        assert (
            Path(suite_manifest["artifacts"]["suite_summary"]["path"]).name
            == "suite-summary.json"
        )
        assert (
            Path(suite_manifest["artifacts"]["handoff_json"]["path"]).name
            == "suite-handoff.json"
        )
        assert (
            Path(suite_manifest["artifacts"]["stage_gate"]["path"]).name
            == "suite-stage-gate.json"
        )
        assert (
            Path(suite_manifest["artifacts"]["bundle_manifest"]["path"]).name
            == "bundle-manifest.json"
        )
        assert {cycle["mode"] for cycle in suite_manifest["cycles"]} == {
            "approval",
            "reject-replan",
        }
        for cycle in suite_manifest["cycles"]:
            assert Path(cycle["summary_path"]).name == "summary.json"
            assert Path(cycle["status_summary_path"]).name == "status-summary.json"
            assert Path(cycle["bundle_manifest_path"]).name == "bundle-manifest.json"

        suite_handoff = _read_json(suite_handoff_json_path)
        assert suite_handoff["source_type"] == "suite"
        assert suite_handoff["all_completed"] is True
        assert suite_handoff["all_audit_assertions_passed"] is True
        assert len(suite_handoff["cycles"]) == 2
        assert suite_handoff["total_stage_runs"] >= 1
        assert "total_llm_transport_fallbacks" in suite_handoff
        assert "total_stage_legacy_fallback_normalizations" in suite_handoff
        assert suite_handoff["project_ids"]
        for cycle in suite_handoff["cycles"]:
            assert Path(cycle["status_summary_path"]).exists()

        suite_stage_gate = _read_json(suite_stage_gate_path)
        assert suite_stage_gate["passed"] is True
        assert suite_stage_gate["cycle_count"] == 2
        assert suite_stage_gate["summary_type"] == "suite"
        assert "legacy_fallback_normalizations" in suite_stage_gate["totals"]
        for cycle in suite_stage_gate["cycles"]:
            assert Path(cycle["status_summary_path"]).exists()

        strict_gate = _run_operator_script_raw(
            "operator-stage-gate.ps1",
            "-SummaryPath",
            str(suite_summary_path),
            "-MaxLlmTransportFallbacks",
            "0",
        )
        assert strict_gate.returncode == 0

        handoff_from_manifest = tmp_path / "suite-handoff-from-manifest.json"
        manifest_handoff_result = _run_operator_script(
            "operator-handoff-envelope.ps1",
            "-BundleManifestPath",
            str(suite_summary["files"]["bundle_manifest"]),
            "-OutPath",
            str(handoff_from_manifest),
        )
        assert manifest_handoff_result.returncode == 0
        manifest_handoff = _read_json(handoff_from_manifest)
        assert manifest_handoff["source_type"] == "suite"
        assert manifest_handoff["all_completed"] is True

        manifest_gate_path = tmp_path / "suite-stage-gate-from-manifest.json"
        manifest_gate = _run_operator_script_raw(
            "operator-stage-gate.ps1",
            "-BundleManifestPath",
            str(suite_summary["files"]["bundle_manifest"]),
            "-OutPath",
            str(manifest_gate_path),
            "-MaxLlmTransportFallbacks",
            "0",
        )
        assert manifest_gate.returncode == 0, manifest_gate.stderr
        manifest_gate_payload = _read_json(manifest_gate_path)
        assert manifest_gate_payload["passed"] is True
        assert manifest_gate_payload["summary_type"] == "suite"
    finally:
        _terminate_process(process)
