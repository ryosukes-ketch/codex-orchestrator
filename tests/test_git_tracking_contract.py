import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _require_git_worktree() -> None:
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip("git worktree is not available in this runtime")


def test_split_runtime_entrypoint_files_are_git_tracked() -> None:
    _require_git_worktree()
    required = (
        "app/ai_work_system/__init__.py",
        "app/ai_work_system/main.py",
        "app/macro_pulser/__init__.py",
        "app/macro_pulser/main.py",
        "scripts/ai_work_system/start-server.ps1",
        "scripts/ai_work_system/release-readiness.ps1",
        "scripts/ai_work_system/operator-menu.ps1",
        "scripts/macro_pulser/run-api.ps1",
        "scripts/macro_pulser/run-live.ps1",
        "scripts/macro_pulser/run-backfill.ps1",
        "scripts/macro_pulser/run-replay.ps1",
        "scripts/macro_pulser/local-dev-smoke.ps1",
    )

    for rel in required:
        probe = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert probe.returncode == 0, f"{rel} must be git-tracked"
