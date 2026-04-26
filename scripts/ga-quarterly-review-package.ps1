param(
    [string]$ReliabilityManifestPath = "",
    [string]$ClosureOwnershipManifestPath = "",
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

function Resolve-Or-DiscoverManifestPath {
    param(
        [string]$RequestedPath,
        [string]$LogsRootPath,
        [string]$Filter,
        [string]$Label
    )

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        $resolved = Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot
        if (-not (Test-Path $resolved)) {
            throw ("{0} manifest path not found: {1}" -f $Label, $resolved)
        }
        return $resolved
    }

    $root = Join-Path $LogsRootPath "ga-adoption"
    if (-not (Test-Path $root)) {
        throw ("{0} discovery root not found: {1}" -f $Label, $root)
    }
    $latest = Get-ChildItem -Path $root -Recurse -File -Filter $Filter |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw ("No {0} manifest found with filter [{1}]." -f $Label, $Filter)
    }
    return $latest.FullName
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-adoption\quarterly-review-package-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-quarterly-review-package.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-quarterly-review-package.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedReliabilityPath = Resolve-Or-DiscoverManifestPath `
    -RequestedPath $ReliabilityManifestPath `
    -LogsRootPath $resolvedLogsRoot `
    -Filter "ga-quarterly-reliability-governance.manifest.json" `
    -Label "Quarterly reliability"

$resolvedClosurePath = Resolve-Or-DiscoverManifestPath `
    -RequestedPath $ClosureOwnershipManifestPath `
    -LogsRootPath $resolvedLogsRoot `
    -Filter "ga-quarterly-closure-sla-ownership.manifest.json" `
    -Label "Quarterly closure ownership"

$reliability = Read-OperatorJsonFile -Path $resolvedReliabilityPath
$closure = Read-OperatorJsonFile -Path $resolvedClosurePath

if ([string]$reliability.bundle_type -ne "phase18_quarterly_reliability_governance") {
    Write-Error ("Unsupported reliability bundle_type [{0}] in {1}" -f ([string]$reliability.bundle_type), $resolvedReliabilityPath)
    exit 1
}
if ([string]$closure.bundle_type -ne "phase18_quarterly_closure_sla_ownership") {
    Write-Error ("Unsupported closure ownership bundle_type [{0}] in {1}" -f ([string]$closure.bundle_type), $resolvedClosurePath)
    exit 1
}

$reliabilityDecision = ([string]$reliability.summary.quarterly_decision).Trim().ToLowerInvariant()
$closureDecision = ([string]$closure.summary.quarterly_closure_decision).Trim().ToLowerInvariant()
$reviewDecision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]

if ($reliabilityDecision -eq "escalate" -or $closureDecision -eq "escalate") {
    $reviewDecision = "escalate"
    $decisionReasons.Add("Escalation signal exists in quarterly reliability or closure ownership package.") | Out-Null
} elseif ($reliabilityDecision -eq "watch" -or $closureDecision -eq "watch") {
    $reviewDecision = "watch"
    $decisionReasons.Add("Watch-level signal exists in quarterly reliability or closure ownership package.") | Out-Null
} else {
    $decisionReasons.Add("Quarterly reliability and closure ownership packages both indicate go state.") | Out-Null
}

$ownerCommitments = @($closure.details.owner_commitments)
$atRiskOwners = @($ownerCommitments | Where-Object { ([string]$_.commitment_status).Trim().ToLowerInvariant() -ne "on_track" })

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_reliability_manifest_path = $resolvedReliabilityPath
    source_closure_manifest_path = $resolvedClosurePath
    reliability_quarterly_decision = $reliabilityDecision
    closure_quarterly_decision = $closureDecision
    quarterly_review_decision = $reviewDecision
    reliability_health_score_average = Convert-OperatorToInt -Value $reliability.summary.reliability_health_score_average -Default 0
    carry_over_action_count = Convert-OperatorToInt -Value $closure.summary.carry_over_action_count -Default 0
    owner_commitment_count = $ownerCommitments.Count
    owner_at_risk_count = $atRiskOwners.Count
    quarterly_review_decision_reasons = @($decisionReasons.ToArray())
}

Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase18_quarterly_review_package"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        reliability_manifest_path = $resolvedReliabilityPath
        closure_ownership_manifest_path = $resolvedClosurePath
    }
    details = [ordered]@{
        owner_commitments = $ownerCommitments
        at_risk_owners = $atRiskOwners
        decision_next_steps = @(
            "1) if quarterly_review_decision=escalate, run immediate owner remediation and track ETA in closure ownership loop.",
            "2) if quarterly_review_decision=watch, schedule targeted runbook-delta hardening before next monthly cycle close.",
            "3) rerun quarterly review package after monthly governance updates and compare decision drift."
        )
    }
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-quarterly-review-package.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Quarterly Review Package") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- reliability_quarterly_decision: {0}" -f [string]$summary.reliability_quarterly_decision)) | Out-Null
$lines.Add(("- closure_quarterly_decision: {0}" -f [string]$summary.closure_quarterly_decision)) | Out-Null
$lines.Add(("- quarterly_review_decision: {0}" -f [string]$summary.quarterly_review_decision)) | Out-Null
$lines.Add(("- reliability_health_score_average: {0}" -f [int]$summary.reliability_health_score_average)) | Out-Null
$lines.Add(("- carry_over_action_count: {0}" -f [int]$summary.carry_over_action_count)) | Out-Null
$lines.Add(("- owner_at_risk_count: {0}" -f [int]$summary.owner_at_risk_count)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Decision reasons") | Out-Null
foreach ($reason in @($summary.quarterly_review_decision_reasons)) {
    $lines.Add(("- {0}" -f [string]$reason)) | Out-Null
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

Write-Host "[done] ga quarterly review package completed"
Write-Host ("  review_manifest  : {0}" -f $OutPath)
Write-Host ("  review_summary   : {0}" -f $SummaryOutPath)
Write-Host ("  review_decision  : {0}" -f [string]$summary.quarterly_review_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive          : {0}" -f $archiveOutputPath)
}
