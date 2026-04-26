param(
    [string]$MonthlyManifestPath = "",
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

function Resolve-Or-DiscoverMonthlyManifestPath {
    param(
        [string]$RequestedPath,
        [string]$RepoRoot,
        [string]$LogsRootPath
    )

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        $resolvedRequested = Resolve-OperatorAbsolutePath -Path $requested -BasePath $RepoRoot
        if (-not (Test-Path $resolvedRequested)) {
            throw ("Monthly manifest not found: {0}" -f $resolvedRequested)
        }
        return $resolvedRequested
    }

    $monthlyRoot = Join-Path $LogsRootPath "ga-adoption"
    if (-not (Test-Path $monthlyRoot)) {
        throw ("Monthly manifest root not found: {0}" -f $monthlyRoot)
    }

    $latest = Get-ChildItem -Path $monthlyRoot -Recurse -File -Filter "ga-monthly-reliability-targets.manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw "No ga-monthly-reliability-targets.manifest.json found."
    }
    return $latest.FullName
}

function Get-OwnerByCategory {
    param([string]$Category)

    $normalized = ([string]$Category).Trim().ToLowerInvariant()
    switch ($normalized) {
        "runtime" { return "runtime_ops" }
        "provider_auth" { return "provider_ops" }
        "policy" { return "policy_ops" }
        "semantic_output" { return "semantic_quality" }
        "persistence_restore" { return "data_ops" }
        "operator_flow" { return "operator_ops" }
        "support_evidence" { return "support_ops" }
        default { return "ga_governance" }
    }
}

function Get-RouteByAction {
    param(
        [hashtable]$Action,
        [DateTime]$NowUtc
    )

    $overdue = Convert-OperatorToBool -Value $Action.overdue -Default $false
    $priority = ([string]$Action.priority).Trim().ToUpperInvariant()
    $ageDays = Convert-OperatorToInt -Value $Action.age_days -Default 0
    $slaDays = Convert-OperatorToInt -Value $Action.sla_days -Default 0

    if ($overdue -and $priority -eq "P1") {
        return "immediate_escalation"
    }
    if ($overdue) {
        return "targeted_hardening"
    }
    if ($slaDays -gt 0 -and $ageDays -ge [int][Math]::Floor($slaDays * 0.75)) {
        return "watchlist"
    }
    return "monitor"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-adoption\closure-sla-routing-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-closure-sla-routing.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-closure-sla-routing.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedMonthlyManifestPath = Resolve-Or-DiscoverMonthlyManifestPath `
    -RequestedPath $MonthlyManifestPath `
    -RepoRoot $repoRoot `
    -LogsRootPath $resolvedLogsRoot

$monthly = Read-OperatorJsonFile -Path $resolvedMonthlyManifestPath
if ([string]$monthly.bundle_type -ne "phase17_ga_monthly_reliability_target_package") {
    Write-Error ("Unsupported monthly bundle_type [{0}] in {1}" -f ([string]$monthly.bundle_type), $resolvedMonthlyManifestPath)
    exit 1
}

$nowUtc = [DateTime]::UtcNow
$routed = New-Object System.Collections.Generic.List[object]
$routeCounts = [ordered]@{
    immediate_escalation = 0
    targeted_hardening = 0
    watchlist = 0
    monitor = 0
}
$ownerCounts = @{}
$overdueOwnerCounts = @{}

foreach ($rawAction in @($monthly.details.closure_sla_open_actions)) {
    $action = [ordered]@{
        action_id = [string]$rawAction.action_id
        category = [string]$rawAction.category
        priority = [string]$rawAction.priority
        status = [string]$rawAction.status
        observed_at_utc = [string]$rawAction.observed_at_utc
        age_days = Convert-OperatorToInt -Value $rawAction.age_days -Default 0
        sla_days = Convert-OperatorToInt -Value $rawAction.sla_days -Default 0
        overdue = Convert-OperatorToBool -Value $rawAction.overdue -Default $false
        runbook_delta = [string]$rawAction.runbook_delta
    }
    $owner = Get-OwnerByCategory -Category $action.category
    $route = Get-RouteByAction -Action $action -NowUtc $nowUtc

    if (-not $routeCounts.Contains($route)) {
        $routeCounts[$route] = 0
    }
    $routeCounts[$route] = [int]$routeCounts[$route] + 1

    if (-not $ownerCounts.ContainsKey($owner)) {
        $ownerCounts[$owner] = 0
    }
    $ownerCounts[$owner] = [int]$ownerCounts[$owner] + 1

    if ($action.overdue) {
        if (-not $overdueOwnerCounts.ContainsKey($owner)) {
            $overdueOwnerCounts[$owner] = 0
        }
        $overdueOwnerCounts[$owner] = [int]$overdueOwnerCounts[$owner] + 1
    }

    $dueAtUtc = ""
    try {
        if (-not [string]::IsNullOrWhiteSpace($action.observed_at_utc) -and $action.sla_days -gt 0) {
            $dueAtUtc = [DateTime]::Parse($action.observed_at_utc).ToUniversalTime().AddDays($action.sla_days).ToString("o")
        }
    } catch {
        $dueAtUtc = ""
    }

    $routed.Add([ordered]@{
        action_id = $action.action_id
        category = $action.category
        priority = $action.priority
        status = $action.status
        owner = $owner
        route = $route
        observed_at_utc = $action.observed_at_utc
        due_at_utc = $dueAtUtc
        age_days = $action.age_days
        sla_days = $action.sla_days
        overdue = $action.overdue
        runbook_delta = $action.runbook_delta
    }) | Out-Null
}

$topOwnerRows = @(
    $ownerCounts.GetEnumerator() |
        Sort-Object -Property @{Expression = { [int]$_.Value }; Descending = $true }, @{Expression = { [string]$_.Key }; Descending = $false } |
        ForEach-Object {
            [ordered]@{
                owner = [string]$_.Key
                open_action_count = [int]$_.Value
                overdue_action_count = Convert-OperatorToInt -Value $overdueOwnerCounts[[string]$_.Key] -Default 0
            }
        }
)

$decision = "go"
$decisionReasons = New-Object System.Collections.Generic.List[string]
if ([int]$routeCounts.immediate_escalation -gt 0) {
    $decision = "escalate"
    $decisionReasons.Add("Immediate escalation routes exist for overdue P1 closure-SLA actions.") | Out-Null
}
if ($decision -ne "escalate" -and [int]$routeCounts.targeted_hardening -gt 0) {
    $decision = "watch"
    $decisionReasons.Add("Targeted hardening routes exist for overdue non-P1 closure-SLA actions.") | Out-Null
}
if ($decisionReasons.Count -eq 0) {
    $decisionReasons.Add("No closure-SLA breach escalation routes detected.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = $nowUtc.ToString("o")
    source_monthly_manifest_path = $resolvedMonthlyManifestPath
    open_action_count = $routed.Count
    route_counts = $routeCounts
    owner_open_counts = $topOwnerRows
    closure_sla_decision = $decision
    closure_sla_decision_reasons = @($decisionReasons.ToArray())
}

Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase17_closure_sla_breach_routing"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        monthly_reliability_manifest_path = $resolvedMonthlyManifestPath
    }
    details = [ordered]@{
        closure_sla_routed_actions = @($routed.ToArray())
        runbook_delta_ownership_loop = @($topOwnerRows)
        next_steps = @(
            "1) Assign immediate_escalation actions to owner and set execution ETA within one business day.",
            "2) Apply targeted_hardening runbook deltas before next monthly reliability cycle.",
            "3) Re-run ga-closure-sla-breach-route.ps1 after owner status updates to track closure drift."
        )
    }
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-closure-sla-routing.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Closure-SLA Breach Routing") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- source_monthly_manifest_path: {0}" -f (Get-OperatorRelativePath -Path $resolvedMonthlyManifestPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- open_action_count: {0}" -f [int]$summary.open_action_count)) | Out-Null
$lines.Add(("- closure_sla_decision: {0}" -f [string]$summary.closure_sla_decision)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Route counts") | Out-Null
$lines.Add(("- immediate_escalation: {0}" -f [int]$summary.route_counts.immediate_escalation)) | Out-Null
$lines.Add(("- targeted_hardening: {0}" -f [int]$summary.route_counts.targeted_hardening)) | Out-Null
$lines.Add(("- watchlist: {0}" -f [int]$summary.route_counts.watchlist)) | Out-Null
$lines.Add(("- monitor: {0}" -f [int]$summary.route_counts.monitor)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Owner workload") | Out-Null
if ($topOwnerRows.Count -eq 0) {
    $lines.Add("- none") | Out-Null
} else {
    foreach ($row in $topOwnerRows) {
        $lines.Add(("- {0}: open={1}, overdue={2}" -f ([string]$row.owner), ([int]$row.open_action_count), ([int]$row.overdue_action_count))) | Out-Null
    }
}
$lines.Add("") | Out-Null
$lines.Add("## Decision reasons") | Out-Null
foreach ($reason in @($summary.closure_sla_decision_reasons)) {
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

Write-Host "[done] ga closure-sla breach routing completed"
Write-Host ("  monthly_manifest : {0}" -f $resolvedMonthlyManifestPath)
Write-Host ("  routing_manifest : {0}" -f $OutPath)
Write-Host ("  routing_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  closure_decision : {0}" -f [string]$summary.closure_sla_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive          : {0}" -f $archiveOutputPath)
}
