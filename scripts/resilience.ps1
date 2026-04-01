param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [switch]$SkipPreflight,
    [switch]$NoRuff,
    [int]$Repeat = 2
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$ruffExe = Join-Path $repoRoot ".venv\Scripts\ruff.exe"

if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }
if (-not (Test-Path $ruffExe)) { $ruffExe = "ruff" }

if (-not $SkipPreflight) {
    Write-Host "[preflight] starting"
    & (Join-Path $repoRoot "scripts\preflight.ps1") -ApiBaseUrl $ApiBaseUrl
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$targets = @(
    "tests/test_api.py",
    "tests/test_orchestrator.py",
    "tests/test_dry_run_orchestration.py"
)

$keyword = "idempot or checkpoint or artifact or approval_requested or approvals or replanning or revision or reject or resume"

for ($i = 1; $i -le $Repeat; $i++) {
    Write-Host ("[resilience {0}/{1}] targeted pytest" -f $i, $Repeat)
    & $pythonExe "-m" "pytest" "-q" @targets "-k" $keyword
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $NoRuff) {
    Write-Host "[ruff] scripts and README"
    & $ruffExe "check" "scripts" "README.md"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "[done] resilience checks passed"
