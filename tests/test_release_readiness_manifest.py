import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


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
    db_path = tmp_path / "readiness-manifest.sqlite3"
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


@pytest.mark.skipif(os.name != "nt", reason="PowerShell readiness script tests are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for readiness script tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for readiness script tests.",
)
def test_release_readiness_writes_manifest_bundle(tmp_path: Path) -> None:
    process, base_url = _start_test_server(tmp_path)
    try:
        relative_log_dir = Path("logs") / "test-release-readiness" / str(uuid.uuid4())
        command = [
            POWERSHELL_EXE,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "release-readiness.ps1"),
            "-ApiBaseUrl",
            base_url,
            "-Authorization",
            "Bearer dev-approver-token",
            "-AutoSeedFullFlow",
            "-SkipSmoke",
            "-SkipResilience",
            "-SkipVerify",
            "-RunOperatorSuite",
            "-OperatorRequireStageTelemetry",
            "-OperatorMaxLlmTransportFallbacks",
            "0",
            "-LogDir",
            str(relative_log_dir),
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        log_dir = ROOT / relative_log_dir
        summary_candidates = sorted(log_dir.glob("readiness-summary-*.json"))
        manifest_candidates = sorted(log_dir.glob("readiness-manifest-*.json"))
        assert summary_candidates
        assert manifest_candidates

        summary = json.loads(summary_candidates[-1].read_text(encoding="utf-8"))
        manifest = json.loads(manifest_candidates[-1].read_text(encoding="utf-8"))

        assert summary["overall_passed"] is True
        assert summary["stages"]["preflight"]["passed"] is True
        assert summary["stages"]["live_smoke"]["passed"] is True
        assert summary["stages"]["operator_suite"]["passed"] is True
        assert summary["flags"]["operator_require_policy_assertions"] is False
        assert summary["flags"]["operator_require_auth_evidence"] is False
        assert summary["flags"]["operator_expected_auth_roles"] == []
        assert summary["flags"]["operator_auth_policy_mode"] == ""
        assert summary["flags"]["operator_breakglass"] is False
        assert summary["flags"]["operator_breakglass_reason"] == ""
        assert summary["flags"]["operator_breakglass_actor"] == ""
        assert summary["flags"]["operator_skip_approval_mode"] is False
        assert summary["flags"]["operator_skip_reject_replan_mode"] is False
        assert summary["flags"]["operator_authorization_operator_provided"] is True
        assert summary["flags"]["operator_max_revision_replan_attempts"] == 1
        assert summary["flags"]["operator_policy_mode"] == "strict"
        assert summary["flags"]["operator_enforce_model_allowlist"] is False
        assert summary["flags"]["operator_fail_on_backend_override_mismatch"] is False

        assert manifest["bundle_type"] == "readiness"
        assert manifest["bundle_version"] == 1
        assert manifest["overall_passed"] is True
        assert manifest["artifacts"]["readiness_summary"]["path"].endswith(".json")
        assert Path(manifest["artifacts"]["readiness_summary"]["path"]).exists()
        assert Path(manifest["artifacts"]["live_smoke_log"]["path"]).exists()
        assert Path(manifest["artifacts"]["full_live_flow_seed_log"]["path"]).exists()
        assert Path(manifest["artifacts"]["operator_suite_manifest"]["path"]).exists()
        assert Path(manifest["artifacts"]["operator_suite_summary"]["path"]).exists()
        assert Path(manifest["artifacts"]["operator_suite_stage_gate"]["path"]).exists()
        assert Path(manifest["artifacts"]["operator_suite_handoff"]["path"]).exists()
        assert manifest["stages"]["operator_suite"]["suite_manifest_path"].endswith(
            "bundle-manifest.json"
        )
        assert "readiness manifest" in result.stdout.lower()
    finally:
        _terminate_process(process)
