import json
import os
import shutil
import socket
import subprocess
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


def _get_free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class _Scenario:
    project_id: str = "project-seed-mismatch"
    run_status: str = "in_progress"
    use_stage_events: bool = True
    use_stage_summary: bool = False


def _make_handler(scenario: _Scenario):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            if length > 0:
                _ = self.rfile.read(length)

            if self.path == "/orchestrator/run":
                self._send_json(
                    {
                        "summary": {
                            "project_id": scenario.project_id,
                            "status": scenario.run_status,
                            "next_steps": [
                                "Investigate department stage telemetry for runtime failures."
                            ],
                        }
                    }
                )
                return

            self._send_json({"detail": "Not Found"}, status=404)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == f"/projects/{scenario.project_id}/audit":
                events = []
                if scenario.use_stage_events:
                    events = [
                        {
                            "event_type": "department_stage_executed",
                            "department": "research",
                            "stage_name": "ScopeFraming",
                            "sequence": 1,
                            "stage_success": False,
                            "stage_failure_reason": "llm_exception:RuntimeError",
                            "effective_model": "openclaw/codex-orchestrator@openai-codex/gpt-5.2",
                            "llm_endpoint": "chat/completions",
                        }
                    ]
                stage_summary = []
                if scenario.use_stage_summary:
                    stage_summary = [
                        {
                            "department": "research",
                            "stage_name": "ScopeFraming",
                            "sequence": 1,
                            "failure_count": 1,
                            "failure_reasons": ["llm_exception:RuntimeError"],
                            "effective_models": [
                                "openclaw/codex-orchestrator@openai-codex/gpt-5.2"
                            ],
                            "llm_endpoints": ["chat/completions"],
                        }
                    ]
                self._send_json(
                    {
                        "project_id": scenario.project_id,
                        "status": "in_progress",
                        "events": events,
                        "department_stage_summary": stage_summary,
                    }
                )
                return

            self._send_json({"detail": "Not Found"}, status=404)

    return _Handler


@contextmanager
def _run_fake_api(scenario: _Scenario):
    port = _get_free_tcp_port()
    server = HTTPServer(("127.0.0.1", port), _make_handler(scenario))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL_EXE is not None
    command = [
        POWERSHELL_EXE,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / "full-live-flow.ps1"),
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


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contract tests are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for full-live-flow script tests.",
)
def test_full_live_flow_seed_mismatch_writes_audit_snapshot(tmp_path: Path) -> None:
    scenario = _Scenario(project_id=f"seed-mismatch-{uuid.uuid4()}")
    relative_log_dir = Path("logs") / "test-full-live-flow" / str(uuid.uuid4())

    with _run_fake_api(scenario) as base_url:
        result = _run_script(
            "-ApiBaseUrl",
            base_url,
            "-SkipPreflight",
            "-NoRuff",
            "-LogDir",
            str(relative_log_dir),
        )

    assert result.returncode != 0
    assert "[seed-mismatch]" in result.stdout

    diag_files = sorted((ROOT / relative_log_dir).glob("full-live-flow-seed-mismatch-*.json"))
    assert diag_files, "Expected full-live-flow seed mismatch diagnostic file."
    payload = json.loads(diag_files[-1].read_text(encoding="utf-8"))

    assert payload["expected_status"] == "waiting_approval"
    assert payload["actual_status"] == "in_progress"
    assert payload["project_id"] == scenario.project_id
    assert payload["trend_provider"] == "gemini-flash-lite-latest"

    snapshot = payload["audit_snapshot"]
    assert snapshot["fetched"] is True
    assert snapshot["project_status"] == "in_progress"
    assert snapshot["failing_stage_count"] == 1
    assert snapshot["failing_stages"][0]["department"] == "research"
    assert snapshot["failing_stages"][0]["stage_name"] == "ScopeFraming"
    assert snapshot["failing_stages"][0]["failure_reason"] == "llm_exception:RuntimeError"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contract tests are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for full-live-flow script tests.",
)
def test_full_live_flow_seed_mismatch_uses_stage_summary_when_events_missing(
    tmp_path: Path,
) -> None:
    scenario = _Scenario(
        project_id=f"seed-mismatch-summary-{uuid.uuid4()}",
        use_stage_events=False,
        use_stage_summary=True,
    )
    relative_log_dir = Path("logs") / "test-full-live-flow" / str(uuid.uuid4())

    with _run_fake_api(scenario) as base_url:
        result = _run_script(
            "-ApiBaseUrl",
            base_url,
            "-SkipPreflight",
            "-NoRuff",
            "-LogDir",
            str(relative_log_dir),
        )

    assert result.returncode != 0
    diag_files = sorted((ROOT / relative_log_dir).glob("full-live-flow-seed-mismatch-*.json"))
    assert diag_files
    payload = json.loads(diag_files[-1].read_text(encoding="utf-8"))
    snapshot = payload["audit_snapshot"]
    assert snapshot["fetched"] is True
    assert snapshot["department_stage_event_count"] == 0
    assert snapshot["department_stage_summary_count"] == 1
    assert snapshot["failing_stage_count"] == 1
    assert snapshot["failing_stages"][0]["stage_name"] == "ScopeFraming"
    assert snapshot["failing_stages"][0]["failure_reason"] == "llm_exception:RuntimeError"
