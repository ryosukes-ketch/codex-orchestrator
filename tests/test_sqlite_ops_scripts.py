import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app.state.repository import SqliteProjectRepository

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


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for sqlite script tests.",
)
def test_sqlite_verify_script_passes_on_initialized_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "verify.sqlite3"
    repository = SqliteProjectRepository(str(db_path))
    repository.initialize_schema()
    repository.close()

    out_path = tmp_path / "verify-report.json"
    result = _run_script(
        "sqlite-verify.ps1",
        "-SqliteDbPath",
        str(db_path),
        "-OutPath",
        str(out_path),
    )
    assert result.returncode == 0, result.stderr
    assert out_path.exists()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    report = payload["report"]
    assert report["exists"] is True
    assert report["integrity_check_ok"] is True
    assert report["quick_check_ok"] is True
    assert report["missing_required_tables"] == []
    assert "projects" in report["tables"]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for sqlite script tests.",
)
def test_sqlite_backup_and_restore_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    repository = SqliteProjectRepository(str(db_path))
    repository.initialize_schema()
    repository.close()

    backup_manifest = tmp_path / "backup-manifest.json"
    backup_result = _run_script(
        "sqlite-backup.ps1",
        "-SqliteDbPath",
        str(db_path),
        "-OutPath",
        str(backup_manifest),
        "-Label",
        "pytest",
    )
    assert backup_result.returncode == 0, backup_result.stderr
    backup_payload = json.loads(backup_manifest.read_text(encoding="utf-8"))
    backup_db_path = Path(backup_payload["backup_db_path"])
    assert backup_db_path.exists()

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE marker_after_backup (id INTEGER PRIMARY KEY, note TEXT)")
        conn.execute("INSERT INTO marker_after_backup(note) VALUES ('mutated')")
        conn.commit()

    restore_report = tmp_path / "restore-report.json"
    restore_result = _run_script(
        "sqlite-restore.ps1",
        "-SqliteDbPath",
        str(db_path),
        "-BackupManifestPath",
        str(backup_manifest),
        "-Force",
        "-OutPath",
        str(restore_report),
    )
    assert restore_result.returncode == 0, restore_result.stderr
    restore_payload = json.loads(restore_report.read_text(encoding="utf-8"))
    assert Path(restore_payload["restored_db_path"]).exists()
    assert restore_payload["verify"]["integrity_check_ok"] is True
    assert restore_payload["verify"]["missing_required_tables"] == []

    with sqlite3.connect(str(db_path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        }
    assert "marker_after_backup" not in tables


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for sqlite script tests.",
)
def test_sqlite_restore_requires_force_when_target_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    repository = SqliteProjectRepository(str(db_path))
    repository.initialize_schema()
    repository.close()

    backup_manifest = tmp_path / "backup-manifest.json"
    backup_result = _run_script(
        "sqlite-backup.ps1",
        "-SqliteDbPath",
        str(db_path),
        "-OutPath",
        str(backup_manifest),
        "-Label",
        "pytest-force",
    )
    assert backup_result.returncode == 0, backup_result.stderr

    restore_result = _run_script(
        "sqlite-restore.ps1",
        "-SqliteDbPath",
        str(db_path),
        "-BackupManifestPath",
        str(backup_manifest),
    )
    assert restore_result.returncode != 0
    assert "Re-run with -Force" in (restore_result.stderr + restore_result.stdout)
