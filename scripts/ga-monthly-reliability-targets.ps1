param(
    [string]$LogsRoot = "logs",
    [int]$WindowDays = 30,
    [string[]]$WeeklyManifestPaths = @(),
    [string[]]$RoutingManifestPaths = @(),
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [int]$ClosureSlaP1Days = 7,
    [int]$ClosureSlaP2Days = 14,
    [int]$ClosureSlaP3Days = 30,
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
if ($ClosureSlaP1Days -lt 1 -or $ClosureSlaP2Days -lt 1 -or $ClosureSlaP3Days -lt 1) {
    Write-Error "Closure SLA day thresholds must be >= 1."
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

function Parse-UtcOrDefault {
    param(
        [string]$Value,
        [DateTime]$DefaultUtc
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $DefaultUtc
    }
    try {
        return ([DateTime]::Parse($Value).ToUniversalTime())
    } catch {
        return $DefaultUtc
    }
}

function Resolve-WeeklyManifestList {
    param(
        [string[]]$RequestedPaths,
        [string]$LogsRootPath,
        [DateTime]$WindowStartUtc,
        [DateTime]$WindowEndUtc
    )

    $explicit = @(
        @($RequestedPaths) |
            Where-Object { -not [string]::IsNullOrWhiteSpace(([string]$_).Trim()) }
    )
    if ($explicit.Count -gt 0) {
        return $explicit
    }

    $weeklyRoot = Join-Path $LogsRootPath "ga-adoption"
    if (-not (Test-Path $weeklyRoot)) {
        return @()
    }

    $resolved = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in Get-ChildItem -Path $weeklyRoot -Recurse -File -Filter "ga-weekly-reliability-review.manifest.json") {
        $payload = $null
        try {
            $payload = Read-OperatorJsonFile -Path $candidate.FullName
        } catch {
            continue
        }

        $generatedAtUtc = Parse-UtcOrDefault -Value ([string]$payload.generated_at_utc) -DefaultUtc $candidate.LastWriteTimeUtc
        if ($generatedAtUtc -lt $WindowStartUtc -or $generatedAtUtc -gt $WindowEndUtc) {
            continue
        }
        $resolved.Add($candidate.FullName) | Out-Null
    }

    return @($resolved.ToArray())
}

function Resolve-RoutingManifestList {
    param(
        [string[]]$RequestedPaths,
        [string]$LogsRootPath,
        [DateTime]$WindowStartUtc,
        [DateTime]$WindowEndUtc
    )

    $explicit = @(
        @($RequestedPaths) |
            Where-Object { -not [string]::IsNullOrWhiteSpace(([string]$_).Trim()) }
    )
    if ($explicit.Count -gt 0) {
        return $explicit
    }

    $gaLaunchRoot = Join-Path $LogsRootPath "ga-launch"
    if (-not (Test-Path $gaLaunchRoot)) {
        return @()
    }

    $resolved = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in Get-ChildItem -Path $gaLaunchRoot -Recurse -File -Filter "hotfix-next-release-route.manifest.json") {
        $payload = $null
        try {
            $payload = Read-OperatorJsonFile -Path $candidate.FullName
        } catch {
            continue
        }
        if ([string]$payload.bundle_type -ne "phase15_hotfix_next_release_routing") {
            continue
        }

        $generatedAtUtc = Parse-UtcOrDefault -Value ([string]$payload.generated_at_utc) -DefaultUtc $candidate.LastWriteTimeUtc
        if ($generatedAtUtc -lt $WindowStartUtc -or $generatedAtUtc -gt $WindowEndUtc) {
            continue
        }
        $resolved.Add($candidate.FullName) | Out-Null
    }
    return @($resolved.ToArray())
}

function Get-SlaDaysForPriority {
    param(
        [string]$Priority,
        [int]$P1Days,
        [int]$P2Days,
        [int]$P3Days
    )

    $normalized = ([string]$Priority).Trim().ToUpperInvariant()
    if ($normalized -eq "P1") { return $P1Days }
    if ($normalized -eq "P2") { return $P2Days }
    return $P3Days
}

function Get-AgingBucket {
    param([int]$AgeDays)

    if ($AgeDays -le 7) { return "le_7_days" }
    if ($AgeDays -le 14) { return "d8_14_days" }
    if ($AgeDays -le 30) { return "d15_30_days" }
    return "gt_30_days"
}

function Get-KnownIssuesSnapshot {
    param([string]$Path)

    $default = [ordered]@{
        total = 0
        open = 0
        mitigated = 0
        resolved = 0
        accepted_risk = 0
    }
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path)) {
        return $default
    }

    $lines = Get-Content -Path $Path
    foreach ($line in $lines) {
        $trimmed = ([string]$line).Trim()
        if (-not $trimmed.StartsWith("|")) {
            continue
        }
        if ($trimmed -match "^\|\s*-") {
            continue
        }
        if ($trimmed -match "^\|\s*Issue ID\s*\|") {
            continue
        }
        $parts = $trimmed.Split("|")
        if ($parts.Length -lt 5) {
            continue
        }
        $status = ([string]$parts[4]).Trim().ToLowerInvariant()
        if ([string]::IsNullOrWhiteSpace($status)) {
            continue
        }
        $default.total = [int]$default.total + 1
        if ($default.Contains($status)) {
            $default[$status] = [int]$default[$status] + 1
        }
    }
    return $default
}

function Get-PreviousMonthlySummaryPath {
    param(
        [string]$LogsRootPath,
        [string]$CurrentSummaryPath
    )

    $monthlyRoot = Join-Path $LogsRootPath "ga-adoption"
    if (-not (Test-Path $monthlyRoot)) {
        return ""
    }

    $currentResolved = Resolve-OperatorAbsolutePath -Path $CurrentSummaryPath -BasePath $repoRoot
    $latest = Get-ChildItem -Path $monthlyRoot -Recurse -File -Filter "ga-monthly-reliability-targets.summary.json" |
        Where-Object { (Resolve-OperatorAbsolutePath -Path $_.FullName -BasePath $repoRoot) -ne $currentResolved } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        return ""
    }
    return $latest.FullName
}

$windowEndUtc = [DateTime]::UtcNow
$windowStartUtc = $windowEndUtc.AddDays(-1 * $WindowDays)

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-adoption\monthly-targets-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-monthly-reliability-targets.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-monthly-reliability-targets.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedKnownIssuesPath = Resolve-OperatorAbsolutePath -Path $KnownIssuesPath -BasePath $repoRoot
$requestedWeeklyPaths = Resolve-OptionalArrayPaths -InputPaths $WeeklyManifestPaths -BasePath $repoRoot
$requestedRoutingPaths = Resolve-OptionalArrayPaths -InputPaths $RoutingManifestPaths -BasePath $repoRoot

$weeklyManifestPaths = Resolve-WeeklyManifestList `
    -RequestedPaths $requestedWeeklyPaths `
    -LogsRootPath $resolvedLogsRoot `
    -WindowStartUtc $windowStartUtc `
    -WindowEndUtc $windowEndUtc
if (@($weeklyManifestPaths).Count -eq 0) {
    Write-Error "No weekly reliability manifests were found in the requested window."
    exit 1
}

$routingManifestPaths = Resolve-RoutingManifestList `
    -RequestedPaths $requestedRoutingPaths `
    -LogsRootPath $resolvedLogsRoot `
    -WindowStartUtc $windowStartUtc `
    -WindowEndUtc $windowEndUtc

$weeklyManifestEntries = New-Object System.Collections.Generic.List[object]
$routingManifestEntries = New-Object System.Collections.Generic.List[object]
$topCategoryCounts = @{}
$hardeningOpenActions = New-Object System.Collections.Generic.List[object]
$recommendationCounts = [ordered]@{
    urgent_hardening_cycle = 0
    targeted_hardening_cycle = 0
    monitor_only_cycle = 0
}
$routingSummary = [ordered]@{
    routed_item_count = 0
    hotfix_candidate_count = 0
    next_release_candidate_count = 0
    monitoring_only_count = 0
    deferred_count = 0
}

$weeklyReviewCount = 0
$supportBundleCountTotal = 0
$topRecurringCategoryCountTotal = 0
$hardeningActionCountTotal = 0
$p1HardeningActionCountTotal = 0
$schemaIssueCountTotal = 0

foreach ($path in @($weeklyManifestPaths)) {
    $resolvedPath = Resolve-OperatorAbsolutePath -Path $path -BasePath $repoRoot
    if (-not (Test-Path $resolvedPath)) {
        Write-Error ("Weekly manifest path not found: {0}" -f $resolvedPath)
        exit 1
    }
    $payload = Read-OperatorJsonFile -Path $resolvedPath
    if ([string]$payload.bundle_type -ne "phase16_ga_weekly_reliability_review") {
        Write-Error ("Unsupported weekly bundle_type [{0}] in {1}" -f ([string]$payload.bundle_type), $resolvedPath)
        exit 1
    }

    $generatedAtUtc = Parse-UtcOrDefault -Value ([string]$payload.generated_at_utc) -DefaultUtc (Get-Item $resolvedPath).LastWriteTimeUtc
    if ($generatedAtUtc -lt $windowStartUtc -or $generatedAtUtc -gt $windowEndUtc) {
        continue
    }

    $weeklyReviewCount += 1
    $summary = $payload.summary
    $supportBundleCountTotal += Convert-OperatorToInt -Value $summary.support_bundle_count -Default 0
    $topRecurringCategoryCountTotal += Convert-OperatorToInt -Value $summary.top_recurring_category_count -Default 0
    $hardeningActionCountTotal += Convert-OperatorToInt -Value $summary.hardening_action_count -Default 0
    $p1HardeningActionCountTotal += Convert-OperatorToInt -Value $summary.p1_hardening_action_count -Default 0
    $schemaIssueCountTotal += Convert-OperatorToInt -Value $summary.schema_issue_count -Default 0

    $recommendation = ([string]$summary.recommendation).Trim().ToLowerInvariant()
    if (-not $recommendationCounts.Contains($recommendation)) {
        $recommendationCounts[$recommendation] = 0
    }
    $recommendationCounts[$recommendation] = [int]$recommendationCounts[$recommendation] + 1

    foreach ($category in @($payload.details.top_recurring_categories)) {
        $name = ([string]$category.category).Trim().ToLowerInvariant()
        if ([string]::IsNullOrWhiteSpace($name)) {
            continue
        }
        if (-not $topCategoryCounts.Contains($name)) {
            $topCategoryCounts[$name] = 0
        }
        $topCategoryCounts[$name] = [int]$topCategoryCounts[$name] + (Convert-OperatorToInt -Value $category.total_occurrences -Default 0)
    }

    foreach ($action in @($payload.details.hardening_actions)) {
        $status = ([string]$action.status).Trim().ToLowerInvariant()
        if ([string]::IsNullOrWhiteSpace($status)) {
            $status = "planned"
        }
        $closed = @("done", "closed", "resolved", "completed", "mitigated") -contains $status
        if ($closed) {
            continue
        }

        $priority = ([string]$action.priority).Trim().ToUpperInvariant()
        if ([string]::IsNullOrWhiteSpace($priority)) {
            $priority = "P3"
        }
        $slaDays = Get-SlaDaysForPriority `
            -Priority $priority `
            -P1Days $ClosureSlaP1Days `
            -P2Days $ClosureSlaP2Days `
            -P3Days $ClosureSlaP3Days
        $ageDays = [int][Math]::Floor(($windowEndUtc - $generatedAtUtc).TotalDays)
        if ($ageDays -lt 0) {
            $ageDays = 0
        }

        $hardeningOpenActions.Add([ordered]@{
            action_id = [string]$action.action_id
            category = [string]$action.category
            priority = $priority
            status = $status
            owner = "unassigned"
            observed_at_utc = $generatedAtUtc.ToString("o")
            age_days = $ageDays
            sla_days = $slaDays
            overdue = ($ageDays -gt $slaDays)
            runbook_delta = [string]$action.runbook_delta
        }) | Out-Null
    }

    $weeklyManifestEntries.Add([ordered]@{
        path = $resolvedPath
        generated_at_utc = $generatedAtUtc.ToString("o")
        recommendation = $recommendation
    }) | Out-Null
}

if ($weeklyReviewCount -eq 0) {
    Write-Error "No weekly reliability manifests fell within the requested window."
    exit 1
}

foreach ($path in @($routingManifestPaths)) {
    $resolvedPath = Resolve-OperatorAbsolutePath -Path $path -BasePath $repoRoot
    if (-not (Test-Path $resolvedPath)) {
        continue
    }
    $payload = Read-OperatorJsonFile -Path $resolvedPath
    if ([string]$payload.bundle_type -ne "phase15_hotfix_next_release_routing") {
        continue
    }
    $generatedAtUtc = Parse-UtcOrDefault -Value ([string]$payload.generated_at_utc) -DefaultUtc (Get-Item $resolvedPath).LastWriteTimeUtc
    if ($generatedAtUtc -lt $windowStartUtc -or $generatedAtUtc -gt $windowEndUtc) {
        continue
    }

    $summary = $payload.summary
    $routingSummary.routed_item_count += Convert-OperatorToInt -Value $summary.routed_item_count -Default 0
    $routingSummary.hotfix_candidate_count += Convert-OperatorToInt -Value $summary.hotfix_candidate_count -Default 0
    $routingSummary.next_release_candidate_count += Convert-OperatorToInt -Value $summary.next_release_candidate_count -Default 0
    $routingSummary.monitoring_only_count += Convert-OperatorToInt -Value $summary.monitoring_only_count -Default 0
    $routingSummary.deferred_count += Convert-OperatorToInt -Value $summary.deferred_count -Default 0

    $routingManifestEntries.Add([ordered]@{
        path = $resolvedPath
        generated_at_utc = $generatedAtUtc.ToString("o")
    }) | Out-Null
}

$knownIssueSnapshot = Get-KnownIssuesSnapshot -Path $resolvedKnownIssuesPath
$previousSummaryPath = Get-PreviousMonthlySummaryPath -LogsRootPath $resolvedLogsRoot -CurrentSummaryPath $SummaryOutPath
$knownIssueDelta = [ordered]@{
    previous_summary_path = $previousSummaryPath
    open_delta = $null
    mitigated_delta = $null
    resolved_delta = $null
    accepted_risk_delta = $null
}
if (-not [string]::IsNullOrWhiteSpace($previousSummaryPath) -and (Test-Path $previousSummaryPath)) {
    try {
        $previousSummary = Read-OperatorJsonFile -Path $previousSummaryPath
        $prevKnown = $previousSummary.known_issue_snapshot
        $knownIssueDelta.open_delta = ($knownIssueSnapshot.open - (Convert-OperatorToInt -Value $prevKnown.open -Default 0))
        $knownIssueDelta.mitigated_delta = ($knownIssueSnapshot.mitigated - (Convert-OperatorToInt -Value $prevKnown.mitigated -Default 0))
        $knownIssueDelta.resolved_delta = ($knownIssueSnapshot.resolved - (Convert-OperatorToInt -Value $prevKnown.resolved -Default 0))
        $knownIssueDelta.accepted_risk_delta = ($knownIssueSnapshot.accepted_risk - (Convert-OperatorToInt -Value $prevKnown.accepted_risk -Default 0))
    } catch {
        $knownIssueDelta.previous_summary_path = ""
    }
}

$agingBuckets = [ordered]@{
    le_7_days = 0
    d8_14_days = 0
    d15_30_days = 0
    gt_30_days = 0
}
$overdueTotal = 0
$overdueP1 = 0
foreach ($item in @($hardeningOpenActions.ToArray())) {
    $bucket = Get-AgingBucket -AgeDays (Convert-OperatorToInt -Value $item.age_days -Default 0)
    $agingBuckets[$bucket] = [int]$agingBuckets[$bucket] + 1
    if (Convert-OperatorToBool -Value $item.overdue -Default $false) {
        $overdueTotal += 1
        if (([string]$item.priority).ToUpperInvariant() -eq "P1") {
            $overdueP1 += 1
        }
    }
}

$categoryRows = @(
    $topCategoryCounts.GetEnumerator() |
        Sort-Object -Property @{Expression = { [int]$_.Value }; Descending = $true }, @{Expression = { [string]$_.Key }; Descending = $false } |
        Select-Object -First 10 |
        ForEach-Object {
            [ordered]@{
                category = [string]$_.Key
                total_occurrences = [int]$_.Value
            }
        }
)

$decisionReasons = New-Object System.Collections.Generic.List[string]
$decision = "go"
if ($overdueP1 -gt 0) {
    $decision = "escalate"
    $decisionReasons.Add("P1 closure SLA overdue items detected.") | Out-Null
}
if ([int]$recommendationCounts.urgent_hardening_cycle -gt 0) {
    $decision = "escalate"
    $decisionReasons.Add("Urgent weekly hardening cycle recommendation detected.") | Out-Null
}
if ($decision -ne "escalate") {
    if ($overdueTotal -gt 0) {
        $decision = "watch"
        $decisionReasons.Add("Open hardening actions exceeded closure SLA threshold.") | Out-Null
    }
    if ([int]$recommendationCounts.targeted_hardening_cycle -ge 2) {
        $decision = "watch"
        $decisionReasons.Add("Targeted hardening recommendations repeated across the monthly window.") | Out-Null
    }
}
if ($decisionReasons.Count -eq 0) {
    $decisionReasons.Add("No urgent or overdue reliability risk detected in the monthly window.") | Out-Null
}

$penalty = 0
$penalty += [int]$recommendationCounts.urgent_hardening_cycle * 15
$penalty += [int]$recommendationCounts.targeted_hardening_cycle * 5
$penalty += $overdueP1 * 20
$penalty += $overdueTotal * 5
$penalty += [Math]::Min(20, $knownIssueSnapshot.open * 2)
$healthScore = [Math]::Max(0, 100 - $penalty)

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    analysis_window_utc = [ordered]@{
        start = $windowStartUtc.ToString("o")
        end = $windowEndUtc.ToString("o")
        days = $WindowDays
    }
    weekly_review_count = $weeklyReviewCount
    support_bundle_count_total = $supportBundleCountTotal
    top_recurring_category_count_total = $topRecurringCategoryCountTotal
    top_recurring_category_unique_count = $categoryRows.Count
    hardening_action_count_total = $hardeningActionCountTotal
    p1_hardening_action_count_total = $p1HardeningActionCountTotal
    schema_issue_count_total = $schemaIssueCountTotal
    recommendation_counts = $recommendationCounts
    routing_summary = $routingSummary
    known_issue_snapshot = $knownIssueSnapshot
    known_issue_delta = $knownIssueDelta
    closure_sla = [ordered]@{
        thresholds_days = [ordered]@{
            P1 = $ClosureSlaP1Days
            P2 = $ClosureSlaP2Days
            P3 = $ClosureSlaP3Days
        }
        open_action_count = $hardeningOpenActions.Count
        overdue_action_count = $overdueTotal
        overdue_p1_count = $overdueP1
        unresolved_aging_buckets = $agingBuckets
    }
    reliability_health_score = $healthScore
    monthly_decision = $decision
    monthly_decision_reasons = @($decisionReasons.ToArray())
}

Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase17_ga_monthly_reliability_target_package"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        logs_root = $resolvedLogsRoot
        known_issues_path = $resolvedKnownIssuesPath
        weekly_reliability_manifests = @($weeklyManifestEntries.ToArray())
        routing_manifests = @($routingManifestEntries.ToArray())
    }
    details = [ordered]@{
        top_recurring_categories = $categoryRows
        closure_sla_open_actions = @($hardeningOpenActions.ToArray())
        decision_next_steps = @(
            "1) if monthly_decision=escalate, execute P1 closure owner assignment within one business day",
            "2) if monthly_decision=watch, schedule targeted runbook-delta updates before next monthly cycle",
            "3) rerun ga-monthly-reliability-targets.ps1 after weekly review close and compare known issue delta drift"
        )
    }
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-monthly-reliability-targets.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Monthly Reliability Targets") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- analysis_window_utc: {0} -> {1}" -f $summary.analysis_window_utc.start, $summary.analysis_window_utc.end)) | Out-Null
$lines.Add(("- weekly_review_count: {0}" -f [int]$summary.weekly_review_count)) | Out-Null
$lines.Add(("- support_bundle_count_total: {0}" -f [int]$summary.support_bundle_count_total)) | Out-Null
$lines.Add(("- hardening_action_count_total: {0}" -f [int]$summary.hardening_action_count_total)) | Out-Null
$lines.Add(("- closure_sla_overdue_action_count: {0}" -f [int]$summary.closure_sla.overdue_action_count)) | Out-Null
$lines.Add(("- reliability_health_score: {0}" -f [int]$summary.reliability_health_score)) | Out-Null
$lines.Add(("- monthly_decision: {0}" -f [string]$summary.monthly_decision)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Recommendation counts") | Out-Null
$lines.Add(("- urgent_hardening_cycle: {0}" -f [int]$summary.recommendation_counts.urgent_hardening_cycle)) | Out-Null
$lines.Add(("- targeted_hardening_cycle: {0}" -f [int]$summary.recommendation_counts.targeted_hardening_cycle)) | Out-Null
$lines.Add(("- monitor_only_cycle: {0}" -f [int]$summary.recommendation_counts.monitor_only_cycle)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Routing summary") | Out-Null
$lines.Add(("- hotfix_candidate_count: {0}" -f [int]$summary.routing_summary.hotfix_candidate_count)) | Out-Null
$lines.Add(("- next_release_candidate_count: {0}" -f [int]$summary.routing_summary.next_release_candidate_count)) | Out-Null
$lines.Add(("- monitoring_only_count: {0}" -f [int]$summary.routing_summary.monitoring_only_count)) | Out-Null
$lines.Add(("- deferred_count: {0}" -f [int]$summary.routing_summary.deferred_count)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Known issue snapshot") | Out-Null
$lines.Add(("- open: {0}" -f [int]$summary.known_issue_snapshot.open)) | Out-Null
$lines.Add(("- mitigated: {0}" -f [int]$summary.known_issue_snapshot.mitigated)) | Out-Null
$lines.Add(("- resolved: {0}" -f [int]$summary.known_issue_snapshot.resolved)) | Out-Null
$lines.Add(("- accepted_risk: {0}" -f [int]$summary.known_issue_snapshot.accepted_risk)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Top recurring categories") | Out-Null
if ($categoryRows.Count -eq 0) {
    $lines.Add("- none") | Out-Null
} else {
    foreach ($row in $categoryRows) {
        $lines.Add(("- {0}: total_occurrences={1}" -f [string]$row.category, [int]$row.total_occurrences)) | Out-Null
    }
}
$lines.Add("") | Out-Null
$lines.Add("## Decision reasons") | Out-Null
foreach ($reason in @($summary.monthly_decision_reasons)) {
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

Write-Host "[done] ga monthly reliability targets package completed"
Write-Host ("  monthly_manifest : {0}" -f $OutPath)
Write-Host ("  monthly_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision         : {0}" -f [string]$summary.monthly_decision)
Write-Host ("  health_score     : {0}" -f [int]$summary.reliability_health_score)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive          : {0}" -f $archiveOutputPath)
}
