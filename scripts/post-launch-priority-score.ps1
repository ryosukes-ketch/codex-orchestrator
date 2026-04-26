param(
    [string]$TriageManifestPath = "",
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$ScoringDocPath = "docs/post_launch_priority_scoring.md"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-TriageManifestPath {
    param([string]$RequestedPath)

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot)
    }

    $latest = Get-ChildItem -Path (Join-Path $repoRoot "logs\post-launch-ops") -Recurse -File -Filter "post-launch-triage.manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw "No post-launch triage manifest found under logs/post-launch-ops."
    }
    return $latest.FullName
}

function Get-ImpactWeight {
    param([string]$PriorityHint)

    $priority = ([string]$PriorityHint).Trim().ToUpperInvariant()
    switch ($priority) {
        "P1" { return 3 }
        "P2" { return 2 }
        default { return 1 }
    }
}

function Get-BucketWeight {
    param([string]$Bucket)

    $bucket = ([string]$Bucket).Trim().ToLowerInvariant()
    switch ($bucket) {
        "release_backlog" { return 3 }
        "product_backlog" { return 2 }
        "runbook_backlog" { return 2 }
        default { return 1 }
    }
}

function Get-ScoreTier {
    param([int]$Score)

    if ($Score -ge 15) { return "High" }
    if ($Score -ge 8) { return "Medium" }
    return "Low"
}

$resolvedTriagePath = Resolve-TriageManifestPath -RequestedPath $TriageManifestPath
if (-not (Test-Path $resolvedTriagePath)) {
    Write-Error ("Triage manifest not found: {0}" -f $resolvedTriagePath)
    exit 1
}

$triage = Read-OperatorJsonFile -Path $resolvedTriagePath
if ([string]$triage.bundle_type -ne "phase13_post_launch_issue_triage") {
    Write-Error "Unexpected triage manifest bundle_type."
    exit 1
}

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\post-launch-ops\post-launch-priority-score-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "post-launch-priority-score.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

$scoredItems = New-Object System.Collections.Generic.List[object]
$tierCounts = [ordered]@{ High = 0; Medium = 0; Low = 0 }

$ranked = @($triage.triage_items) | ForEach-Object {
    $freq = Convert-OperatorToInt -Value $_.source_signal_count -Default 0
    $bundle = Convert-OperatorToInt -Value $_.source_bundle_count -Default 0
    $impactWeight = Get-ImpactWeight -PriorityHint ([string]$_.priority_hint)
    $bucketWeight = Get-BucketWeight -Bucket ([string]$_.backlog_bucket)
    $score = ($freq * 2) + ($bundle * 2) + ($impactWeight * 3) + $bucketWeight
    [pscustomobject]@{
        triage = $_
        score = $score
        tier = (Get-ScoreTier -Score $score)
    }
} | Sort-Object -Property @{Expression = { $_.score }; Descending = $true }, @{Expression = { [string]$_.triage.triage_id }; Descending = $false }

$rank = 1
foreach ($entry in $ranked) {
    $tier = [string]$entry.tier
    if (-not $tierCounts.Contains($tier)) {
        $tierCounts[$tier] = 0
    }
    $tierCounts[$tier] = [int]$tierCounts[$tier] + 1

    $scoredItems.Add([ordered]@{
        rank = $rank
        triage_id = [string]$entry.triage.triage_id
        source_action_id = [string]$entry.triage.source_action_id
        category = [string]$entry.triage.category
        backlog_bucket = [string]$entry.triage.backlog_bucket
        priority_hint = [string]$entry.triage.priority_hint
        score = [int]$entry.score
        tier = $tier
        decision = [string]$entry.triage.decision
        rationale = [string]$entry.triage.rationale
        source_signal_count = Convert-OperatorToInt -Value $entry.triage.source_signal_count -Default 0
        source_bundle_count = Convert-OperatorToInt -Value $entry.triage.source_bundle_count -Default 0
    }) | Out-Null
    $rank += 1
}

$payload = [ordered]@{
    bundle_type = "phase13_post_launch_priority_scoring"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_triage_manifest_path = $resolvedTriagePath
    scored_item_count = $scoredItems.Count
    tier_counts = $tierCounts
    scored_items = @($scoredItems.ToArray())
    scoring_formula = [ordered]@{
        score = "(source_signal_count*2) + (source_bundle_count*2) + (impact_weight*3) + bucket_weight"
        impact_weight = [ordered]@{ P1 = 3; P2 = 2; P3 = 1 }
        bucket_weight = [ordered]@{ release_backlog = 3; product_backlog = 2; runbook_backlog = 2; monitoring_only = 1 }
        tier_thresholds = [ordered]@{ High = ">=15"; Medium = ">=8"; Low = "<8" }
    }
    next_steps = @(
        "1) Route scored items into known-issue flow and release candidate queues.",
        "2) Treat High-tier release_backlog items as hotfix review candidates.",
        "3) Re-score after each trend/hardening refresh window."
    )
}

Save-OperatorJson -Payload $payload -OutPath $OutPath

$reportMarkdownPath = Join-Path $resolvedOutputDir "post-launch-priority-score.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Post-Launch Priority Scoring") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
$lines.Add(("- source_triage_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedTriagePath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- scored_item_count: {0}" -f $payload.scored_item_count)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Tier counts") | Out-Null
foreach ($entry in $tierCounts.GetEnumerator()) {
    $lines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
}
$lines.Add("") | Out-Null
$lines.Add("## Top scored items") | Out-Null
foreach ($item in @($scoredItems.ToArray() | Select-Object -First 10)) {
    $lines.Add(("- rank={0} {1} [{2}] score={3} tier={4}" -f [int]$item.rank, [string]$item.triage_id, [string]$item.category, [int]$item.score, [string]$item.tier)) | Out-Null
}
[System.IO.File]::WriteAllLines($reportMarkdownPath, $lines, [System.Text.Encoding]::UTF8)

if (-not [string]::IsNullOrWhiteSpace($ScoringDocPath)) {
    $resolvedDocPath = Resolve-OperatorAbsolutePath -Path $ScoringDocPath -BasePath $repoRoot
    $docLines = New-Object System.Collections.Generic.List[string]
    $docLines.Add("# Post-Launch Priority Scoring (Phase 13 / p13_t2)") | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Purpose") | Out-Null
    $docLines.Add("Apply deterministic priority scoring to post-launch triage outputs for backlog and release governance decisions.") | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Latest metadata") | Out-Null
    $docLines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
    $docLines.Add(("- scoring_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
    $docLines.Add(("- source_triage_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedTriagePath -RootPath $repoRoot))) | Out-Null
    $docLines.Add(("- scored_item_count: {0}" -f $payload.scored_item_count)) | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Tier counts") | Out-Null
    foreach ($entry in $tierCounts.GetEnumerator()) {
        $docLines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
    }
    $docLines.Add("") | Out-Null
    $docLines.Add("## Formula") | Out-Null
    $docLines.Add(("- {0}" -f [string]$payload.scoring_formula.score)) | Out-Null
    [System.IO.File]::WriteAllLines($resolvedDocPath, $docLines, [System.Text.Encoding]::UTF8)
}

Write-Host "[done] post-launch priority scoring completed"
Write-Host ("  triage_manifest  : {0}" -f $resolvedTriagePath)
Write-Host ("  scored_items     : {0}" -f $scoredItems.Count)
Write-Host ("  manifest         : {0}" -f $OutPath)
Write-Host ("  report_markdown  : {0}" -f $reportMarkdownPath)
if (-not [string]::IsNullOrWhiteSpace($ScoringDocPath)) {
    Write-Host ("  scoring_doc      : {0}" -f (Resolve-OperatorAbsolutePath -Path $ScoringDocPath -BasePath $repoRoot))
}
