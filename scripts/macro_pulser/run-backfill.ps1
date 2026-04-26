param(
    [Parameter(Mandatory = $true)][string]$FromUtc,
    [Parameter(Mandatory = $true)][string]$ToUtc
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }

& $pythonExe -m app.macro_pulser.main backfill --from $FromUtc --to $ToUtc
