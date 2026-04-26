param(
    [string]$RecurringHardeningManifestPath = "",
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$TriageDocPath = "docs/post_launch_issue_triage.md"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-RecurringHardeningManifestPath {
    param([string]$RequestedPath)

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot)
    }

    $latest = Get-ChildItem -Path (Join-Path $repoRoot "logs\post-launch-ops") -Recurse -File -Filter "recurring-issue-hardening.manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw "No recurring-issue-hardening manifest found under logs/post-launch-ops."
    }
    return $latest.FullName
}

function Get-BacklogBucket {
    param(
        [string]$ActionType,
        [string]$Category,
        [string]$Priority
    )

    $type = ([string]$ActionType).Trim().ToLowerInvariant()
    $cat = ([string]$Category).Trim().ToLowerInvariant()
    $pri = ([string]$Priority).Trim().ToUpperInvariant()

    if ($type -eq "baseline_monitoring" -or $cat -eq "none") {
        return "monitoring_only"
    }
    if ($type -eq "support_evidence_schema_hardening" -or $type -eq "classification_rule_hardening") {
        return "product_backlog"
    }
    if ($cat -eq "runtime" -or $cat -eq "provider_auth" -or $cat -eq "persistence_restore") {
        if ($pri -eq "P1") { return "release_backlog" }
        return "product_backlog"
    }
    if ($cat -eq "policy" -or $cat -eq "semantic_output" -or $cat -eq "operator_flow") {
        return "runbook_backlog"
    }
    return "monitoring_only"
}

function Get-KnownIssueSummary {
    param([string]$KnownIssuesContent)

    $summary = [ordered]@{
        total = 0
        open = 0
        mitigated = 0
        resolved = 0
        accepted_risk = 0
    }

    foreach ($line in $KnownIssuesContent -split "`n") {
        $trimmed = $line.Trim()
        if (-not $trimmed.StartsWith("| KI-")) {
            continue
        }
        $summary.total = [int]$summary.total + 1
        if ($trimmed -match "\|\s*(open|mitigated|resolved|accepted_risk)\s*\|") {
            $status = $Matches[1].Trim().ToLowerInvariant()
            if ($summary.Contains($status)) {
                $summary[$status] = [int]$summary[$status] + 1
            }
        }
    }

    return $summary
}

$resolvedRecurringPath = Resolve-RecurringHardeningManifestPath -RequestedPath $RecurringHardeningManifestPath
if (-not (Test-Path $resolvedRecurringPath)) {
    Write-Error ("Recurring hardening manifest not found: {0}" -f $resolvedRecurringPath)
    exit 1
}

$hardening = Read-OperatorJsonFile -Path $resolvedRecurringPath
if ([string]$hardening.bundle_type -ne "phase12_recurring_issue_pattern_hardening") {
    Write-Error "Unexpected recurring hardening manifest bundle_type."
    exit 1
}

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\post-launch-ops\post-launch-triage-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "post-launch-triage.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

$knownIssuesPath = Resolve-OperatorAbsolutePath -Path $KnownIssuesPath -BasePath $repoRoot
$knownIssuesContent = if (Test-Path $knownIssuesPath) { Get-Content -Raw -Path $knownIssuesPath } else { "" }
$knownIssueSummary = Get-KnownIssueSummary -KnownIssuesContent $knownIssuesContent

$triageItems = New-Object System.Collections.Generic.List[object]
$bucketCounts = [ordered]@{
    runbook_backlog = 0
    product_backlog = 0
    release_backlog = 0
    monitoring_only = 0
}

$index = 1
foreach ($action in @($hardening.hardening_actions)) {
    $actionId = [string]$action.action_id
    $actionType = [string]$action.action_type
    $category = [string]$action.category
    $priority = [string]$action.priority
    $bucket = Get-BacklogBucket -ActionType $actionType -Category $category -Priority $priority

    if (-not $bucketCounts.Contains($bucket)) {
        $bucketCounts[$bucket] = 0
    }
    $bucketCounts[$bucket] = [int]$bucketCounts[$bucket] + 1

    $decision = switch ($bucket) {
        "release_backlog" { "candidate_for_release_planning" }
        "product_backlog" { "candidate_for_product_backlog" }
        "runbook_backlog" { "candidate_for_runbook_patch" }
        default { "monitor_only" }
    }

    $triageItems.Add([ordered]@{
        triage_id = ("P13-TRI-{0:D3}" -f $index)
        source_action_id = $actionId
        action_type = $actionType
        category = $category
        priority_hint = $priority
        backlog_bucket = $bucket
        decision = $decision
        rationale = [string]$action.runbook_delta
        source_signal_count = Convert-OperatorToInt -Value $action.source_signal_count -Default 0
        source_bundle_count = Convert-OperatorToInt -Value $action.source_bundle_count -Default 0
        target_docs = @($action.target_docs)
        recommended_script_checks = @($action.recommended_script_checks)
    }) | Out-Null

    $index += 1
}

$payload = [ordered]@{
    bundle_type = "phase13_post_launch_issue_triage"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_recurring_hardening_manifest_path = $resolvedRecurringPath
    source_known_issues_path = $knownIssuesPath
    known_issue_summary = $knownIssueSummary
    triage_item_count = $triageItems.Count
    triage_bucket_counts = $bucketCounts
    triage_items = @($triageItems.ToArray())
    next_steps = @(
        "1) Score triage items by recurrence/impact/operational cost.",
        "2) Route known issues and triage outputs into release/runbook/product queues.",
        "3) Export release backlog package for launch governance review."
    )
}

Save-OperatorJson -Payload $payload -OutPath $OutPath

$reportMarkdownPath = Join-Path $resolvedOutputDir "post-launch-triage.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Post-Launch Issue Triage") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
$lines.Add(("- source_recurring_hardening_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedRecurringPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- triage_item_count: {0}" -f $payload.triage_item_count)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Backlog bucket counts") | Out-Null
foreach ($entry in $bucketCounts.GetEnumerator()) {
    $lines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
}
$lines.Add("") | Out-Null
$lines.Add("## Triage items") | Out-Null
foreach ($item in @($triageItems.ToArray())) {
    $lines.Add(("- {0} [{1}] -> {2}" -f [string]$item.triage_id, [string]$item.category, [string]$item.backlog_bucket)) | Out-Null
}
[System.IO.File]::WriteAllLines($reportMarkdownPath, $lines, [System.Text.Encoding]::UTF8)

if (-not [string]::IsNullOrWhiteSpace($TriageDocPath)) {
    $resolvedDocPath = Resolve-OperatorAbsolutePath -Path $TriageDocPath -BasePath $repoRoot
    $docLines = New-Object System.Collections.Generic.List[string]
    $docLines.Add("# Post-Launch Issue Triage (Phase 13 / p13_t1)") | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Purpose") | Out-Null
    $docLines.Add("Convert recurring hardening outputs and known issue context into deterministic backlog routing decisions.") | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Latest metadata") | Out-Null
    $docLines.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
    $docLines.Add(("- triage_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
    $docLines.Add(("- source_recurring_hardening_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedRecurringPath -RootPath $repoRoot))) | Out-Null
    $docLines.Add(("- triage_item_count: {0}" -f $payload.triage_item_count)) | Out-Null
    $docLines.Add("") | Out-Null
    $docLines.Add("## Backlog bucket counts") | Out-Null
    foreach ($entry in $bucketCounts.GetEnumerator()) {
        $docLines.Add(("- {0}: {1}" -f [string]$entry.Key, [int]$entry.Value)) | Out-Null
    }
    $docLines.Add("") | Out-Null
    $docLines.Add("## Next actions") | Out-Null
    foreach ($step in @($payload.next_steps)) {
        $docLines.Add(("- {0}" -f [string]$step)) | Out-Null
    }
    [System.IO.File]::WriteAllLines($resolvedDocPath, $docLines, [System.Text.Encoding]::UTF8)
}

Write-Host "[done] post-launch issue triage completed"
Write-Host ("  recurring_manifest : {0}" -f $resolvedRecurringPath)
Write-Host ("  triage_items       : {0}" -f $triageItems.Count)
Write-Host ("  manifest           : {0}" -f $OutPath)
Write-Host ("  report_markdown    : {0}" -f $reportMarkdownPath)
if (-not [string]::IsNullOrWhiteSpace($TriageDocPath)) {
    Write-Host ("  triage_doc         : {0}" -f (Resolve-OperatorAbsolutePath -Path $TriageDocPath -BasePath $repoRoot))
}
