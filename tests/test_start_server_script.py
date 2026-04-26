import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


def _run_start_server_script(
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL_EXE is not None
    command = [
        POWERSHELL_EXE,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / "start-server.ps1"),
        *args,
    ]
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=process_env,
    )


@pytest.mark.skipif(os.name != "nt", reason="PowerShell startup script is Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for startup script tests.",
)
def test_start_server_use_openclaw_default_profile_emits_effective_config_json(
    tmp_path: Path,
) -> None:
    result = _run_start_server_script(
        "-UseOpenClawDefaultProfile",
        "-PrintEffectiveConfigOnly",
        env={
            "STATE_BACKEND": "sqlite",
            "SQLITE_DB_PATH": str(tmp_path / "phase6.sqlite3"),
            "RESEARCH_MODEL": "",
            "DESIGN_MODEL": "",
            "BUILD_MODEL": "",
            "REVIEW_MODEL": "",
        },
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["state_backend"] == "sqlite"
    assert payload["use_openclaw_default_profile"] is True
    assert payload["department_models"] == {
        "research": "openclaw/codex-orchestrator",
        "design": "openclaw/codex-orchestrator",
        "build": "openclaw/codex-orchestrator",
        "review": "openclaw/codex-orchestrator",
    }


@pytest.mark.skipif(os.name != "nt", reason="PowerShell startup script is Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for startup script tests.",
)
def test_start_server_specific_department_model_overrides_take_precedence(tmp_path: Path) -> None:
    result = _run_start_server_script(
        "-DepartmentModel",
        "openclaw/codex-orchestrator",
        "-BuildModel",
        "openclaw/codex-orchestrator@openai-codex/gpt-5.2",
        "-OpenClawBaseUrl",
        "http://127.0.0.1:18789/v1",
        "-OpenClawBackendModel",
        "openai-codex/gpt-5.2",
        "-PrintEffectiveConfigOnly",
        env={
            "STATE_BACKEND": "sqlite",
            "SQLITE_DB_PATH": str(tmp_path / "phase6.sqlite3"),
            "BUILD_MODEL": "mock",
        },
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["department_models"] == {
        "research": "openclaw/codex-orchestrator",
        "design": "openclaw/codex-orchestrator",
        "build": "openclaw/codex-orchestrator@openai-codex/gpt-5.2",
        "review": "openclaw/codex-orchestrator",
    }
    assert payload["openclaw"] == {
        "base_url": "http://127.0.0.1:18789/v1",
        "backend_model": "openai-codex/gpt-5.2",
    }
