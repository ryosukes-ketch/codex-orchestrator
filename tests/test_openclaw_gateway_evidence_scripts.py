import json
import os
import shutil
import socket
import subprocess
import threading
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
class _GatewayScenario:
    chat_status: int = 200
    chat_body: str = '{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}'
    responses_status: int = 200
    responses_body: str = '{"output":[{"content":[{"text":"{\\"ok\\":true}"}]}]}'
    models_status: int = 200
    models_body: str = '{"data":[]}'


def _make_handler(scenario: _GatewayScenario):
    class _GatewayHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            return

        def _send(self, status: int, body: str, content_type: str = "application/json") -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            if length > 0:
                _ = self.rfile.read(length)

            if self.path == "/v1/chat/completions":
                self._send(scenario.chat_status, scenario.chat_body)
                return
            if self.path == "/v1/responses":
                self._send(scenario.responses_status, scenario.responses_body)
                return
            self._send(404, "Not Found", content_type="text/plain")

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/v1/models":
                content_type = (
                    "text/html"
                    if "<openclaw-app>" in scenario.models_body
                    else "application/json"
                )
                self._send(scenario.models_status, scenario.models_body, content_type=content_type)
                return
            self._send(404, "Not Found", content_type="text/plain")

    return _GatewayHandler


@contextmanager
def _run_fake_gateway(scenario: _GatewayScenario):
    port = _get_free_tcp_port()
    server = HTTPServer(("127.0.0.1", port), _make_handler(scenario))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


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


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contract tests are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for gateway evidence script tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for gateway evidence script tests.",
)
def test_openclaw_gateway_check_writes_success_evidence(tmp_path: Path) -> None:
    with _run_fake_gateway(_GatewayScenario()) as base_url:
        evidence_path = tmp_path / "gateway-success.json"
        result = _run_script(
            "openclaw-gateway-check.ps1",
            "-GatewayBaseUrl",
            base_url,
            "-AgentId",
            "default",
            "-EvidenceOutPath",
            str(evidence_path),
            "-VerifiedBy",
            "pytest",
        )
    assert result.returncode == 0, result.stderr
    assert evidence_path.exists()
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["gateway_response_success"] is True
    assert payload["used_endpoint"] == "chat/completions"
    assert payload["fallback_used"] is False
    assert payload["status_code"] == 200
    assert payload["content_response_mode"] == "json_text"
    assert payload["content_kind"] == "json_text"
    assert payload["upstream_rejection_detected"] is False
    assert payload["models_probe_status_code"] == 200
    assert payload["models_probe_content_type"]
    assert isinstance(payload["models_probe_model_ids"], list)
    assert payload["models_probe_agent_model_present"] is False


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contract tests are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for gateway evidence script tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for gateway evidence script tests.",
)
def test_openclaw_gateway_check_classifies_upstream_rejection_success(tmp_path: Path) -> None:
    scenario = _GatewayScenario(
        chat_status=200,
        chat_body=(
            '{"choices":[{"message":{"content":"LLM request rejected: '
            'Your credit balance is too low to access the Anthropic API. '
            'Please go to Plans & Billing to upgrade or purchase credits."}}]}'
        ),
    )
    with _run_fake_gateway(scenario) as base_url:
        evidence_path = tmp_path / "gateway-upstream-rejection.json"
        result = _run_script(
            "openclaw-gateway-check.ps1",
            "-GatewayBaseUrl",
            base_url,
            "-EvidenceOutPath",
            str(evidence_path),
            "-VerifiedBy",
            "pytest",
        )
    assert result.returncode == 0, result.stderr
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["gateway_response_success"] is True
    assert payload["used_endpoint"] == "chat/completions"
    assert payload["content_response_mode"] == "plain_text_upstream_rejection"
    assert payload["content_kind"] == "upstream_rejection"
    assert payload["upstream_rejection_detected"] is True
    assert payload["upstream_provider"] == "anthropic"
    assert payload["upstream_rejection_reason"] == "credit_balance_too_low"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contract tests are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for gateway evidence script tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for gateway evidence script tests.",
)
def test_openclaw_gateway_check_marks_backend_override_provider_mismatch(tmp_path: Path) -> None:
    scenario = _GatewayScenario(
        chat_status=200,
        chat_body=(
            '{"choices":[{"message":{"content":"LLM request rejected: '
            'Your credit balance is too low to access the Anthropic API. '
            'Please go to Plans & Billing to upgrade or purchase credits."}}]}'
        ),
    )
    with _run_fake_gateway(scenario) as base_url:
        evidence_path = tmp_path / "gateway-upstream-rejection-override.json"
        result = _run_script(
            "openclaw-gateway-check.ps1",
            "-GatewayBaseUrl",
            base_url,
            "-BackendModel",
            "openai-codex/gpt-5.2",
            "-EvidenceOutPath",
            str(evidence_path),
            "-VerifiedBy",
            "pytest",
        )
    assert result.returncode == 0, result.stderr
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["backend_model"] == "openai-codex/gpt-5.2"
    assert payload["backend_override_provider"] == "openai"
    assert payload["backend_override_provider_mismatch"] is True
    assert payload["upstream_provider"] == "anthropic"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contract tests are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for gateway evidence script tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for gateway evidence script tests.",
)
def test_openclaw_gateway_check_writes_fallback_success_evidence(tmp_path: Path) -> None:
    scenario = _GatewayScenario(
        chat_status=404,
        chat_body="Not Found",
        responses_status=200,
        responses_body='{"output":[{"content":[{"text":"{\\"ok\\":true}"}]}]}',
    )
    with _run_fake_gateway(scenario) as base_url:
        evidence_path = tmp_path / "gateway-fallback-success.json"
        result = _run_script(
            "openclaw-gateway-check.ps1",
            "-GatewayBaseUrl",
            base_url,
            "-EvidenceOutPath",
            str(evidence_path),
            "-VerifiedBy",
            "pytest",
        )
    assert result.returncode == 0, result.stderr
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["gateway_response_success"] is True
    assert payload["used_endpoint"] == "responses"
    assert payload["fallback_used"] is True
    assert payload["status_code"] == 200
    assert payload["models_probe_status_code"] == 200
    assert isinstance(payload["models_probe_model_ids"], list)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contract tests are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for gateway evidence script tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for gateway evidence script tests.",
)
def test_openclaw_gateway_check_falls_back_when_chat_payload_invalid(tmp_path: Path) -> None:
    scenario = _GatewayScenario(
        chat_status=200,
        chat_body='{"ok":true}',
        responses_status=200,
        responses_body='{"output":[{"content":[{"text":"{\\"ok\\":true}"}]}]}',
    )
    with _run_fake_gateway(scenario) as base_url:
        evidence_path = tmp_path / "gateway-invalid-chat-fallback.json"
        result = _run_script(
            "openclaw-gateway-check.ps1",
            "-GatewayBaseUrl",
            base_url,
            "-EvidenceOutPath",
            str(evidence_path),
            "-VerifiedBy",
            "pytest",
        )
    assert result.returncode == 0, result.stderr
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["gateway_response_success"] is True
    assert payload["used_endpoint"] == "responses"
    assert payload["fallback_used"] is True
    assert payload["status_code"] == 200


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contract tests are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for gateway evidence script tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for gateway evidence script tests.",
)
def test_openclaw_gateway_check_writes_failure_evidence_and_staging_record(tmp_path: Path) -> None:
    scenario = _GatewayScenario(
        chat_status=404,
        chat_body="Not Found",
        responses_status=404,
        responses_body="Not Found",
        models_status=200,
        models_body="<openclaw-app></openclaw-app>",
    )
    with _run_fake_gateway(scenario) as base_url:
        evidence_path = tmp_path / "gateway-failure.json"
        staging_path = tmp_path / "staging.md"
        result = _run_script(
            "openclaw-gateway-check.ps1",
            "-GatewayBaseUrl",
            base_url,
            "-EvidenceOutPath",
            str(evidence_path),
            "-AppendStagingRecord",
            "-StagingRecordPath",
            str(staging_path),
            "-VerifiedBy",
            "pytest",
        )
    assert result.returncode != 0
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["gateway_response_success"] is False
    assert payload["used_endpoint"] == "responses"
    assert payload["fallback_used"] is True
    assert payload["status_code"] == 404
    assert payload["models_probe_control_html"] is True
    assert payload["models_probe_status_code"] == 200
    assert payload["models_probe_content_type"].startswith("text/html")
    content = staging_path.read_text(encoding="utf-8")
    assert "OpenClaw Gateway evidence" in content
    assert "Gateway response success: no" in content
    assert "Models probe status/content-type: 200 / text/html" in content


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contract tests are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for gateway evidence script tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for gateway evidence script tests.",
)
def test_openclaw_gateway_check_fails_on_invalid_responses_payload(tmp_path: Path) -> None:
    scenario = _GatewayScenario(
        chat_status=404,
        chat_body="Not Found",
        responses_status=200,
        responses_body='{"ok": true}',
        models_status=200,
        models_body="<openclaw-app></openclaw-app>",
    )
    with _run_fake_gateway(scenario) as base_url:
        evidence_path = tmp_path / "gateway-invalid-responses.json"
        result = _run_script(
            "openclaw-gateway-check.ps1",
            "-GatewayBaseUrl",
            base_url,
            "-EvidenceOutPath",
            str(evidence_path),
            "-VerifiedBy",
            "pytest",
        )
    assert result.returncode != 0
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["gateway_response_success"] is False
    assert payload["used_endpoint"] == "responses"
    assert payload["status_code"] == 200
    assert "payload invalid" in payload["details"]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contract tests are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for gateway evidence script tests.",
)
@pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe is required for gateway evidence script tests.",
)
def test_openclaw_evidence_capture_wrapper_writes_outputs(tmp_path: Path) -> None:
    with _run_fake_gateway(_GatewayScenario()) as base_url:
        evidence_path = tmp_path / "wrapper-evidence.json"
        staging_path = tmp_path / "wrapper-staging.md"
        result = _run_script(
            "openclaw-evidence-capture.ps1",
            "-GatewayBaseUrl",
            base_url,
            "-EvidenceOutPath",
            str(evidence_path),
            "-StagingRecordPath",
            str(staging_path),
            "-VerifiedBy",
            "pytest",
        )
    assert result.returncode == 0, result.stderr
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["gateway_response_success"] is True
    assert "OpenClaw Gateway evidence" in staging_path.read_text(encoding="utf-8")
