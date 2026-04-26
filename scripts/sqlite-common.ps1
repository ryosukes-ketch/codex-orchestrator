function Get-SqliteRepoRoot {
    param([string]$ScriptRoot)
    return (Split-Path -Parent $ScriptRoot)
}

function Get-SqlitePythonExe {
    param([string]$RepoRoot)

    $pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $pythonExe) {
        return $pythonExe
    }
    return "python"
}

function Get-SqliteDotEnvValues {
    param([string]$RepoRoot)

    $envMap = @{}
    $envFile = Join-Path $RepoRoot ".env"
    if (-not (Test-Path $envFile)) {
        return $envMap
    }

    foreach ($line in (Get-Content $envFile -Encoding utf8)) {
        if ($line -match "^\s*#" -or [string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        if ($line -match "^([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
            $key = $Matches[1]
            $value = $Matches[2].Trim()
            if (-not $envMap.ContainsKey($key)) {
                $envMap[$key] = $value
            }
        }
    }
    return $envMap
}

function Resolve-SqliteDbPath {
    param(
        [string]$RepoRoot,
        [string]$SqliteDbPath = ""
    )

    $candidate = ([string]$SqliteDbPath).Trim()
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $candidate = [System.Environment]::GetEnvironmentVariable("SQLITE_DB_PATH", "Process")
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $envMap = Get-SqliteDotEnvValues -RepoRoot $RepoRoot
        if ($envMap.ContainsKey("SQLITE_DB_PATH")) {
            $candidate = [string]$envMap["SQLITE_DB_PATH"]
        }
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $candidate = "data/codex.db"
    }

    if ([System.IO.Path]::IsPathRooted($candidate)) {
        return [System.IO.Path]::GetFullPath($candidate)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $candidate))
}

function Resolve-SqliteBackupDir {
    param(
        [string]$RepoRoot,
        [string]$BackupDir = ""
    )

    $candidate = ([string]$BackupDir).Trim()
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $candidate = [System.Environment]::GetEnvironmentVariable("SQLITE_BACKUP_DIR", "Process")
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $envMap = Get-SqliteDotEnvValues -RepoRoot $RepoRoot
        if ($envMap.ContainsKey("SQLITE_BACKUP_DIR")) {
            $candidate = [string]$envMap["SQLITE_BACKUP_DIR"]
        }
    }
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        $candidate = "logs/sqlite-backups"
    }

    if ([System.IO.Path]::IsPathRooted($candidate)) {
        return [System.IO.Path]::GetFullPath($candidate)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $candidate))
}

function Invoke-SqlitePythonJson {
    param(
        [string]$PythonExe,
        [string]$Code,
        [string[]]$ScriptArgs = @()
    )

    $tempScriptPath = Join-Path ([System.IO.Path]::GetTempPath()) ("sqlite-helper-" + [guid]::NewGuid().ToString("N") + ".py")
    [System.IO.File]::WriteAllText($tempScriptPath, $Code, [System.Text.Encoding]::UTF8)
    try {
        $output = & $PythonExe $tempScriptPath @ScriptArgs
        if ($LASTEXITCODE -ne 0) {
            throw ("sqlite helper failed: {0}" -f (($output | Out-String).Trim()))
        }
        $json = (($output | Out-String).Trim())
        if ([string]::IsNullOrWhiteSpace($json)) {
            throw "sqlite helper returned empty output."
        }
        return ($json | ConvertFrom-Json)
    } finally {
        if (Test-Path $tempScriptPath) {
            Remove-Item -Path $tempScriptPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-SqliteBackupApi {
    param(
        [string]$PythonExe,
        [string]$SourceDbPath,
        [string]$BackupDbPath
    )

    $code = @'
import json
import sqlite3
import sys
from pathlib import Path

src = Path(sys.argv[1]).resolve()
dst = Path(sys.argv[2]).resolve()

if not src.exists():
    raise SystemExit(json.dumps({"ok": False, "error": f"source_db_not_found:{src}"}))

dst.parent.mkdir(parents=True, exist_ok=True)

src_conn = sqlite3.connect(str(src))
dst_conn = sqlite3.connect(str(dst))
try:
    src_conn.backup(dst_conn)
finally:
    dst_conn.close()
    src_conn.close()

print(json.dumps({"ok": True, "source_db_path": str(src), "backup_db_path": str(dst)}))
'@

    return Invoke-SqlitePythonJson `
        -PythonExe $PythonExe `
        -Code $code `
        -ScriptArgs @($SourceDbPath, $BackupDbPath)
}

function Invoke-SqliteVerifyReport {
    param(
        [string]$PythonExe,
        [string]$DbPath,
        [string[]]$RequiredTables = @()
    )

    $requiredJoined = ""
    if ($RequiredTables -and $RequiredTables.Count -gt 0) {
        $requiredJoined = ($RequiredTables -join ",")
    }

    $code = @'
import json
import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1]).resolve()
required_raw = sys.argv[2] if len(sys.argv) > 2 else ""
required_tables = [item.strip() for item in required_raw.split(",") if item.strip()]

report = {
    "db_path": str(db_path),
    "exists": db_path.exists(),
    "required_tables": required_tables,
    "integrity_check_ok": False,
    "quick_check_ok": False,
    "missing_required_tables": [],
    "tables": [],
    "row_counts": {},
    "error": "",
}

if not db_path.exists():
    report["error"] = "db_not_found"
    print(json.dumps(report))
    raise SystemExit(0)

report["file_size_bytes"] = db_path.stat().st_size
try:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
except Exception as exc:
    report["error"] = f"open_failed:{exc}"
    print(json.dumps(report))
    raise SystemExit(0)

try:
    cur = conn.cursor()
    try:
        report["journal_mode"] = str(cur.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    except Exception:
        report["journal_mode"] = ""
    try:
        integrity = str(cur.execute("PRAGMA integrity_check").fetchone()[0]).lower()
    except Exception as exc:
        integrity = f"error:{exc}"
    try:
        quick = str(cur.execute("PRAGMA quick_check").fetchone()[0]).lower()
    except Exception as exc:
        quick = f"error:{exc}"

    report["integrity_check_result"] = integrity
    report["quick_check_result"] = quick
    report["integrity_check_ok"] = integrity == "ok"
    report["quick_check_ok"] = quick == "ok"

    tables = [row[0] for row in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    report["tables"] = tables
    report["table_count"] = len(tables)
    report["missing_required_tables"] = [t for t in required_tables if t not in tables]

    tracked = [
        "projects",
        "tasks",
        "artifacts",
        "reviews",
        "checkpoints",
        "approvals",
        "project_history",
    ]
    for table_name in tracked:
        if table_name in tables:
            count_value = cur.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            report["row_counts"][table_name] = int(count_value)
finally:
    conn.close()

print(json.dumps(report))
'@

    return Invoke-SqlitePythonJson `
        -PythonExe $PythonExe `
        -Code $code `
        -ScriptArgs @($DbPath, $requiredJoined)
}

function Save-SqliteJson {
    param(
        [object]$Payload,
        [string]$OutPath
    )

    if ([string]::IsNullOrWhiteSpace($OutPath)) {
        return
    }
    $parent = Split-Path -Parent $OutPath
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 12 | Set-Content -Path $OutPath -Encoding utf8
}

function Get-SqliteFileHashWithRetry {
    param(
        [string]$Path,
        [int]$Attempts = 8,
        [int]$DelayMs = 250
    )

    $lastError = $null
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            return (Get-FileHash -Path $Path -Algorithm SHA256).Hash
        } catch {
            $lastError = $_.Exception
            if ($attempt -lt $Attempts) {
                Start-Sleep -Milliseconds $DelayMs
            }
        }
    }
    if ($null -ne $lastError) {
        throw $lastError
    }
    throw ("Unable to hash file: {0}" -f $Path)
}
