param(
    [string]$PriorityManifestPath = "",
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$RoutingDocPath = "docs/known_issue_routing.md"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-PriorityManifestPath {
    param([string]$RequestedPath)

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot)
    }

    $latest = Get-ChildItem -Path (Join-Path $repoRoot "logs\post-launch-ops") -Recurse -File -Filter "post-launch-priority-score.manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw "No post-launch priority-score manifest found under logs/post-launch-ops."
    }
    return $latest.FullName
}

function Get-KnownIssueStatusHints {
    param([string]$Content)

    $counts = [ordered]@{ open = 0; mitigated = 0; resolved = 0; accepted_risk = 0 }
    foreach ($line in $Content -split "`n") {
        $trimmed = $line.Trim()
        if ($trimmed -notlike "| KI-*") {
            continue
        }
        if ($trimmed -match "\|\s*(open|mitigated|resolved|accepted_risk)\s*\|") {
            $status = $Matches[1].Trim().ToLowerInvariant()
            if ($counts.Contains($status)) {
                $counts[$status] = [int]$counts[$status] + 1
            }
        }
    }
    return $counts
}

function Get-RouteDecision {
    param(
        [string]$Tier,
        [string]$BacklogBucket,
        [string]$Category,
        [int]$AcceptedRiskCount
    )

    $tier = ([string]$Tier).Trim().ToLowerInvariant()
    $bucket = ([string]$BacklogBucket).Trim().ToLowerInvariant()
    $category = ([string]$Category).Trim().ToLowerInvariant()

    if ($bucket -eq "monitoring_only") {
        if ($AcceptedRiskCount -gt 0) {
            return "defer_accepted_risk"
        }
        return "monitor_only"
    }

    if ($tier -eq "high") {
        if ($category -eq "runtime" -or $category -eq "provider_auth" -or $category -eq "persistence_restore") {
            return "hotfix_candidate"
        }
        return "next_release_candidate"
    }

    if ($bucket -eq "runbook_backlog") {
        return "runbook_patch"
    }

    if ($tier -eq "medium") {
        return "next_release_candidate"
    }

    return "monitor_only"
}

$resolvedPriorityPath = Resolve-PriorityManifestPath -RequestedPath $PriorityManifestPath
if (-not (Test-Path $resolvedPriorityPath)) {
    Write-Error ("Priority manifest not found: {0}" -f $resolvedPriorityPath)
    exit 1
}

$priority = Read-OperatorJsonFile -Path $resolvedPriorityPath
if ([string]$priority.bundle_type -ne "phase13_post_launch_priority_scoring") {
    Write-Error "Unexpected priority manifest bundle_type."
    exit 1
}

$knownIssuesPath = Resolve-OperatorAbsolutePath -Path $KnownIssuesPath -BasePath $repoRoot
$knownIssuesContent = if (Test-Path $knownIssuesPath) { Get-Content -Raw -Path $knownIssuesPath } else { "" }
$knownIssueHints = Get-KnownIssueStatusHints -Content $knownIssuesContent
$acceptedRiskCount = Convert-OperatorToInt -Value $knownIssueHints.accepted_risk -Default 0

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\post-launch-ops\known-issue-routing-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "known-issue-routing.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

$routeCounts = [ordered]@{
    monitor_only = 0
    runbook_patch = 0
    hotfix_candidate = 0
    next_release_candidate = 0
    defer_accepted_risk = 0
}
$routingItems = New-Object System.Collections.Generic.List[object]

foreach ($item in @($priority.scored_items)) {
    $route = Get-RouteDecision `
        -Tier ([string]$item.tier) `
        -BacklogBucket ([string]$item.backlog_bucket) `
        -Category ([string]$item.category) `
        -AcceptedRiskCount $acceptedRiskCount

    if (-not $routeCounts.Contains($route)) {
        $routeCounts[$route] = 0
    }
    $routeCounts[$route] = [int]$routeCounts[$route] + 1

    $routingItems.Add([ordered]@{
        triage_id = [string]$item.triage_id
        category = [string]$item.category
        score = Convert-OperatorToInt -Value $item.score -Default 0
        tier = [string]$item.tier
        backlog_bucket = [string]$item.backlog_bucket
        route = $route
        route_rationale = ("tier={0} bucket={1} category={2}" -f [string]$item.tier, [string]$item.backlog_bucket, [string]$item.category)
    }) | Out-Null
}

$payload = [ordered]@{
    bundle_type = "phase13_known_issue_routing"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_priority_manifest_path = $resolvedPriorityPath
    source_known_issues_path = $knownIssuesPath
    known_issue_status_hints = $knownIssueHints
    routed_item_count = $routingItems.Count
    route_counts = $routeCounts
    routing_items = @($routingItems.ToArray())
    next_steps = @(
        "1) Promote hotfix_candidate and next_release_candidate items into release backlog package.",
        "2) Apply runbook_patch items as bounded doc updates.",
        "3) Keep monitor_only/defer items in known-issue review cadence."
    )
}

Save-OperatorJson -Payload $payload -OutPath $OutPath

$reportMarkdownPath = Join-Path $resolvedOutputDir "known-issue-routing.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Known Issue Routing") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
$lines.Add(("- source_priority_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedPriorityPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- routed_item_count: {0}" -f $payload.routed_item_count)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Route counts") | Out-Null
foreach ($entry in $routeCounts.GetEnumerator()) {
    $lines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
}
[System.IO.File]::WriteAllLines($reportMarkdownPath, $lines, [System.Text.Encoding]::UTF8)

if (-not [string]::IsNullOrWhiteSpace($RoutingDocPath)) {
    $resolvedDocPath = Resolve-OperatorAbsolutePath -Path $RoutingDocPath -BasePath $repoRoot
    $docLines = New-Object System.Collections.Generic.List[string]
    $docLines.Add("# Known Issue Routing (Phase 13 / p13_t3)") | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Purpose") | Out-Null
    $docLines.Add("Route scored post-launch issues into monitor/runbook/hotfix/release/defer decisions with deterministic criteria.") | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Latest metadata") | Out-Null
    $docLines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
    $docLines.Add(("- routing_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
    $docLines.Add(("- source_priority_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedPriorityPath -RootPath $repoRoot))) | Out-Null
    $docLines.Add(("- routed_item_count: {0}" -f $payload.routed_item_count)) | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Route counts") | Out-Null
    foreach ($entry in $routeCounts.GetEnumerator()) {
        $docLines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
    }
    [System.IO.File]::WriteAllLines($resolvedDocPath, $docLines, [System.Text.Encoding]::UTF8)
}

Write-Host "[done] known issue routing completed"
Write-Host ("  priority_manifest : {0}" -f $resolvedPriorityPath)
Write-Host ("  routed_items      : {0}" -f $routingItems.Count)
Write-Host ("  manifest          : {0}" -f $OutPath)
Write-Host ("  report_markdown   : {0}" -f $reportMarkdownPath)
if (-not [string]::IsNullOrWhiteSpace($RoutingDocPath)) {
    Write-Host ("  routing_doc       : {0}" -f (Resolve-OperatorAbsolutePath -Path $RoutingDocPath -BasePath $repoRoot))
}
