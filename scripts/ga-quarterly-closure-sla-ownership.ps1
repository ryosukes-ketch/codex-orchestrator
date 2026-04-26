param(
    [string]$LogsRoot = "logs",
    [int]$WindowDays = 90,
    [string[]]$ClosureRoutingManifestPaths = @(),
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

function Resolve-OptionalArrayPaths {
    param(
        [string[]]$InputPaths,
        [string]$BasePath
    )

    $resolved = New-Object System.Collections.Generic.List[string]
    foreach ($value in @($InputPaths)) {
        foreach ($token in (([string]$value) -split ",")) {
            $trimmed = ([string]$token).Trim()
            if ([string]::IsNullOrWhiteSpace($trimmed)) {
                continue
            }
            $resolved.Add((Resolve-OperatorAbsolutePath -Path $trimmed -BasePath $BasePath)) | Out-Null
        }
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

function Resolve-ClosureRoutingManifestList {
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

    $root = Join-Path $LogsRootPath "ga-adoption"
    if (-not (Test-Path $root)) {
        return @()
    }

    $resolved = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in Get-ChildItem -Path $root -Recurse -File -Filter "ga-closure-sla-routing.manifest.json") {
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

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$windowEndUtc = [DateTime]::UtcNow
$windowStartUtc = $windowEndUtc.AddDays(-1 * $WindowDays)

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-adoption\quarterly-closure-ownership-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-quarterly-closure-sla-ownership.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-quarterly-closure-sla-ownership.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$requestedPaths = Resolve-OptionalArrayPaths -InputPaths $ClosureRoutingManifestPaths -BasePath $repoRoot
$routingManifestPaths = Resolve-ClosureRoutingManifestList `
    -RequestedPaths $requestedPaths `
    -LogsRootPath $resolvedLogsRoot `
    -WindowStartUtc $windowStartUtc `
    -WindowEndUtc $windowEndUtc

if (@($routingManifestPaths).Count -eq 0) {
    Write-Error "No closure-SLA routing manifests were found in the requested window."
    exit 1
}

$manifestEntries = New-Object System.Collections.Generic.List[object]
$ownerRows = @{}
$actionSeenCounts = @{}
$latestActionState = @{}
$routeTotals = [ordered]@{
    immediate_escalation = 0
    targeted_hardening = 0
    watchlist = 0
    monitor = 0
}

foreach ($path in @($routingManifestPaths)) {
    $resolvedPath = Resolve-OperatorAbsolutePath -Path $path -BasePath $repoRoot
    if (-not (Test-Path $resolvedPath)) {
        Write-Error ("Closure routing manifest path not found: {0}" -f $resolvedPath)
        exit 1
    }

    $payload = Read-OperatorJsonFile -Path $resolvedPath
    if ([string]$payload.bundle_type -ne "phase17_closure_sla_breach_routing") {
        Write-Error ("Unsupported closure routing bundle_type [{0}] in {1}" -f ([string]$payload.bundle_type), $resolvedPath)
        exit 1
    }

    $generatedAtUtc = Parse-UtcOrDefault -Value ([string]$payload.generated_at_utc) -DefaultUtc (Get-Item $resolvedPath).LastWriteTimeUtc
    if ($generatedAtUtc -lt $windowStartUtc -or $generatedAtUtc -gt $windowEndUtc) {
        continue
    }

    foreach ($row in @($payload.details.closure_sla_routed_actions)) {
        $actionId = ([string]$row.action_id).Trim()
        if ([string]::IsNullOrWhiteSpace($actionId)) {
            continue
        }
        $owner = ([string]$row.owner).Trim().ToLowerInvariant()
        if ([string]::IsNullOrWhiteSpace($owner)) {
            $owner = "unassigned"
        }
        $route = ([string]$row.route).Trim().ToLowerInvariant()
        if ([string]::IsNullOrWhiteSpace($route)) {
            $route = "monitor"
        }

        if (-not $ownerRows.ContainsKey($owner)) {
            $ownerRows[$owner] = [ordered]@{
                owner = $owner
                open_action_count = 0
                overdue_action_count = 0
                immediate_escalation_count = 0
                targeted_hardening_count = 0
                watchlist_count = 0
                monitor_count = 0
            }
        }

        $ownerRows[$owner].open_action_count = [int]$ownerRows[$owner].open_action_count + 1
        if (Convert-OperatorToBool -Value $row.overdue -Default $false) {
            $ownerRows[$owner].overdue_action_count = [int]$ownerRows[$owner].overdue_action_count + 1
        }
        if ($route -eq "immediate_escalation") {
            $ownerRows[$owner].immediate_escalation_count = [int]$ownerRows[$owner].immediate_escalation_count + 1
        } elseif ($route -eq "targeted_hardening") {
            $ownerRows[$owner].targeted_hardening_count = [int]$ownerRows[$owner].targeted_hardening_count + 1
        } elseif ($route -eq "watchlist") {
            $ownerRows[$owner].watchlist_count = [int]$ownerRows[$owner].watchlist_count + 1
        } else {
            $ownerRows[$owner].monitor_count = [int]$ownerRows[$owner].monitor_count + 1
        }

        if (-not $routeTotals.Contains($route)) {
            $routeTotals[$route] = 0
        }
        $routeTotals[$route] = [int]$routeTotals[$route] + 1

        if (-not $actionSeenCounts.ContainsKey($actionId)) {
            $actionSeenCounts[$actionId] = 0
        }
        $actionSeenCounts[$actionId] = [int]$actionSeenCounts[$actionId] + 1
        $latestActionState[$actionId] = [ordered]@{
            action_id = $actionId
            owner = $owner
            status = [string]$row.status
            route = $route
            overdue = Convert-OperatorToBool -Value $row.overdue -Default $false
            due_at_utc = [string]$row.due_at_utc
            generated_at_utc = $generatedAtUtc.ToString("o")
        }
    }

    $manifestEntries.Add([ordered]@{
        path = $resolvedPath
        generated_at_utc = $generatedAtUtc.ToString("o")
    }) | Out-Null
}

if ($manifestEntries.Count -eq 0) {
    Write-Error "No closure-SLA routing manifests fell within the requested window."
    exit 1
}

$carryOverActions = New-Object System.Collections.Generic.List[object]
foreach ($pair in $actionSeenCounts.GetEnumerator()) {
    $actionId = [string]$pair.Key
    $seenCount = Convert-OperatorToInt -Value $pair.Value -Default 0
    if ($seenCount -lt 2) {
        continue
    }
    $state = $latestActionState[$actionId]
    if ($null -eq $state) {
        continue
    }
    $status = ([string]$state.status).Trim().ToLowerInvariant()
    $closed = @("done", "closed", "resolved", "completed", "mitigated") -contains $status
    if ($closed) {
        continue
    }
    $carryOverActions.Add([ordered]@{
        action_id = $actionId
        owner = [string]$state.owner
        status = [string]$state.status
        route = [string]$state.route
        seen_in_routing_cycles = $seenCount
        overdue = Convert-OperatorToBool -Value $state.overdue -Default $false
        due_at_utc = [string]$state.due_at_utc
        latest_routed_at_utc = [string]$state.generated_at_utc
    }) | Out-Null
}

$ownerTable = @(
    $ownerRows.Values |
        ForEach-Object {
            $commitmentStatus = "on_track"
            if ([int]$_.immediate_escalation_count -gt 0) {
                $commitmentStatus = "escalate"
            } elseif ([int]$_.overdue_action_count -gt 0 -or [int]$_.targeted_hardening_count -gt 0) {
                $commitmentStatus = "at_risk"
            }
            [ordered]@{
                owner = [string]$_.owner
                open_action_count = [int]$_.open_action_count
                overdue_action_count = [int]$_.overdue_action_count
                immediate_escalation_count = [int]$_.immediate_escalation_count
                targeted_hardening_count = [int]$_.targeted_hardening_count
                watchlist_count = [int]$_.watchlist_count
                monitor_count = [int]$_.monitor_count
                commitment_status = $commitmentStatus
            }
        } |
        Sort-Object -Property @{Expression = { [int]$_.immediate_escalation_count }; Descending = $true }, @{Expression = { [int]$_.overdue_action_count }; Descending = $true }, @{Expression = { [string]$_.owner }; Descending = $false }
)

$decision = "go"
$reasons = New-Object System.Collections.Generic.List[string]
if ([int]$routeTotals.immediate_escalation -gt 0) {
    $decision = "escalate"
    $reasons.Add("Immediate escalation routes are present in quarterly closure-SLA ownership data.") | Out-Null
} elseif ([int]$routeTotals.targeted_hardening -gt 0 -or $carryOverActions.Count -gt 0) {
    $decision = "watch"
    $reasons.Add("Targeted hardening routes or unresolved carry-over actions are present.") | Out-Null
} else {
    $reasons.Add("No closure-SLA breach escalation routes or unresolved carry-over actions detected.") | Out-Null
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    analysis_window_utc = [ordered]@{
        start = $windowStartUtc.ToString("o")
        end = $windowEndUtc.ToString("o")
        days = $WindowDays
    }
    routing_manifest_count = $manifestEntries.Count
    owner_commitment_count = $ownerTable.Count
    route_totals = $routeTotals
    carry_over_action_count = $carryOverActions.Count
    quarterly_closure_decision = $decision
    quarterly_closure_decision_reasons = @($reasons.ToArray())
}

Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "phase18_quarterly_closure_sla_ownership"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    source = [ordered]@{
        logs_root = $resolvedLogsRoot
        closure_routing_manifests = @($manifestEntries.ToArray())
    }
    details = [ordered]@{
        owner_commitments = @($ownerTable)
        carry_over_actions = @($carryOverActions.ToArray())
        next_steps = @(
            "1) escalate owners with commitment_status=escalate and set one-business-day action ETA.",
            "2) review at_risk owners and convert targeted_hardening items into bounded runbook deltas.",
            "3) rerun quarterly closure ownership package after monthly cycle close and compare carry-over drift."
        )
    }
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-quarterly-closure-sla-ownership.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Quarterly Closure-SLA Ownership") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- routing_manifest_count: {0}" -f [int]$summary.routing_manifest_count)) | Out-Null
$lines.Add(("- owner_commitment_count: {0}" -f [int]$summary.owner_commitment_count)) | Out-Null
$lines.Add(("- carry_over_action_count: {0}" -f [int]$summary.carry_over_action_count)) | Out-Null
$lines.Add(("- quarterly_closure_decision: {0}" -f [string]$summary.quarterly_closure_decision)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Route totals") | Out-Null
$lines.Add(("- immediate_escalation: {0}" -f [int]$summary.route_totals.immediate_escalation)) | Out-Null
$lines.Add(("- targeted_hardening: {0}" -f [int]$summary.route_totals.targeted_hardening)) | Out-Null
$lines.Add(("- watchlist: {0}" -f [int]$summary.route_totals.watchlist)) | Out-Null
$lines.Add(("- monitor: {0}" -f [int]$summary.route_totals.monitor)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Owner commitments") | Out-Null
if ($ownerTable.Count -eq 0) {
    $lines.Add("- none") | Out-Null
} else {
    foreach ($row in $ownerTable) {
        $lines.Add(("- {0}: status={1}, open={2}, overdue={3}, immediate={4}" -f ([string]$row.owner), ([string]$row.commitment_status), ([int]$row.open_action_count), ([int]$row.overdue_action_count), ([int]$row.immediate_escalation_count))) | Out-Null
    }
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

Write-Host "[done] ga quarterly closure-SLA ownership completed"
Write-Host ("  ownership_manifest : {0}" -f $OutPath)
Write-Host ("  ownership_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  closure_decision   : {0}" -f [string]$summary.quarterly_closure_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive            : {0}" -f $archiveOutputPath)
}
