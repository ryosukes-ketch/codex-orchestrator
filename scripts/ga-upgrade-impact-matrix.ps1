param(
    [string]$QuarterlyReviewManifestPath = "",
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
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

function Resolve-Or-DiscoverQuarterlyReviewManifest {
    param(
        [string]$RequestedPath,
        [string]$LogsRootPath
    )

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        $resolved = Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot
        if (-not (Test-Path $resolved)) {
            throw ("Quarterly review manifest path not found: {0}" -f $resolved)
        }
        return $resolved
    }

    $root = Join-Path $LogsRootPath "ga-adoption"
    if (-not (Test-Path $root)) {
        throw ("Quarterly review discovery root not found: {0}" -f $root)
    }

    $latest = Get-ChildItem -Path $root -Recurse -File -Filter "ga-quarterly-review-package.manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw "No quarterly review package manifest found."
    }
    return $latest.FullName
}

function Get-KnownIssueStatusCounts {
    param([string]$KnownIssuesFilePath)

    $counts = [ordered]@{
        open = 0
        mitigated = 0
        resolved = 0
    }

    if (-not (Test-Path $KnownIssuesFilePath)) {
        return $counts
    }

    foreach ($line in [System.IO.File]::ReadAllLines($KnownIssuesFilePath)) {
        if ($line -notmatch "\|\s*KI-") {
            continue
        }
        $normalized = $line.ToLowerInvariant()
        if ($normalized -match "\|\s*open\s*\|") {
            $counts.open = [int]$counts.open + 1
        } elseif ($normalized -match "\|\s*mitigated\s*\|") {
            $counts.mitigated = [int]$counts.mitigated + 1
        } elseif ($normalized -match "\|\s*resolved\s*\|") {
            $counts.resolved = [int]$counts.resolved + 1
        }
    }

    return $counts
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-upgrade\impact-matrix-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-upgrade-impact-matrix.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-upgrade-impact-matrix.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedQuarterlyReviewPath = Resolve-Or-DiscoverQuarterlyReviewManifest `
    -RequestedPath $QuarterlyReviewManifestPath `
    -LogsRootPath $resolvedLogsRoot

$resolvedKnownIssuesPath = Resolve-OperatorAbsolutePath -Path $KnownIssuesPath -BasePath $repoRoot
$quarterlyReview = Read-OperatorJsonFile -Path $resolvedQuarterlyReviewPath
if ([string]$quarterlyReview.bundle_type -ne "phase18_quarterly_review_package") {
    Write-Error ("Unsupported quarterly review bundle_type [{0}] in {1}" -f ([string]$quarterlyReview.bundle_type), $resolvedQuarterlyReviewPath)
    exit 1
}

$quarterlyDecision = ([string]$quarterlyReview.summary.quarterly_review_decision).Trim().ToLowerInvariant()
$ownerAtRiskCount = Convert-OperatorToInt -Value $quarterlyReview.summary.owner_at_risk_count -Default 0
$carryOverActionCount = Convert-OperatorToInt -Value $quarterlyReview.summary.carry_over_action_count -Default 0
$knownIssueCounts = Get-KnownIssueStatusCounts -KnownIssuesFilePath $resolvedKnownIssuesPath

$impactLaneCounts = [ordered]@{
    safe_patch = 0
    guarded_upgrade = 0
    rollback_sensitive = 0
    data_protection_required = 1
}

if ($quarterlyDecision -eq "go" -and $ownerAtRiskCount -eq 0 -and $carryOverActionCount -eq 0) {
    $impactLaneCounts.safe_patch = 1
} elseif ($quarterlyDecision -eq "watch") {
    $impactLaneCounts.guarded_upgrade = 1
    $impactLaneCounts.rollback_sensitive = 1
} else {
    $impactLaneCounts.guarded_upgrade = 1
    $impactLaneCounts.rollback_sensitive = 1
}

$upgradeDecision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ($quarterlyDecision -eq "escalate" -or $ownerAtRiskCount -gt 0 -or $carryOverActionCount -gt 0) {
    $upgradeDecision = "watch"
    $decisionReasons.Add("Quarterly review indicates at-risk ownership or carry-over pressure; guarded upgrade required.") | Out-Null
}
if ($knownIssueCounts.open -gt 0) {
    $upgradeDecision = "watch"
    $decisionReasons.Add("Open known issues require explicit mitigation checks before production-like upgrade rehearsal.") | Out-Null
}
if ($decisionReasons.Count -eq 0) {
    $decisionReasons.Add("Quarterly governance signals stable baseline for controlled upgrade planning.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_quarterly_review_manifest_path = $resolvedQuarterlyReviewPath
    known_issues_path = $resolvedKnownIssuesPath
    quarterly_review_decision = $quarterlyDecision
    owner_at_risk_count = $ownerAtRiskCount
    carry_over_action_count = $carryOverActionCount
    known_issue_status_counts = $knownIssueCounts
    impact_lane_counts = $impactLaneCounts
    upgrade_impact_decision = $upgradeDecision
    upgrade_impact_decision_reasons = @($decisionReasons.ToArray())
}

Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase19_upgrade_impact_matrix"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        quarterly_review_manifest_path = $resolvedQuarterlyReviewPath
        known_issues_path = $resolvedKnownIssuesPath
    }
    details = [ordered]@{
        impact_lanes = @(
            [ordered]@{
                lane = "safe_patch"
                count = [int]$impactLaneCounts.safe_patch
                intent = "Proceed with low-risk patch package under standard rollback guard."
            },
            [ordered]@{
                lane = "guarded_upgrade"
                count = [int]$impactLaneCounts.guarded_upgrade
                intent = "Require rehearsal package before rollout."
            },
            [ordered]@{
                lane = "rollback_sensitive"
                count = [int]$impactLaneCounts.rollback_sensitive
                intent = "Require restore/verify checkpoints before approval."
            },
            [ordered]@{
                lane = "data_protection_required"
                count = [int]$impactLaneCounts.data_protection_required
                intent = "Require sqlite backup/export before migration or update operation."
            }
        )
        next_steps = @(
            "1) run ga-migration-rehearsal-package.ps1 with this impact matrix as input.",
            "2) run ga-upgrade-rollback-safety.ps1 before any upgrade package decision.",
            "3) include upgrade impact summary in quarterly review evidence closure."
        )
    }
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-upgrade-impact-matrix.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Upgrade Impact Matrix") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- quarterly_review_decision: {0}" -f [string]$summary.quarterly_review_decision)) | Out-Null
$lines.Add(("- owner_at_risk_count: {0}" -f [int]$summary.owner_at_risk_count)) | Out-Null
$lines.Add(("- carry_over_action_count: {0}" -f [int]$summary.carry_over_action_count)) | Out-Null
$lines.Add(("- upgrade_impact_decision: {0}" -f [string]$summary.upgrade_impact_decision)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Known issue status counts") | Out-Null
$lines.Add(("- open: {0}" -f [int]$summary.known_issue_status_counts.open)) | Out-Null
$lines.Add(("- mitigated: {0}" -f [int]$summary.known_issue_status_counts.mitigated)) | Out-Null
$lines.Add(("- resolved: {0}" -f [int]$summary.known_issue_status_counts.resolved)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Decision reasons") | Out-Null
foreach ($reason in @($summary.upgrade_impact_decision_reasons)) {
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

Write-Host "[done] ga upgrade impact matrix completed"
Write-Host ("  impact_manifest  : {0}" -f $OutPath)
Write-Host ("  impact_summary   : {0}" -f $SummaryOutPath)
Write-Host ("  impact_decision  : {0}" -f [string]$summary.upgrade_impact_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive          : {0}" -f $archiveOutputPath)
}
