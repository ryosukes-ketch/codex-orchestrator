import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


def _run_preflight_script(
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
        str(ROOT / "scripts" / "self-serve-preflight.ps1"),
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
        timeout=180,
        check=False,
        env=process_env,
    )


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for self-serve preflight tests.",
)
def test_self_serve_preflight_passes_with_sqlite_baseline(tmp_path: Path) -> None:
    sqlite_db = tmp_path / "state" / "codex.db"
    sqlite_backup = tmp_path / "backups"
    env_path = tmp_path / ".env.selfserve"
    out_path = tmp_path / "preflight-pass.json"

    env_path.write_text(
        "\n".join(
            [
                "STATE_BACKEND=sqlite",
                "STATE_BACKEND_STRICT=true",
                f"SQLITE_DB_PATH={sqlite_db}",
                f"SQLITE_BACKUP_DIR={sqlite_backup}",
                "OPERATOR_API_TIMEOUT_SECONDS=600",
                "OPENCLAW_BASE_URL=http://127.0.0.1:18789/v1",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_preflight_script(
        "-EnvPath",
        str(env_path),
        "-OutPath",
        str(out_path),
        env={
            "STATE_BACKEND": "sqlite",
            "STATE_BACKEND_STRICT": "true",
            "SQLITE_DB_PATH": str(sqlite_db),
            "SQLITE_BACKUP_DIR": str(sqlite_backup),
            "OPERATOR_API_TIMEOUT_SECONDS": "600",
            "OPENCLAW_BASE_URL": "http://127.0.0.1:18789/v1",
        },
    )
    assert result.returncode == 0, result.stderr
    assert out_path.exists()

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["failed_check_count"] == 0
    assert report["resolved"]["state_backend"] == "sqlite"
    assert report["resolved"]["state_backend_strict"].lower() == "true"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for self-serve preflight tests.",
)
def test_self_serve_preflight_fails_when_strict_flag_invalid(tmp_path: Path) -> None:
    sqlite_db = tmp_path / "state" / "codex.db"
    sqlite_backup = tmp_path / "backups"
    env_path = tmp_path / ".env.invalid"
    out_path = tmp_path / "preflight-fail.json"

    env_path.write_text(
        "\n".join(
            [
                "STATE_BACKEND=sqlite",
                "STATE_BACKEND_STRICT=maybe",
                f"SQLITE_DB_PATH={sqlite_db}",
                f"SQLITE_BACKUP_DIR={sqlite_backup}",
                "OPERATOR_API_TIMEOUT_SECONDS=600",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_preflight_script(
        "-EnvPath",
        str(env_path),
        "-OutPath",
        str(out_path),
        env={
            "STATE_BACKEND": "sqlite",
            "STATE_BACKEND_STRICT": "maybe",
            "SQLITE_DB_PATH": str(sqlite_db),
            "SQLITE_BACKUP_DIR": str(sqlite_backup),
            "OPERATOR_API_TIMEOUT_SECONDS": "600",
        },
    )
    assert result.returncode != 0
    assert out_path.exists()

    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    failed_names = {entry["name"] for entry in report["checks"] if not entry["passed"]}
    assert "state_backend_strict_true" in failed_names
