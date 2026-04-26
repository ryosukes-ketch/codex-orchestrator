import json
import os
import shutil
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
def test_sqlite_export_creates_manifest_and_archive(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    repository = SqliteProjectRepository(str(db_path))
    repository.initialize_schema()
    repository.close()

    output_dir = tmp_path / "sqlite-export"
    manifest_path = tmp_path / "sqlite-export-manifest.json"
    archive_path = tmp_path / "sqlite-export.zip"

    result = _run_script(
        "sqlite-export.ps1",
        "-SqliteDbPath",
        str(db_path),
        "-OutputDir",
        str(output_dir),
        "-Label",
        "pytest-export",
        "-Zip",
        "-ArchivePath",
        str(archive_path),
        "-OutPath",
        str(manifest_path),
    )
    assert result.returncode == 0, result.stderr
    assert output_dir.exists()
    assert manifest_path.exists()
    assert archive_path.exists()

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "sqlite_export"
    assert payload["source_db_path"] == str(db_path)
    assert Path(payload["backup_db_path"]).exists()
    assert Path(payload["backup_manifest_path"]).exists()
    assert Path(payload["verify_report_path"]).exists()
    assert payload["archive_path"] == str(archive_path)
