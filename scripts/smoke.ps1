param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [switch]$SkipPreflight,
    [switch]$NoRuff
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$ruffExe = Join-Path $repoRoot ".venv\Scripts\ruff.exe"

if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }
if (-not (Test-Path $ruffExe)) { $ruffExe = "ruff" }

if (-not $SkipPreflight) {
    & (Join-Path $repoRoot "scripts\preflight.ps1") -ApiBaseUrl $ApiBaseUrl
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$targets = @(
    "tests/test_api.py",
    "tests/test_orchestrator.py",
    "tests/test_dry_run_orchestration.py"
)

Write-Host "[1/2] Targeted smoke pytest"
& $pythonExe "-m" "pytest" "-q" @targets
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $NoRuff) {
    Write-Host "[2/2] Ruff check for changed surfaces"
    & $ruffExe "check" "scripts" "tests" "README.md"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
