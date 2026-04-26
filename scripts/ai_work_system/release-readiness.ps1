$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$legacyScript = Join-Path $repoRoot "scripts\release-readiness.ps1"
if (-not (Test-Path $legacyScript)) {
    throw "Legacy script not found: $legacyScript"
}

& $legacyScript @args
