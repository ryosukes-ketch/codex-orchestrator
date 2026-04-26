param(
    [switch]$Once,
    [switch]$SkipRemoteSchedules
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }

$args = @("-m", "app.macro_pulser.main", "live")
if ($Once) { $args += "--once" }
if ($SkipRemoteSchedules) { $args += "--skip-remote-schedules" }

& $pythonExe @args
