param(
    [string]$TrendManifestPath = "",
    [string]$LogsRoot = "logs",
    [int]$WindowDays = 7,
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$ReportDocPath = "docs/phase12_recurring_issue_hardening.md"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

if ($WindowDays -lt 1) {
    Write-Error "-WindowDays must be >= 1."
    exit 1
}

function Resolve-TrendManifestPath {
    param(
        [string]$RequestedPath,
        [string]$RepoRoot,
        [string]$LogsRoot,
        [int]$WindowDays
    )

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $RepoRoot)
    }

    $trendRoot = Join-Path $RepoRoot "logs\post-launch-ops"
    if (Test-Path $trendRoot) {
        $latest = Get-ChildItem -Path $trendRoot -Recurse -File -Filter "launch-week-trend.manifest.json" |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if ($null -ne $latest) {
            return $latest.FullName
        }
    }

    $bootstrapDir = Join-Path $RepoRoot ("logs\post-launch-ops\launch-week-trend-bootstrap-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
    & (Join-Path $PSScriptRoot "launch-week-trend-review.ps1") `
        -LogsRoot $LogsRoot `
        -WindowDays $WindowDays `
        -OutputDir $bootstrapDir
    if (-not $?) {
        throw "Failed to bootstrap trend manifest via launch-week-trend-review.ps1."
    }

    $bootstrapManifest = Join-Path $bootstrapDir "launch-week-trend.manifest.json"
    if (-not (Test-Path $bootstrapManifest)) {
        throw ("Bootstrap trend manifest not found: {0}" -f $bootstrapManifest)
    }
    return $bootstrapManifest
}

function Get-SignalSignature {
    param([string]$Message)

    $normalized = ([string]$Message).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return ""
    }

    $normalized = $normalized -replace "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<id>"
    $normalized = $normalized -replace "\b\d+\b", "<n>"
    $normalized = $normalized -replace "\s+", " "
    return $normalized.Trim()
}

function Get-CategoryPriority {
    param([string]$Category)

    $normalized = ([string]$Category).Trim().ToLowerInvariant()
    switch ($normalized) {
        "runtime" { return "P1" }
        "provider_auth" { return "P1" }
        "persistence_restore" { return "P1" }
        default { return "P2" }
    }
}

function Get-CategoryHardeningPlan {
    param([string]$Category)

    $normalized = ([string]$Category).Trim().ToLowerInvariant()
    switch ($normalized) {
        "runtime" {
            return [ordered]@{
                target_docs = @(
                    "docs/commercial_pilot_support_runbook.md",
                    "docs/operator_workflow_runbook.md"
                )
                script_checks = @(
                    "scripts/openclaw-gateway-check.ps1",
                    "scripts/operator-stage-report.ps1",
                    "scripts/operator-support-bundle.ps1"
                )
                runbook_delta = "Add runtime timeout/endpoint quick-isolation decision tree with command order."
            }
        }
        "provider_auth" {
            return [ordered]@{
                target_docs = @(
                    "docs/commercial_pilot_support_runbook.md",
                    "docs/known_issues_register.md"
                )
                script_checks = @(
                    "scripts/openclaw-gateway-check.ps1",
                    "scripts/openclaw-evidence-capture.ps1",
                    "scripts/operator-support-bundle.ps1"
                )
                runbook_delta = "Add provider/auth rejection matrix (credit/token/routing) with owner mapping."
            }
        }
        "policy" {
            return [ordered]@{
                target_docs = @(
                    "docs/operational_readiness_runbook.md",
                    "docs/operator_workflow_runbook.md"
                )
                script_checks = @(
                    "scripts/operator-stage-gate.ps1",
                    "scripts/operator-audit-assert.ps1",
                    "scripts/operator-support-bundle.ps1"
                )
                runbook_delta = "Strengthen strict deny reason decision tree for allowlist/auth/override mismatch branches."
            }
        }
        "semantic_output" {
            return [ordered]@{
                target_docs = @(
                    "docs/commercial_pilot_support_runbook.md",
                    "docs/operator_workflow_runbook.md"
                )
                script_checks = @(
                    "scripts/operator-stage-report.ps1",
                    "scripts/operator-audit-assert.ps1",
                    "scripts/operator-support-bundle.ps1"
                )
                runbook_delta = "Document recurring non_json/missing_required_keys containment for stage-level stabilization."
            }
        }
        "persistence_restore" {
            return [ordered]@{
                target_docs = @(
                    "docs/operational_startup_runbook.md",
                    "docs/operational_readiness_runbook.md"
                )
                script_checks = @(
                    "scripts/sqlite-verify.ps1",
                    "scripts/sqlite-backup.ps1",
                    "scripts/sqlite-restore.ps1",
                    "scripts/sqlite-export.ps1"
                )
                runbook_delta = "Add post-restore validation sequence with deterministic status/audit checks."
            }
        }
        "operator_flow" {
            return [ordered]@{
                target_docs = @(
                    "docs/operator_workflow_runbook.md",
                    "docs/commercial_pilot_support_runbook.md"
                )
                script_checks = @(
                    "scripts/operator-status.ps1",
                    "scripts/operator-audit.ps1",
                    "scripts/operator-audit-assert.ps1"
                )
                runbook_delta = "Add transition mismatch triage branch for approval and reject-replan cycles."
            }
        }
        default {
            return [ordered]@{
                target_docs = @("docs/commercial_pilot_support_runbook.md")
                script_checks = @("scripts/operator-support-bundle.ps1")
                runbook_delta = "Track uncategorized recurring failures and promote normalized signature rules."
            }
        }
    }
}

$resolvedTrendManifestPath = Resolve-TrendManifestPath `
    -RequestedPath $TrendManifestPath `
    -RepoRoot $repoRoot `
    -LogsRoot $LogsRoot `
    -WindowDays $WindowDays
if (-not (Test-Path $resolvedTrendManifestPath)) {
    Write-Error ("Trend manifest not found: {0}" -f $resolvedTrendManifestPath)
    exit 1
}

$trend = Read-OperatorJsonFile -Path $resolvedTrendManifestPath
$trendType = [string]$trend.bundle_type
if ($trendType -ne "phase12_launch_week_support_trend_review") {
    Write-Error ("Unsupported trend manifest bundle_type [{0}] for p12 hardening." -f $trendType)
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\post-launch-ops\recurring-issue-hardening-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "recurring-issue-hardening.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

$requiredCategories = @(
    "runtime",
    "provider_auth",
    "policy",
    "semantic_output",
    "persistence_restore",
    "operator_flow",
    "unknown"
)
$requiredSeverities = @("error", "warning", "info")

$signalCounts = @{}
$schemaIssues = New-Object System.Collections.Generic.List[object]
$bundleQualityRows = New-Object System.Collections.Generic.List[object]
$missingClassificationCount = 0
$unknownCategoryOccurrences = 0
$checkedBundles = 0

foreach ($sourceBundle in @($trend.source_support_bundles)) {
    $bundleManifestPath = Resolve-OperatorAbsolutePath -Path ([string]$sourceBundle.support_bundle_manifest_path) -BasePath $repoRoot
    $classificationPath = Resolve-OperatorAbsolutePath -Path ([string]$sourceBundle.failure_classification_path) -BasePath $repoRoot
    $bundleGeneratedAt = [string]$sourceBundle.generated_at_utc

    if ([string]::IsNullOrWhiteSpace($bundleManifestPath) -or -not (Test-Path $bundleManifestPath)) {
        continue
    }

    $checkedBundles += 1
    $bundleIssues = New-Object System.Collections.Generic.List[string]

    if ([string]::IsNullOrWhiteSpace($classificationPath) -or -not (Test-Path $classificationPath)) {
        $missingClassificationCount += 1
        $bundleIssues.Add("missing_failure_classification_json") | Out-Null
        $schemaIssues.Add([ordered]@{
            issue_kind = "missing_failure_classification_json"
            support_bundle_manifest_path = $bundleManifestPath
            generated_at_utc = $bundleGeneratedAt
        }) | Out-Null
        $bundleQualityRows.Add([ordered]@{
            support_bundle_manifest_path = $bundleManifestPath
            generated_at_utc = $bundleGeneratedAt
            schema_ok = $false
            issue_count = 1
            issues = @($bundleIssues.ToArray())
        }) | Out-Null
        continue
    }

    $classification = $null
    try {
        $classification = Read-OperatorJsonFile -Path $classificationPath
    } catch {
        $bundleIssues.Add("invalid_failure_classification_json") | Out-Null
        $schemaIssues.Add([ordered]@{
            issue_kind = "invalid_failure_classification_json"
            support_bundle_manifest_path = $bundleManifestPath
            failure_classification_path = $classificationPath
            generated_at_utc = $bundleGeneratedAt
        }) | Out-Null
        $bundleQualityRows.Add([ordered]@{
            support_bundle_manifest_path = $bundleManifestPath
            generated_at_utc = $bundleGeneratedAt
            schema_ok = $false
            issue_count = 1
            issues = @($bundleIssues.ToArray())
        }) | Out-Null
        continue
    }

    $categoryCounts = $classification.category_counts
    foreach ($category in $requiredCategories) {
        $value = Get-OperatorObjectPropertyValue -Object $categoryCounts -Name $category
        if ($null -eq $value) {
            $bundleIssues.Add(("missing_category_key:{0}" -f $category)) | Out-Null
        }
    }

    $severityCounts = $classification.severity_counts
    foreach ($severity in $requiredSeverities) {
        $value = Get-OperatorObjectPropertyValue -Object $severityCounts -Name $severity
        if ($null -eq $value) {
            $bundleIssues.Add(("missing_severity_key:{0}" -f $severity)) | Out-Null
        }
    }

    $unknownCount = Convert-OperatorToInt -Value (Get-OperatorObjectPropertyValue -Object $categoryCounts -Name "unknown") -Default 0
    if ($unknownCount -gt 0) {
        $unknownCategoryOccurrences += $unknownCount
    }

    $findingCount = Convert-OperatorToInt -Value $classification.finding_count -Default 0
    $actualFindingCount = @($classification.findings).Count
    if ($findingCount -ne $actualFindingCount) {
        $bundleIssues.Add("finding_count_mismatch") | Out-Null
    }

    if (@($classification.next_steps).Count -lt 3) {
        $bundleIssues.Add("next_steps_insufficient") | Out-Null
    }

    foreach ($finding in @($classification.findings)) {
        $category = ([string]$finding.category).Trim().ToLowerInvariant()
        if ([string]::IsNullOrWhiteSpace($category)) {
            $category = "unknown"
        }

        $signature = Get-SignalSignature -Message ([string]$finding.message)
        if ([string]::IsNullOrWhiteSpace($signature)) {
            continue
        }
        $key = "{0}|{1}" -f $category, $signature
        if (-not $signalCounts.ContainsKey($key)) {
            $signalCounts[$key] = [ordered]@{
                category = $category
                signature = $signature
                count = 0
            }
        }
        $signalCounts[$key].count = [int]$signalCounts[$key].count + 1
    }

    foreach ($issue in @($bundleIssues.ToArray())) {
        $schemaIssues.Add([ordered]@{
            issue_kind = $issue
            support_bundle_manifest_path = $bundleManifestPath
            failure_classification_path = $classificationPath
            generated_at_utc = $bundleGeneratedAt
        }) | Out-Null
    }

    $bundleQualityRows.Add([ordered]@{
        support_bundle_manifest_path = $bundleManifestPath
        generated_at_utc = $bundleGeneratedAt
        schema_ok = ($bundleIssues.Count -eq 0)
        issue_count = $bundleIssues.Count
        issues = @($bundleIssues.ToArray())
    }) | Out-Null
}

$recurringSignals = @(
    $signalCounts.Values |
        Where-Object { [int]$_.count -ge 2 } |
        Sort-Object -Property @{Expression = { [int]$_.count }; Descending = $true }, @{Expression = { [string]$_.category }; Descending = $false }, @{Expression = { [string]$_.signature }; Descending = $false }
)

$hardeningActions = New-Object System.Collections.Generic.List[object]
$actionIndex = 1
$seenCategories = New-Object System.Collections.Generic.HashSet[string]

foreach ($categoryCandidate in @($trend.top_recurring_categories)) {
    $category = ([string]$categoryCandidate.category).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($category)) {
        continue
    }
    if ($seenCategories.Contains($category)) {
        continue
    }
    $seenCategories.Add($category) | Out-Null

    $plan = Get-CategoryHardeningPlan -Category $category
    $hardeningActions.Add([ordered]@{
        action_id = ("P12-HARD-{0:D3}" -f $actionIndex)
        status = "planned"
        action_type = "recurring_category_hardening"
        category = $category
        priority = (Get-CategoryPriority -Category $category)
        source_signal_count = Convert-OperatorToInt -Value $categoryCandidate.total_occurrences -Default 0
        source_bundle_count = Convert-OperatorToInt -Value $categoryCandidate.impacted_bundle_count -Default 0
        runbook_delta = [string]$plan.runbook_delta
        target_docs = @($plan.target_docs)
        recommended_script_checks = @($plan.script_checks)
    }) | Out-Null
    $actionIndex += 1
}

if ($schemaIssues.Count -gt 0) {
    $hardeningActions.Add([ordered]@{
        action_id = ("P12-HARD-{0:D3}" -f $actionIndex)
        status = "planned"
        action_type = "support_evidence_schema_hardening"
        category = "support_evidence"
        priority = "P1"
        source_signal_count = $schemaIssues.Count
        source_bundle_count = @($bundleQualityRows.ToArray() | Where-Object { [int]$_.issue_count -gt 0 }).Count
        runbook_delta = "Backfill failure-classification schema checks and enforce mandatory category/severity keys in support evidence workflows."
        target_docs = @(
            "docs/commercial_pilot_support_runbook.md",
            "docs/operational_readiness_runbook.md"
        )
        recommended_script_checks = @(
            "scripts/operator-support-bundle.ps1",
            "scripts/launch-week-trend-review.ps1"
        )
    }) | Out-Null
    $actionIndex += 1
}

if ($unknownCategoryOccurrences -gt 0) {
    $hardeningActions.Add([ordered]@{
        action_id = ("P12-HARD-{0:D3}" -f $actionIndex)
        status = "planned"
        action_type = "classification_rule_hardening"
        category = "unknown"
        priority = "P2"
        source_signal_count = $unknownCategoryOccurrences
        source_bundle_count = @($bundleQualityRows.ToArray() | Where-Object { @($_.issues) -match "missing_category_key:unknown" }).Count
        runbook_delta = "Expand classification heuristics to reduce unknown-category drift for recurring support signals."
        target_docs = @(
            "docs/commercial_pilot_support_runbook.md",
            "docs/launch_week_support_trend_review.md"
        )
        recommended_script_checks = @(
            "scripts/operator-support-bundle.ps1",
            "scripts/launch-week-trend-review.ps1"
        )
    }) | Out-Null
    $actionIndex += 1
}

if ($hardeningActions.Count -eq 0) {
    $hardeningActions.Add([ordered]@{
        action_id = "P12-HARD-001"
        status = "planned"
        action_type = "baseline_monitoring"
        category = "none"
        priority = "P3"
        source_signal_count = 0
        source_bundle_count = $checkedBundles
        runbook_delta = "No recurring hardening deltas in this window; keep weekly trend review cadence and evidence schema checks."
        target_docs = @(
            "docs/launch_week_support_trend_review.md",
            "docs/launch_week_runbook_delta_backlog.md"
        )
        recommended_script_checks = @(
            "scripts/launch-week-trend-review.ps1",
            "scripts/operator-support-bundle.ps1"
        )
    }) | Out-Null
}

$payload = [ordered]@{
    bundle_type = "phase12_recurring_issue_pattern_hardening"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_trend_manifest_path = $resolvedTrendManifestPath
    analysis_window_utc = $trend.analysis_window_utc
    support_bundle_count = Convert-OperatorToInt -Value $trend.support_bundle_count -Default 0
    checked_support_bundle_count = $checkedBundles
    recurring_signal_count = $recurringSignals.Count
    recurring_signals = @($recurringSignals | Select-Object -First 10)
    evidence_quality = [ordered]@{
        missing_failure_classification_count = $missingClassificationCount
        schema_issue_count = $schemaIssues.Count
        bundles_with_schema_issues = @($bundleQualityRows.ToArray() | Where-Object { [int]$_.issue_count -gt 0 }).Count
        unknown_category_occurrences = $unknownCategoryOccurrences
    }
    bundle_quality = @($bundleQualityRows.ToArray())
    schema_issues = @($schemaIssues.ToArray())
    hardening_actions = @($hardeningActions.ToArray())
    next_steps = @(
        "1) Apply P1/P2 hardening actions to support runbooks and evidence scripts.",
        "2) Re-run launch-week trend review and recurring issue hardening after each support cycle close.",
        "3) Promote recurring candidates to known issues when recurrence thresholds hold for 2+ windows."
    )
}

Save-OperatorJson -Payload $payload -OutPath $OutPath

$reportMarkdownPath = Join-Path $resolvedOutputDir "recurring-issue-hardening.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Phase 12 Recurring Issue Pattern Hardening") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
$lines.Add(("- source_trend_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedTrendManifestPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- support_bundle_count: {0}" -f [int]$payload.support_bundle_count)) | Out-Null
$lines.Add(("- checked_support_bundle_count: {0}" -f [int]$payload.checked_support_bundle_count)) | Out-Null
$lines.Add(("- recurring_signal_count: {0}" -f [int]$payload.recurring_signal_count)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Evidence quality summary") | Out-Null
$lines.Add(("- missing_failure_classification_count: {0}" -f [int]$payload.evidence_quality.missing_failure_classification_count)) | Out-Null
$lines.Add(("- schema_issue_count: {0}" -f [int]$payload.evidence_quality.schema_issue_count)) | Out-Null
$lines.Add(("- bundles_with_schema_issues: {0}" -f [int]$payload.evidence_quality.bundles_with_schema_issues)) | Out-Null
$lines.Add(("- unknown_category_occurrences: {0}" -f [int]$payload.evidence_quality.unknown_category_occurrences)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Hardening actions") | Out-Null
foreach ($action in @($hardeningActions.ToArray())) {
    $lines.Add(("### {0} - {1}" -f [string]$action.action_id, [string]$action.action_type)) | Out-Null
    $lines.Add(("- category: {0}" -f [string]$action.category)) | Out-Null
    $lines.Add(("- priority: {0}" -f [string]$action.priority)) | Out-Null
    $lines.Add(("- source_signal_count: {0}" -f [int]$action.source_signal_count)) | Out-Null
    $lines.Add(("- source_bundle_count: {0}" -f [int]$action.source_bundle_count)) | Out-Null
    $lines.Add(("- runbook_delta: {0}" -f [string]$action.runbook_delta)) | Out-Null
    $targetDocsText = (@($action.target_docs) -join ", ")
    $scriptChecksText = (@($action.recommended_script_checks) -join ", ")
    $lines.Add(("- target_docs: {0}" -f $targetDocsText)) | Out-Null
    $lines.Add(("- recommended_script_checks: {0}" -f $scriptChecksText)) | Out-Null
    $lines.Add("") | Out-Null
}
[System.IO.File]::WriteAllLines($reportMarkdownPath, $lines, [System.Text.Encoding]::UTF8)

if (-not [string]::IsNullOrWhiteSpace($ReportDocPath)) {
    $resolvedReportDocPath = Resolve-OperatorAbsolutePath -Path $ReportDocPath -BasePath $repoRoot
    $docLines = New-Object System.Collections.Generic.List[string]
    $docLines.Add("# Recurring Issue Pattern Hardening (Phase 12 / p12_t2)") | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Purpose") | Out-Null
    $docLines.Add("Harden support-safe evidence workflows by converting recurring launch-week support signals into deterministic runbook/script hardening actions.") | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Latest hardening metadata") | Out-Null
    $docLines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
    $docLines.Add(("- source_trend_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedTrendManifestPath -RootPath $repoRoot))) | Out-Null
    $docLines.Add(("- hardening_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
    $docLines.Add(("- support_bundle_count: {0}" -f [int]$payload.support_bundle_count)) | Out-Null
    $docLines.Add(("- checked_support_bundle_count: {0}" -f [int]$payload.checked_support_bundle_count)) | Out-Null
    $docLines.Add(("- recurring_signal_count: {0}" -f [int]$payload.recurring_signal_count)) | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Evidence quality summary") | Out-Null
    $docLines.Add(("- missing_failure_classification_count: {0}" -f [int]$payload.evidence_quality.missing_failure_classification_count)) | Out-Null
    $docLines.Add(("- schema_issue_count: {0}" -f [int]$payload.evidence_quality.schema_issue_count)) | Out-Null
    $docLines.Add(("- bundles_with_schema_issues: {0}" -f [int]$payload.evidence_quality.bundles_with_schema_issues)) | Out-Null
    $docLines.Add(("- unknown_category_occurrences: {0}" -f [int]$payload.evidence_quality.unknown_category_occurrences)) | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Hardening actions (latest window)") | Out-Null
    foreach ($action in @($hardeningActions.ToArray())) {
        $docLines.Add(("- {0} [{1}] {2}" -f [string]$action.action_id, [string]$action.priority, [string]$action.runbook_delta)) | Out-Null
    }
    $docLines.Add("") | Out-Null
    $docLines.Add("## Next actions") | Out-Null
    foreach ($step in @($payload.next_steps)) {
        $docLines.Add(("- {0}" -f [string]$step)) | Out-Null
    }
    [System.IO.File]::WriteAllLines($resolvedReportDocPath, $docLines, [System.Text.Encoding]::UTF8)
}

Write-Host "[done] recurring issue pattern hardening completed"
Write-Host ("  source_trend_manifest : {0}" -f $resolvedTrendManifestPath)
Write-Host ("  checked_bundles       : {0}" -f $checkedBundles)
Write-Host ("  recurring_signals     : {0}" -f $recurringSignals.Count)
Write-Host ("  hardening_actions     : {0}" -f $hardeningActions.Count)
Write-Host ("  manifest              : {0}" -f $OutPath)
Write-Host ("  report_markdown       : {0}" -f $reportMarkdownPath)
if (-not [string]::IsNullOrWhiteSpace($ReportDocPath)) {
    Write-Host ("  report_doc            : {0}" -f (Resolve-OperatorAbsolutePath -Path $ReportDocPath -BasePath $repoRoot))
}
