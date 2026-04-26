param(
    [string]$LogsRoot = "logs",
    [int]$WindowDays = 7,
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$TrendDocPath = "docs/launch_week_support_trend_review.md",
    [string]$BacklogDocPath = "docs/launch_week_runbook_delta_backlog.md"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

if ($WindowDays -lt 1) {
    Write-Error "-WindowDays must be >= 1."
    exit 1
}

$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
if (-not (Test-Path $resolvedLogsRoot)) {
    Write-Error ("Logs root not found: {0}" -f $resolvedLogsRoot)
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\post-launch-ops\launch-week-trend-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedOutputDir))
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

$windowEndUtc = [DateTime]::UtcNow
$windowStartUtc = $windowEndUtc.AddDays(-1 * $WindowDays)

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "launch-week-trend.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

$knownCategories = @(
    "runtime",
    "provider_auth",
    "policy",
    "semantic_output",
    "persistence_restore",
    "operator_flow",
    "unknown"
)

$aggregateCategoryCounts = [ordered]@{}
$aggregateSeverityCounts = [ordered]@{
    error = 0
    warning = 0
    info = 0
}
$categoryBundleSets = @{}
$categoryMessageCounts = @{}
foreach ($category in $knownCategories) {
    $aggregateCategoryCounts[$category] = 0
    $categoryBundleSets[$category] = New-Object System.Collections.Generic.HashSet[string]
    $categoryMessageCounts[$category] = @{}
}

$includedBundles = New-Object System.Collections.Generic.List[object]

function Add-CategoryCount {
    param(
        [string]$Category,
        [int]$Count
    )

    $normalized = ([string]$Category).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        $normalized = "unknown"
    }
    if (-not $aggregateCategoryCounts.Contains($normalized)) {
        $aggregateCategoryCounts[$normalized] = 0
        $categoryBundleSets[$normalized] = New-Object System.Collections.Generic.HashSet[string]
        $categoryMessageCounts[$normalized] = @{}
    }
    $aggregateCategoryCounts[$normalized] = [int]$aggregateCategoryCounts[$normalized] + $Count
}

function Add-SeverityCount {
    param(
        [string]$Severity,
        [int]$Count
    )

    $normalized = ([string]$Severity).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        $normalized = "info"
    }
    if (-not $aggregateSeverityCounts.Contains($normalized)) {
        $aggregateSeverityCounts[$normalized] = 0
    }
    $aggregateSeverityCounts[$normalized] = [int]$aggregateSeverityCounts[$normalized] + $Count
}

function Get-RunbookDeltaGuidance {
    param([string]$Category)

    $normalized = ([string]$Category).Trim().ToLowerInvariant()
    switch ($normalized) {
        "runtime" {
            return [ordered]@{
                first_triage = "Run openclaw-gateway-check and operator-stage-report, then capture support bundle."
                runbook_delta = "Add a timeout budget table and endpoint-health first response sequence."
                known_issue_trigger = "Promote when runtime category appears in >=2 bundles within the review window."
                target_docs = @(
                    "docs/operator_workflow_runbook.md",
                    "docs/commercial_pilot_support_runbook.md"
                )
            }
        }
        "provider_auth" {
            return [ordered]@{
                first_triage = "Check upstream rejection fields, token source, credit limits, and provider auth probe."
                runbook_delta = "Add provider/auth quick matrix with explicit remediation ownership."
                known_issue_trigger = "Promote when provider_auth count >=2 with same upstream rejection reason."
                target_docs = @(
                    "docs/commercial_pilot_support_runbook.md",
                    "docs/known_issues_register.md"
                )
            }
        }
        "policy" {
            return [ordered]@{
                first_triage = "Inspect suite-stage-gate deny_reasons and cycle audit_assert errors."
                runbook_delta = "Add strict-mode deny reason decision tree (allowlist/auth/override)."
                known_issue_trigger = "Promote when strict deny repeats in >=2 bundles with same reason family."
                target_docs = @(
                    "docs/operational_readiness_runbook.md",
                    "docs/operator_workflow_runbook.md"
                )
            }
        }
        "semantic_output" {
            return [ordered]@{
                first_triage = "Inspect stage-report failing_stages and event-level failure reasons."
                runbook_delta = "Add structured-output fallback diagnostics and stage-specific recovery tips."
                known_issue_trigger = "Promote when non_json_response or missing_required_keys recurs in >=2 bundles."
                target_docs = @(
                    "docs/operator_workflow_runbook.md",
                    "docs/commercial_pilot_support_runbook.md"
                )
            }
        }
        "persistence_restore" {
            return [ordered]@{
                first_triage = "Run sqlite-verify -> sqlite-backup -> sqlite-restore and re-run operator smoke."
                runbook_delta = "Add post-restore validation checklist with exact command order."
                known_issue_trigger = "Promote when persistence_restore appears in any blocking support bundle."
                target_docs = @(
                    "docs/operational_startup_runbook.md",
                    "docs/operational_readiness_runbook.md"
                )
            }
        }
        "operator_flow" {
            return [ordered]@{
                first_triage = "Check status transitions via operator-status/audit/audit-assert with bundle manifests."
                runbook_delta = "Add transition mismatch quick-reference for approval and reject-replan cycles."
                known_issue_trigger = "Promote when same transition mismatch repeats in >=2 bundles."
                target_docs = @(
                    "docs/operator_workflow_runbook.md",
                    "docs/commercial_pilot_support_runbook.md"
                )
            }
        }
        default {
            return [ordered]@{
                first_triage = "Collect support bundle and inspect findings manually."
                runbook_delta = "Document recurring uncategorized issue path when stable pattern appears."
                known_issue_trigger = "Promote when unknown category appears repeatedly with same message."
                target_docs = @(
                    "docs/commercial_pilot_support_runbook.md"
                )
            }
        }
    }
}

$manifestFiles = Get-ChildItem -Path $resolvedLogsRoot -Recurse -Filter "support-bundle.manifest.json" -File
foreach ($manifestFile in $manifestFiles) {
    $manifestPayload = $null
    try {
        $manifestPayload = Read-OperatorJsonFile -Path $manifestFile.FullName
    } catch {
        continue
    }

    $bundleTimeUtc = $manifestFile.LastWriteTimeUtc
    $generatedRaw = [string]$manifestPayload.generated_at_utc
    if (-not [string]::IsNullOrWhiteSpace($generatedRaw)) {
        try {
            $bundleTimeUtc = [DateTime]::Parse($generatedRaw).ToUniversalTime()
        } catch {
            $bundleTimeUtc = $manifestFile.LastWriteTimeUtc
        }
    }

    if ($bundleTimeUtc -lt $windowStartUtc -or $bundleTimeUtc -gt $windowEndUtc) {
        continue
    }

    $classPathRaw = [string]$manifestPayload.failure_classification_json_path
    if ([string]::IsNullOrWhiteSpace($classPathRaw)) {
        continue
    }
    $classPath = Resolve-OperatorAbsolutePath -Path $classPathRaw -BasePath $manifestFile.DirectoryName
    if (-not (Test-Path $classPath)) {
        continue
    }

    $classification = $null
    try {
        $classification = Read-OperatorJsonFile -Path $classPath
    } catch {
        continue
    }

    $bundleId = [string]$manifestFile.FullName
    $includedBundles.Add([ordered]@{
        support_bundle_manifest_path = $manifestFile.FullName
        failure_classification_path = $classPath
        generated_at_utc = $bundleTimeUtc.ToString("o")
        classification_status = [string]$classification.classification_status
        finding_count = Convert-OperatorToInt -Value $classification.finding_count -Default 0
    }) | Out-Null

    $categoryCounts = $classification.category_counts
    if ($null -ne $categoryCounts) {
        foreach ($prop in $categoryCounts.PSObject.Properties) {
            $category = [string]$prop.Name
            $count = Convert-OperatorToInt -Value $prop.Value -Default 0
            if ($count -le 0) {
                continue
            }
            Add-CategoryCount -Category $category -Count $count
            $normalizedCategory = $category.Trim().ToLowerInvariant()
            if ([string]::IsNullOrWhiteSpace($normalizedCategory)) {
                $normalizedCategory = "unknown"
            }
            if (-not $categoryBundleSets.ContainsKey($normalizedCategory)) {
                $categoryBundleSets[$normalizedCategory] = New-Object System.Collections.Generic.HashSet[string]
                $categoryMessageCounts[$normalizedCategory] = @{}
            }
            $categoryBundleSets[$normalizedCategory].Add($bundleId) | Out-Null
        }
    }

    $severityCounts = $classification.severity_counts
    if ($null -ne $severityCounts) {
        foreach ($prop in $severityCounts.PSObject.Properties) {
            $severity = [string]$prop.Name
            $count = Convert-OperatorToInt -Value $prop.Value -Default 0
            if ($count -gt 0) {
                Add-SeverityCount -Severity $severity -Count $count
            }
        }
    }

    foreach ($finding in @($classification.findings)) {
        $category = ([string]$finding.category).Trim().ToLowerInvariant()
        if ([string]::IsNullOrWhiteSpace($category)) {
            $category = "unknown"
        }
        if (-not $categoryMessageCounts.ContainsKey($category)) {
            $categoryMessageCounts[$category] = @{}
        }
        $message = ([string]$finding.message).Trim()
        if ([string]::IsNullOrWhiteSpace($message)) {
            continue
        }
        if (-not $categoryMessageCounts[$category].ContainsKey($message)) {
            $categoryMessageCounts[$category][$message] = 0
        }
        $categoryMessageCounts[$category][$message] = [int]$categoryMessageCounts[$category][$message] + 1
    }
}

$categoryRows = New-Object System.Collections.Generic.List[object]
foreach ($entry in $aggregateCategoryCounts.GetEnumerator()) {
    $count = Convert-OperatorToInt -Value $entry.Value -Default 0
    if ($count -le 0) {
        continue
    }
    $categoryRows.Add([ordered]@{
        category = [string]$entry.Key
        total_occurrences = $count
        impacted_bundle_count = [int]$categoryBundleSets[[string]$entry.Key].Count
    }) | Out-Null
}
$topCategories = @(
    $categoryRows.ToArray() |
        Sort-Object -Property @{Expression = { $_.total_occurrences }; Descending = $true }, @{Expression = { $_.impacted_bundle_count }; Descending = $true }, @{Expression = { $_.category }; Descending = $false } |
        Select-Object -First 3
)

$topRecurringCategories = New-Object System.Collections.Generic.List[object]
$backlogItems = New-Object System.Collections.Generic.List[object]
$knownIssueCandidates = New-Object System.Collections.Generic.List[object]
$rank = 1
foreach ($row in $topCategories) {
    $category = [string]$row.category
    $guidance = Get-RunbookDeltaGuidance -Category $category

    $signalPairs = @()
    if ($categoryMessageCounts.ContainsKey($category)) {
        $signalPairs = $categoryMessageCounts[$category].GetEnumerator() |
            Sort-Object -Property @{Expression = { [int]$_.Value }; Descending = $true }, @{Expression = { [string]$_.Key }; Descending = $false } |
            Select-Object -First 3
    }
    $commonSignals = @()
    foreach ($pair in $signalPairs) {
        $commonSignals += [ordered]@{
            message = [string]$pair.Key
            count = [int]$pair.Value
        }
    }

    $candidate = [ordered]@{
        rank = $rank
        category = $category
        total_occurrences = [int]$row.total_occurrences
        impacted_bundle_count = [int]$row.impacted_bundle_count
        first_triage = [string]$guidance.first_triage
        runbook_delta_candidate = [string]$guidance.runbook_delta
        known_issue_promotion_trigger = [string]$guidance.known_issue_trigger
        common_signals = $commonSignals
    }
    $topRecurringCategories.Add($candidate) | Out-Null

    $priority = "P2"
    if ($category -eq "runtime" -or $category -eq "provider_auth") {
        $priority = "P1"
    } elseif ($category -eq "persistence_restore") {
        $priority = "P1"
    }

    $backlogId = ("P12-BL-{0:D3}" -f $rank)
    $backlogItem = [ordered]@{
        backlog_id = $backlogId
        title = ("Launch-week runbook delta for {0}" -f $category)
        category = $category
        priority = $priority
        status = "planned"
        summary = [string]$guidance.runbook_delta
        first_triage = [string]$guidance.first_triage
        target_docs = @($guidance.target_docs)
        source_signal_count = [int]$row.total_occurrences
        source_bundle_count = [int]$row.impacted_bundle_count
    }
    $backlogItems.Add($backlogItem) | Out-Null

    if ([int]$row.impacted_bundle_count -ge 2 -or [int]$row.total_occurrences -ge 3) {
        $knownIssueCandidates.Add([ordered]@{
            category = $category
            recommendation = "promote_to_known_issue_candidate"
            rationale = ("recurring count={0}, bundles={1}" -f [int]$row.total_occurrences, [int]$row.impacted_bundle_count)
        }) | Out-Null
    }

    $rank += 1
}

$trendPayload = [ordered]@{
    bundle_type = "phase12_launch_week_support_trend_review"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    analysis_window_utc = [ordered]@{
        start = $windowStartUtc.ToString("o")
        end = $windowEndUtc.ToString("o")
        days = $WindowDays
    }
    source_logs_root = $resolvedLogsRoot
    support_bundle_count = $includedBundles.Count
    source_support_bundles = @($includedBundles.ToArray())
    aggregate_category_counts = $aggregateCategoryCounts
    aggregate_severity_counts = $aggregateSeverityCounts
    top_recurring_categories = @($topRecurringCategories.ToArray())
    runbook_delta_backlog = @($backlogItems.ToArray())
    known_issue_candidates = @($knownIssueCandidates.ToArray())
    next_steps = @(
        "1) Apply top recurring category deltas to operator/commercial support runbooks.",
        "2) Promote recurring categories to known issues when thresholds are met.",
        "3) Re-run launch-week trend review after each support-cycle close to track trend movement."
    )
}

Save-OperatorJson -Payload $trendPayload -OutPath $OutPath

$reportMarkdownPath = Join-Path $resolvedOutputDir "launch-week-trend-review.md"
$reportLines = New-Object System.Collections.Generic.List[string]
$reportLines.Add("# Launch-Week Support Trend Review") | Out-Null
$reportLines.Add("") | Out-Null
$reportLines.Add(("- generated_at_utc: {0}" -f $trendPayload.generated_at_utc)) | Out-Null
$reportLines.Add(("- analysis_window_start_utc: {0}" -f $trendPayload.analysis_window_utc.start)) | Out-Null
$reportLines.Add(("- analysis_window_end_utc: {0}" -f $trendPayload.analysis_window_utc.end)) | Out-Null
$reportLines.Add(("- support_bundle_count: {0}" -f $trendPayload.support_bundle_count)) | Out-Null
$reportLines.Add("") | Out-Null
$reportLines.Add("## Top recurring categories") | Out-Null
if ($topRecurringCategories.Count -eq 0) {
    $reportLines.Add("- no recurring categories detected in the selected window.") | Out-Null
} else {
    foreach ($item in @($topRecurringCategories.ToArray())) {
        $reportLines.Add(("- [{0}] occurrences={1} bundles={2}" -f [string]$item.category, [int]$item.total_occurrences, [int]$item.impacted_bundle_count)) | Out-Null
        $reportLines.Add(("  - first triage: {0}" -f [string]$item.first_triage)) | Out-Null
        $reportLines.Add(("  - runbook delta candidate: {0}" -f [string]$item.runbook_delta_candidate)) | Out-Null
        if (@($item.common_signals).Count -gt 0) {
            $reportLines.Add("  - common signals:") | Out-Null
            foreach ($signal in @($item.common_signals)) {
                $reportLines.Add(("    - {0} (count={1})" -f [string]$signal.message, [int]$signal.count)) | Out-Null
            }
        }
    }
}
$reportLines.Add("") | Out-Null
$reportLines.Add("## Aggregate category counts") | Out-Null
foreach ($entry in $aggregateCategoryCounts.GetEnumerator()) {
    $reportLines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
}
$reportLines.Add("") | Out-Null
$reportLines.Add("## Aggregate severity counts") | Out-Null
foreach ($entry in $aggregateSeverityCounts.GetEnumerator()) {
    $reportLines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
}
$reportLines.Add("") | Out-Null
$reportLines.Add("## Known issue promotion candidates") | Out-Null
if ($knownIssueCandidates.Count -eq 0) {
    $reportLines.Add("- none in this window") | Out-Null
} else {
    foreach ($candidate in @($knownIssueCandidates.ToArray())) {
        $reportLines.Add(("- {0}: {1} ({2})" -f [string]$candidate.category, [string]$candidate.recommendation, [string]$candidate.rationale)) | Out-Null
    }
}
$reportLines.Add("") | Out-Null
$reportLines.Add("## Source support-bundle manifests") | Out-Null
if ($includedBundles.Count -eq 0) {
    $reportLines.Add("- none in selected window") | Out-Null
} else {
    foreach ($bundle in @($includedBundles.ToArray())) {
        $relativeManifestPath = Get-OperatorRelativePath -Path ([string]$bundle.support_bundle_manifest_path) -RootPath $repoRoot
        $reportLines.Add(("- {0} ({1})" -f $relativeManifestPath, [string]$bundle.generated_at_utc)) | Out-Null
    }
}
[System.IO.File]::WriteAllLines($reportMarkdownPath, $reportLines, [System.Text.Encoding]::UTF8)

if (-not [string]::IsNullOrWhiteSpace($TrendDocPath)) {
    $resolvedTrendDocPath = Resolve-OperatorAbsolutePath -Path $TrendDocPath -BasePath $repoRoot
    $trendDocLines = New-Object System.Collections.Generic.List[string]
    $trendDocLines.Add("# Launch-Week Support Trend Review (Phase 12 / p12_t1)") | Out-Null
    $trendDocLines.Add("") | Out-Null
    $trendDocLines.Add("## Purpose") | Out-Null
    $trendDocLines.Add("Summarize launch-week support evidence for the last 7 days and produce bounded runbook delta candidates.") | Out-Null
    $trendDocLines.Add("") | Out-Null
    $trendDocLines.Add("## Latest review metadata") | Out-Null
    $trendDocLines.Add(("- generated_at_utc: {0}" -f $trendPayload.generated_at_utc)) | Out-Null
    $trendDocLines.Add(("- analysis_window_utc: {0} -> {1}" -f $trendPayload.analysis_window_utc.start, $trendPayload.analysis_window_utc.end)) | Out-Null
    $trendDocLines.Add(("- support_bundle_count: {0}" -f $trendPayload.support_bundle_count)) | Out-Null
    $trendDocLines.Add(("- trend_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
    $trendDocLines.Add("") | Out-Null
    $trendDocLines.Add("## Top recurring categories (latest window)") | Out-Null
    if ($topRecurringCategories.Count -eq 0) {
        $trendDocLines.Add("- no recurring categories detected in this window.") | Out-Null
    } else {
        foreach ($item in @($topRecurringCategories.ToArray())) {
            $trendDocLines.Add(("- [{0}] occurrences={1}, bundles={2}" -f [string]$item.category, [int]$item.total_occurrences, [int]$item.impacted_bundle_count)) | Out-Null
            $trendDocLines.Add(("  - first triage: {0}" -f [string]$item.first_triage)) | Out-Null
            $trendDocLines.Add(("  - runbook delta candidate: {0}" -f [string]$item.runbook_delta_candidate)) | Out-Null
            $trendDocLines.Add(("  - known issue trigger: {0}" -f [string]$item.known_issue_promotion_trigger)) | Out-Null
        }
    }
    $trendDocLines.Add("") | Out-Null
    $trendDocLines.Add("## Aggregate counts") | Out-Null
    foreach ($entry in $aggregateCategoryCounts.GetEnumerator()) {
        $trendDocLines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
    }
    $trendDocLines.Add("") | Out-Null
    $trendDocLines.Add("## Next actions") | Out-Null
    foreach ($step in @($trendPayload.next_steps)) {
        $trendDocLines.Add(("- {0}" -f [string]$step)) | Out-Null
    }
    [System.IO.File]::WriteAllLines($resolvedTrendDocPath, $trendDocLines, [System.Text.Encoding]::UTF8)
}

if (-not [string]::IsNullOrWhiteSpace($BacklogDocPath)) {
    $resolvedBacklogDocPath = Resolve-OperatorAbsolutePath -Path $BacklogDocPath -BasePath $repoRoot
    $backlogLines = New-Object System.Collections.Generic.List[string]
    $backlogLines.Add("# Launch-Week Runbook Delta Backlog (Phase 12 / p12_t1)") | Out-Null
    $backlogLines.Add("") | Out-Null
    $backlogLines.Add(("- generated_at_utc: {0}" -f $trendPayload.generated_at_utc)) | Out-Null
    $backlogLines.Add(("- source_trend_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
    $backlogLines.Add("") | Out-Null
    $backlogLines.Add("## Backlog items") | Out-Null
    if ($backlogItems.Count -eq 0) {
        $backlogLines.Add("- no backlog items generated for this window.") | Out-Null
    } else {
        foreach ($item in @($backlogItems.ToArray())) {
            $backlogLines.Add(("### {0} - {1}" -f [string]$item.backlog_id, [string]$item.title)) | Out-Null
            $backlogLines.Add(("- category: {0}" -f [string]$item.category)) | Out-Null
            $backlogLines.Add(("- priority: {0}" -f [string]$item.priority)) | Out-Null
            $backlogLines.Add(("- status: {0}" -f [string]$item.status)) | Out-Null
            $backlogLines.Add(("- source_signal_count: {0}" -f [int]$item.source_signal_count)) | Out-Null
            $backlogLines.Add(("- source_bundle_count: {0}" -f [int]$item.source_bundle_count)) | Out-Null
            $backlogLines.Add(("- summary: {0}" -f [string]$item.summary)) | Out-Null
            $backlogLines.Add(("- first_triage: {0}" -f [string]$item.first_triage)) | Out-Null
            $targetDocsText = (@($item.target_docs) -join ", ")
            $backlogLines.Add(("- target_docs: {0}" -f $targetDocsText)) | Out-Null
            $backlogLines.Add("") | Out-Null
        }
    }
    $backlogLines.Add("## Known-issue promotion candidates") | Out-Null
    if ($knownIssueCandidates.Count -eq 0) {
        $backlogLines.Add("- none") | Out-Null
    } else {
        foreach ($candidate in @($knownIssueCandidates.ToArray())) {
            $backlogLines.Add(("- {0}: {1} ({2})" -f [string]$candidate.category, [string]$candidate.recommendation, [string]$candidate.rationale)) | Out-Null
        }
    }
    [System.IO.File]::WriteAllLines($resolvedBacklogDocPath, $backlogLines, [System.Text.Encoding]::UTF8)
}

Write-Host "[done] launch-week support trend review completed"
Write-Host ("  logs_root            : {0}" -f $resolvedLogsRoot)
Write-Host ("  analysis_window_days : {0}" -f $WindowDays)
Write-Host ("  support_bundles      : {0}" -f $includedBundles.Count)
Write-Host ("  manifest             : {0}" -f $OutPath)
Write-Host ("  report_markdown      : {0}" -f $reportMarkdownPath)
if (-not [string]::IsNullOrWhiteSpace($TrendDocPath)) {
    Write-Host ("  trend_doc            : {0}" -f (Resolve-OperatorAbsolutePath -Path $TrendDocPath -BasePath $repoRoot))
}
if (-not [string]::IsNullOrWhiteSpace($BacklogDocPath)) {
    Write-Host ("  backlog_doc          : {0}" -f (Resolve-OperatorAbsolutePath -Path $BacklogDocPath -BasePath $repoRoot))
}
