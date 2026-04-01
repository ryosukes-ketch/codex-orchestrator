param(
    [switch]$ApiOnly,
    [switch]$NoRuff
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$ruffExe = Join-Path $repoRoot ".venv\Scripts\ruff.exe"

if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }
if (-not (Test-Path $ruffExe)) { $ruffExe = "ruff" }

$pytestArgs = @("-m", "pytest", "-q")
if ($ApiOnly) {
    $pytestArgs += "tests/test_api.py"
}

& $pythonExe @pytestArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $NoRuff) {
    & $ruffExe "check" "."
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
