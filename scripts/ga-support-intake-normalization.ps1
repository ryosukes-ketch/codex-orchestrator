param(
    [string]$LogsRoot = "logs",
    [int]$WindowDays = 30,
    [string[]]$SupportIntakeManifestPaths = @(),
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = "",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

if ($WindowDays -lt 1) {
    Write-Error "-WindowDays must be >= 1."
    exit 1
}

function Resolve-OptionalArrayPaths {
    param(
        [string[]]$InputPaths,
        [string]$BasePath
    )

    $resolved = New-Object System.Collections.Generic.List[string]
    foreach ($value in @($InputPaths)) {
        $trimmed = ([string]$value).Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }
        $resolved.Add((Resolve-OperatorAbsolutePath -Path $trimmed -BasePath $BasePath)) | Out-Null
    }
    return @($resolved.ToArray())
}

function Resolve-SupportIntakeManifestList {
    param(
        [string[]]$RequestedPaths,
        [string]$LogsRootPath,
        [DateTime]$WindowStartUtc
    )

    $explicitPaths = @($RequestedPaths | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
    if ($explicitPaths.Count -gt 0) {
        return $explicitPaths
    }

    $selfServeRoot = Join-Path $LogsRootPath "self-serve"
    if (-not (Test-Path $selfServeRoot)) {
        return @()
    }

    $resolved = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in Get-ChildItem -Path $selfServeRoot -Recurse -File -Filter "support-intake.manifest.json") {
        if ($candidate.LastWriteTimeUtc -lt $WindowStartUtc) {
            continue
        }
        $resolved.Add($candidate.FullName) | Out-Null
    }
    return @($resolved.ToArray())
}

function Add-ToCountMap {
    param(
        [hashtable]$Map,
        [string]$Key,
        [int]$Value
    )

    $normalizedKey = ([string]$Key).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($normalizedKey)) {
        return
    }
    if (-not $Map.ContainsKey($normalizedKey)) {
        $Map[$normalizedKey] = 0
    }
    $Map[$normalizedKey] = [int]$Map[$normalizedKey] + $Value
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$windowEndUtc = [DateTime]::UtcNow
$windowStartUtc = $windowEndUtc.AddDays(-1 * $WindowDays)

$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-ops\support-intake-normalization-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-support-intake-normalization.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-support-intake-normalization.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$requestedPaths = Resolve-OptionalArrayPaths -InputPaths $SupportIntakeManifestPaths -BasePath $repoRoot
$manifestPaths = Resolve-SupportIntakeManifestList `
    -RequestedPaths $requestedPaths `
    -LogsRootPath $resolvedLogsRoot `
    -WindowStartUtc $windowStartUtc
$manifestPaths = @($manifestPaths | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })

if (@($manifestPaths).Count -eq 0) {
    Write-Error "No support intake manifests found in the requested window."
    exit 1
}

$requiredFields = @(
    "support_bundle_manifest_path",
    "failure_classification_json_path",
    "required_attachments",
    "classification_status",
    "finding_count"
)

$categoryCounts = @{}
$severityCounts = @{}
$statusCounts = @{}
$sourceEntries = New-Object System.Collections.Generic.List[object]
$blockingCount = 0
$findingCountTotal = 0
$missingRequiredFieldCount = 0

foreach ($path in @($manifestPaths)) {
    if (-not (Test-Path $path)) {
        Write-Error ("Support intake manifest not found: {0}" -f $path)
        exit 1
    }
    $payload = Read-OperatorJsonFile -Path $path
    if ([string]$payload.bundle_type -ne "self_serve_support_intake_manifest") {
        Write-Error ("Unsupported support intake bundle_type [{0}] in {1}" -f ([string]$payload.bundle_type), $path)
        exit 1
    }

    $status = ([string]$payload.classification_status).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($status)) {
        $status = "unknown"
        $missingRequiredFieldCount += 1
    }
    Add-ToCountMap -Map $statusCounts -Key $status -Value 1

    $hasBlocking = Convert-OperatorToBool -Value $payload.has_blocking_findings -Default $false
    if ($hasBlocking) {
        $blockingCount += 1
    }
    $findingCount = Convert-OperatorToInt -Value $payload.finding_count -Default 0
    $findingCountTotal += $findingCount

    foreach ($entry in @($payload.category_counts.PSObject.Properties)) {
        Add-ToCountMap -Map $categoryCounts -Key $entry.Name -Value (Convert-OperatorToInt -Value $entry.Value -Default 0)
    }
    foreach ($entry in @($payload.severity_counts.PSObject.Properties)) {
        Add-ToCountMap -Map $severityCounts -Key $entry.Name -Value (Convert-OperatorToInt -Value $entry.Value -Default 0)
    }

    foreach ($field in @($requiredFields)) {
        $value = Get-OperatorObjectPropertyValue -Object $payload -Name $field
        if ($null -eq $value) {
            $missingRequiredFieldCount += 1
            continue
        }
        if ($value -is [string] -and [string]::IsNullOrWhiteSpace([string]$value)) {
            $missingRequiredFieldCount += 1
        }
        if ($value -is [System.Collections.IEnumerable] -and -not ($value -is [string])) {
            if (@($value).Count -eq 0) {
                $missingRequiredFieldCount += 1
            }
        }
    }

    $sourceEntries.Add([ordered]@{
        manifest_path = $path
        generated_at_utc = [string]$payload.generated_at_utc
        classification_status = $status
        has_blocking_findings = $hasBlocking
        finding_count = $findingCount
    }) | Out-Null
}

$decision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ($missingRequiredFieldCount -gt 0) {
    $decision = "escalate"
    $decisionReasons.Add("Support intake manifests are missing required normalization fields.") | Out-Null
} elseif ($blockingCount -gt 0) {
    $decision = "watch"
    $decisionReasons.Add("Blocking findings exist in support intake manifests; monitor routing capacity.") | Out-Null
} else {
    $decisionReasons.Add("Support intake manifests are normalized and non-blocking in the selected window.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    analysis_window_utc = [ordered]@{
        start = $windowStartUtc.ToString("o")
        end = $windowEndUtc.ToString("o")
        days = $WindowDays
    }
    support_intake_manifest_count = @($manifestPaths).Count
    blocking_manifest_count = $blockingCount
    finding_count_total = $findingCountTotal
    missing_required_field_count = $missingRequiredFieldCount
    normalization_decision = $decision
    normalization_decision_reasons = @($decisionReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase20_support_intake_normalization"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        required_fields = $requiredFields
        classification_status_counts = $statusCounts
        category_counts = $categoryCounts
        severity_counts = $severityCounts
        source_manifests = @($sourceEntries.ToArray())
        next_steps = @(
            "1) if normalization_decision=escalate, fix missing intake fields before support-at-scale rollout.",
            "2) if normalization_decision=watch, prioritize blocking categories in support routing.",
            "3) include normalization summary in environment/support closeout package."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-support-intake-normalization.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Support Intake Normalization") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- support_intake_manifest_count: {0}" -f [int]$summary.support_intake_manifest_count)) | Out-Null
$lines.Add(("- blocking_manifest_count: {0}" -f [int]$summary.blocking_manifest_count)) | Out-Null
$lines.Add(("- finding_count_total: {0}" -f [int]$summary.finding_count_total)) | Out-Null
$lines.Add(("- missing_required_field_count: {0}" -f [int]$summary.missing_required_field_count)) | Out-Null
$lines.Add(("- normalization_decision: {0}" -f [string]$summary.normalization_decision)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga support intake normalization completed"
Write-Host ("  normalization_manifest : {0}" -f $OutPath)
Write-Host ("  normalization_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision               : {0}" -f [string]$summary.normalization_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive                : {0}" -f $archiveOutputPath)
}
