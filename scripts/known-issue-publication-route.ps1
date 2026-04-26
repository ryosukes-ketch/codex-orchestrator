param(
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [string]$ReleaseDecisionManifestPath = "",
    [string]$OutputDir = "",
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-ReleaseDecisionPath {
    param([string]$RequestedPath)

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot)
    }

    $latest = Get-ChildItem -Path (Join-Path $repoRoot "logs\release-train") -Recurse -File -Filter "release-decision-package.manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        return ""
    }
    return $latest.FullName
}

function Parse-KnownIssueRows {
    param([string]$Content)

    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($line in $Content -split "`n") {
        $trimmed = $line.Trim()
        if ($trimmed -notlike "| KI-*") {
            continue
        }
        $cells = @($trimmed.Split("|")) | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
        if ($cells.Count -lt 8) {
            continue
        }
        $rows.Add([ordered]@{
            issue_id = [string]$cells[0]
            title = [string]$cells[1]
            severity = ([string]$cells[2]).ToUpperInvariant()
            status = ([string]$cells[3]).ToLowerInvariant()
            owner = [string]$cells[4]
            first_seen_utc = [string]$cells[5]
            workaround = [string]$cells[6]
            next_action = [string]$cells[7]
        }) | Out-Null
    }
    return @($rows.ToArray())
}

function Get-PublicationRoute {
    param(
        [string]$Severity,
        [string]$Status
    )

    $severityNorm = ([string]$Severity).ToUpperInvariant()
    $statusNorm = ([string]$Status).ToLowerInvariant()

    if ($statusNorm -eq "resolved") {
        return [ordered]@{
            route = "internal_only"
            publication_level = "internal"
            release_note_required = $false
            launch_blocker = $false
        }
    }
    if ($statusNorm -eq "accepted_risk") {
        return [ordered]@{
            route = "defer_internal_monitoring"
            publication_level = "internal"
            release_note_required = $false
            launch_blocker = $false
        }
    }
    if ($severityNorm -eq "P0" -and $statusNorm -eq "open") {
        return [ordered]@{
            route = "blocker_launch_hold"
            publication_level = "customer_visible"
            release_note_required = $true
            launch_blocker = $true
        }
    }
    if ($severityNorm -eq "P1" -and ($statusNorm -eq "open" -or $statusNorm -eq "mitigated")) {
        return [ordered]@{
            route = "release_note_required"
            publication_level = "customer_visible"
            release_note_required = $true
            launch_blocker = $false
        }
    }
    if ($severityNorm -eq "P2" -and $statusNorm -eq "open") {
        return [ordered]@{
            route = "operator_visible"
            publication_level = "operator_visible"
            release_note_required = $true
            launch_blocker = $false
        }
    }
    return [ordered]@{
        route = "operator_visible"
        publication_level = "operator_visible"
        release_note_required = $false
        launch_blocker = $false
    }
}

$resolvedKnownIssuesPath = Resolve-OperatorAbsolutePath -Path $KnownIssuesPath -BasePath $repoRoot
if (-not (Test-Path $resolvedKnownIssuesPath)) {
    Write-Error ("Known issues file not found: {0}" -f $resolvedKnownIssuesPath)
    exit 1
}

$resolvedDecisionPath = Resolve-ReleaseDecisionPath -RequestedPath $ReleaseDecisionManifestPath
$decisionSummary = [ordered]@{
    decision = ""
    rollback_signal = ""
    rationale = @()
}
if (-not [string]::IsNullOrWhiteSpace($resolvedDecisionPath) -and (Test-Path $resolvedDecisionPath)) {
    $decision = Read-OperatorJsonFile -Path $resolvedDecisionPath
    if ([string]$decision.bundle_type -eq "phase14_release_decision_package") {
        $decisionSummary.decision = [string]$decision.decision
        $decisionSummary.rollback_signal = [string]$decision.rollback_signal
        $decisionSummary.rationale = @(Convert-OperatorToStringArray -Value $decision.rationale)
    }
}

$knownIssueContent = Get-Content -Raw -Path $resolvedKnownIssuesPath
$knownIssueRows = Parse-KnownIssueRows -Content $knownIssueContent

$routeCounts = [ordered]@{
    internal_only = 0
    defer_internal_monitoring = 0
    operator_visible = 0
    release_note_required = 0
    blocker_launch_hold = 0
}
$publicationCounts = [ordered]@{
    internal = 0
    operator_visible = 0
    customer_visible = 0
}
$routingItems = New-Object System.Collections.Generic.List[object]

foreach ($issue in @($knownIssueRows)) {
    $route = Get-PublicationRoute -Severity ([string]$issue.severity) -Status ([string]$issue.status)
    $routeKey = [string]$route.route
    $publicationLevel = [string]$route.publication_level
    if (-not $routeCounts.Contains($routeKey)) {
        $routeCounts[$routeKey] = 0
    }
    if (-not $publicationCounts.Contains($publicationLevel)) {
        $publicationCounts[$publicationLevel] = 0
    }
    $routeCounts[$routeKey] = [int]$routeCounts[$routeKey] + 1
    $publicationCounts[$publicationLevel] = [int]$publicationCounts[$publicationLevel] + 1

    $routingItems.Add([ordered]@{
        issue_id = [string]$issue.issue_id
        severity = [string]$issue.severity
        status = [string]$issue.status
        route = $routeKey
        publication_level = $publicationLevel
        release_note_required = [bool]$route.release_note_required
        launch_blocker = [bool]$route.launch_blocker
        workaround = [string]$issue.workaround
        next_action = [string]$issue.next_action
    }) | Out-Null
}

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\release-train\known-issue-publication-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "known-issue-publication.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

$markdownPath = Join-Path $resolvedOutputDir "known-issue-publication.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Known Issue Publication Routing") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f [DateTime]::UtcNow.ToString("o"))) | Out-Null
$lines.Add(("- source_known_issues: {0}" -f (Get-OperatorRelativePath -Path $resolvedKnownIssuesPath -RootPath $repoRoot))) | Out-Null
if (-not [string]::IsNullOrWhiteSpace($resolvedDecisionPath)) {
    $lines.Add(("- source_release_decision_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedDecisionPath -RootPath $repoRoot))) | Out-Null
}
$lines.Add("") | Out-Null
$lines.Add("## Route counts") | Out-Null
foreach ($entry in $routeCounts.GetEnumerator()) {
    $lines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
}
$lines.Add("") | Out-Null
$lines.Add("## Publication levels") | Out-Null
foreach ($entry in $publicationCounts.GetEnumerator()) {
    $lines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
}
[System.IO.File]::WriteAllLines($markdownPath, $lines, [System.Text.Encoding]::UTF8)

$payload = [ordered]@{
    bundle_type = "phase14_known_issue_publication_routing"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_known_issues_path = $resolvedKnownIssuesPath
    source_release_decision_manifest_path = $resolvedDecisionPath
    decision_context = $decisionSummary
    routed_item_count = $routingItems.Count
    route_counts = $routeCounts
    publication_counts = $publicationCounts
    routing_items = @($routingItems.ToArray())
    publication_markdown_path = $markdownPath
    next_steps = @(
        "1) Merge publication routing with release notes for launch communication package.",
        "2) Include blocker_launch_hold items in go/hold/rollback review.",
        "3) Export release-train evidence bundle with decision and notes artifacts."
    )
}

Save-OperatorJson -Payload $payload -OutPath $OutPath

Write-Host "[done] known issue publication routing completed"
Write-Host ("  source_known_issues : {0}" -f $resolvedKnownIssuesPath)
Write-Host ("  routed_items        : {0}" -f $routingItems.Count)
Write-Host ("  manifest            : {0}" -f $OutPath)
