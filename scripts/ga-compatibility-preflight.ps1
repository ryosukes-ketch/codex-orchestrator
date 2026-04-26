param(
    [string]$EnvironmentMatrixManifestPath = "",
    [string]$ReadinessManifestPath = "",
    [string]$LogsRoot = "logs",
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = "",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-LatestManifestPath {
    param(
        [string]$SearchRoot,
        [string]$Filter
    )

    if (-not (Test-Path $SearchRoot)) {
        return ""
    }
    $latest = Get-ChildItem -Path $SearchRoot -Recurse -File -Filter $Filter |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        return ""
    }
    return $latest.FullName
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-ops\compat-preflight-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-compatibility-preflight.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-compatibility-preflight.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedMatrixPath = ([string]$EnvironmentMatrixManifestPath).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedMatrixPath)) {
    $resolvedMatrixPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $resolvedLogsRoot "ga-ops") `
        -Filter "ga-supported-environment-matrix.manifest.json"
}
if ([string]::IsNullOrWhiteSpace($resolvedMatrixPath)) {
    $resolvedMatrixPath = Join-Path $resolvedOutputDir "ga-supported-environment-matrix.manifest.json"
    & (Join-Path $PSScriptRoot "ga-supported-environment-matrix.ps1") `
        -OutputDir $resolvedOutputDir `
        -OutPath $resolvedMatrixPath `
        -SummaryOutPath (Join-Path $resolvedOutputDir "ga-supported-environment-matrix.summary.json")
}
if (-not [System.IO.Path]::IsPathRooted($resolvedMatrixPath)) {
    $resolvedMatrixPath = Resolve-OperatorAbsolutePath -Path $resolvedMatrixPath -BasePath $repoRoot
}
if (-not (Test-Path $resolvedMatrixPath)) {
    Write-Error ("Environment matrix manifest not found: {0}" -f $resolvedMatrixPath)
    exit 1
}

$resolvedReadinessPath = ([string]$ReadinessManifestPath).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedReadinessPath)) {
    $resolvedReadinessPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $resolvedLogsRoot "operational-readiness") `
        -Filter "readiness-manifest-*.json"
}
if (-not [string]::IsNullOrWhiteSpace($resolvedReadinessPath) -and -not [System.IO.Path]::IsPathRooted($resolvedReadinessPath)) {
    $resolvedReadinessPath = Resolve-OperatorAbsolutePath -Path $resolvedReadinessPath -BasePath $repoRoot
}

$matrix = Read-OperatorJsonFile -Path $resolvedMatrixPath
if ([string]$matrix.bundle_type -ne "phase20_supported_environment_matrix") {
    Write-Error ("Unsupported matrix bundle_type [{0}] in {1}" -f ([string]$matrix.bundle_type), $resolvedMatrixPath)
    exit 1
}

$isWindowsOs = $env:OS -eq "Windows_NT"
$psMajor = Convert-OperatorToInt -Value $PSVersionTable.PSVersion.Major -Default 0
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
$pythonVersion = ""
$pythonReady = $false
if ($null -ne $pythonCmd) {
    try {
        $pythonVersion = (& python -V 2>&1 | Select-Object -First 1)
        $pythonReady = $true
    } catch {
        $pythonReady = $false
    }
}

$requiredScripts = @(
    "scripts\self-serve-preflight.ps1",
    "scripts\self-serve-support-intake.ps1",
    "scripts\sqlite-backup.ps1",
    "scripts\sqlite-restore.ps1",
    "scripts\release-readiness.ps1"
)
$missingScripts = New-Object System.Collections.Generic.List[string]
foreach ($relative in $requiredScripts) {
    $path = Resolve-OperatorAbsolutePath -Path $relative -BasePath $repoRoot
    if (-not (Test-Path $path)) {
        $missingScripts.Add($relative) | Out-Null
    }
}

$readinessDecision = ""
if (-not [string]::IsNullOrWhiteSpace($resolvedReadinessPath) -and (Test-Path $resolvedReadinessPath)) {
    try {
        $readinessManifest = Read-OperatorJsonFile -Path $resolvedReadinessPath
        $readinessDecision = ([string]$readinessManifest.summary.readiness_decision).Trim().ToUpperInvariant()
    } catch {
        $readinessDecision = ""
    }
}

$checkResults = @(
    [ordered]@{
        check = "windows_os"
        passed = $isWindowsOs
        details = "Expected Windows_NT for current support matrix baseline."
        required = $true
    },
    [ordered]@{
        check = "powershell_major_gte_5"
        passed = ($psMajor -ge 5)
        details = ("Detected PowerShell major version: {0}" -f $psMajor)
        required = $true
    },
    [ordered]@{
        check = "python_available"
        passed = $pythonReady
        details = ("Detected python version output: {0}" -f $pythonVersion)
        required = $true
    },
    [ordered]@{
        check = "required_scripts_present"
        passed = ($missingScripts.Count -eq 0)
        details = ("Missing scripts: {0}" -f (@($missingScripts.ToArray()) -join ","))
        required = $true
    },
    [ordered]@{
        check = "latest_readiness_decision_go"
        passed = ($readinessDecision -eq "" -or $readinessDecision -eq "GO")
        details = ("Latest readiness decision: {0}" -f $readinessDecision)
        required = $false
    }
)

$failedRequired = @($checkResults | Where-Object { $_.required -and -not $_.passed }).Count
$failedOptional = @($checkResults | Where-Object { (-not $_.required) -and -not $_.passed }).Count
$decision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ($failedRequired -gt 0) {
    $decision = "escalate"
    $decisionReasons.Add("One or more required compatibility checks failed.") | Out-Null
} elseif ($failedOptional -gt 0) {
    $decision = "watch"
    $decisionReasons.Add("Optional compatibility checks failed; monitor before broader rollout.") | Out-Null
} else {
    $decisionReasons.Add("All required compatibility checks passed.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    matrix_manifest_path = $resolvedMatrixPath
    readiness_manifest_path = $resolvedReadinessPath
    required_check_count = @($checkResults | Where-Object { $_.required }).Count
    optional_check_count = @($checkResults | Where-Object { -not $_.required }).Count
    failed_required_check_count = $failedRequired
    failed_optional_check_count = $failedOptional
    compatibility_decision = $decision
    compatibility_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase20_compatibility_preflight_report"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        check_results = $checkResults
        missing_scripts = @($missingScripts.ToArray())
        expected_supported_environment_count = Convert-OperatorToInt -Value $matrix.summary.supported_environment_count -Default 0
        next_steps = @(
            "1) resolve required compatibility failures before support-at-scale intake expansion.",
            "2) generate support intake normalization package to validate evidence shape consistency.",
            "3) keep environment matrix synchronized with startup/readiness runbook prerequisites."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-compatibility-preflight.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Compatibility Preflight") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- compatibility_decision: {0}" -f [string]$summary.compatibility_decision)) | Out-Null
$lines.Add(("- failed_required_check_count: {0}" -f [int]$summary.failed_required_check_count)) | Out-Null
$lines.Add(("- failed_optional_check_count: {0}" -f [int]$summary.failed_optional_check_count)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Check results") | Out-Null
foreach ($entry in @($checkResults)) {
    $lines.Add(("- {0}: passed={1}, required={2}, details={3}" -f [string]$entry.check, [string]$entry.passed, [string]$entry.required, [string]$entry.details)) | Out-Null
}
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga compatibility preflight completed"
Write-Host ("  preflight_manifest : {0}" -f $OutPath)
Write-Host ("  preflight_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision           : {0}" -f [string]$summary.compatibility_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive            : {0}" -f $archiveOutputPath)
}
