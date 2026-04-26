param(
    [string]$CheckpointManifestPath = "",
    [string]$PreviousRoutingManifestPath = "",
    [string]$OwnerAckPath = "docs/steady_state_watchlist_owner_ack.json",
    [string]$LogsRoot = "logs",
    [int]$WatchSlaDays = 7,
    [int]$EscalateSlaDays = 3,
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = "",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

if ($WatchSlaDays -lt 1) {
    Write-Error "-WatchSlaDays must be >= 1."
    exit 1
}
if ($EscalateSlaDays -lt 1) {
    Write-Error "-EscalateSlaDays must be >= 1."
    exit 1
}

function Resolve-LatestManifestPath {
    param(
        [string]$SearchRoot,
        [string]$Filter
    )

    if (-not (Test-Path $SearchRoot)) {
        return ""
    }
    $latest = Get-ChildItem -Path $SearchRoot -Recurse -File -Filter $Filter |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        return ""
    }
    return $latest.FullName
}

function Resolve-OptionalPath {
    param(
        [string]$PathValue,
        [string]$BasePath
    )

    $raw = ([string]$PathValue).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return ""
    }
    return Resolve-OperatorAbsolutePath -Path $raw -BasePath $BasePath
}

function Convert-WatchlistRouteToBoolean {
    param(
        $Value,
        [bool]$Default = $false
    )

    if ($null -eq $Value) {
        return $Default
    }

    if ($Value -is [bool]) {
        return [bool]$Value
    }

    $normalized = ([string]$Value).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return $Default
    }

    if ($normalized -in @("true", "1", "yes", "y", "on")) {
        return $true
    }
    if ($normalized -in @("false", "0", "no", "n", "off")) {
        return $false
    }
    return $Default
}

function Resolve-OwnerAckRulesPath {
    param(
        [string]$PathValue,
        [string]$RepoRootPath
    )

    $resolved = Resolve-OptionalPath -PathValue $PathValue -BasePath $RepoRootPath
    if ([string]::IsNullOrWhiteSpace($resolved)) {
        return ""
    }
    if (-not (Test-Path $resolved)) {
        return ""
    }
    return $resolved
}

function Read-OwnerAckRules {
    param([string]$ResolvedPath)

    if ([string]::IsNullOrWhiteSpace($ResolvedPath)) {
        return @()
    }

    try {
        $parsed = Read-OperatorJsonFile -Path $ResolvedPath
    } catch {
        return @()
    }

    if ($parsed -is [System.Collections.IEnumerable] -and -not ($parsed -is [string])) {
        return @($parsed)
    }
    $rules = Get-OperatorObjectPropertyValue -Object $parsed -Name "rules"
    if ($null -eq $rules) {
        return @()
    }
    return @($rules)
}

function Get-MatchingOwnerAckRule {
    param(
        [object[]]$Rules,
        [string]$Lane,
        [string]$Decision,
        [string]$SourceBundleType,
        [string]$SourceManifestPath
    )

    foreach ($rule in @($Rules)) {
        if ($null -eq $rule) {
            continue
        }

        $enabled = Get-OperatorObjectPropertyValue -Object $rule -Name "enabled"
        if ($null -ne $enabled) {
            if (-not (Convert-WatchlistRouteToBoolean -Value $enabled -Default $true)) {
                continue
            }
        }

        $ruleLane = ([string](Get-OperatorObjectPropertyValue -Object $rule -Name "checkpoint_lane")).Trim().ToLowerInvariant()
        if (-not [string]::IsNullOrWhiteSpace($ruleLane) -and $ruleLane -ne $Lane) {
            continue
        }

        $ruleDecision = ([string](Get-OperatorObjectPropertyValue -Object $rule -Name "decision")).Trim().ToLowerInvariant()
        if (-not [string]::IsNullOrWhiteSpace($ruleDecision) -and $ruleDecision -ne $Decision) {
            continue
        }

        $ruleBundleType = ([string](Get-OperatorObjectPropertyValue -Object $rule -Name "source_bundle_type")).Trim()
        if (-not [string]::IsNullOrWhiteSpace($ruleBundleType) -and $ruleBundleType -ne $SourceBundleType) {
            continue
        }

        $ruleSourceManifest = ([string](Get-OperatorObjectPropertyValue -Object $rule -Name "source_manifest_path")).Trim()
        if (-not [string]::IsNullOrWhiteSpace($ruleSourceManifest) -and $ruleSourceManifest -ne $SourceManifestPath) {
            continue
        }

        return $rule
    }

    return $null
}

function Get-OwnerByLane {
    param([string]$Lane)
    switch (([string]$Lane).Trim().ToLowerInvariant()) {
        "monthly" { return "ga_governance_monthly_owner" }
        "quarterly" { return "ga_governance_quarterly_owner" }
        "release" { return "release_ops_owner" }
        default { return "steady_state_ops_owner" }
    }
}

function Resolve-CheckpointManifestPath {
    param(
        [string]$RequestedPath,
        [string]$LogsRootPath,
        [string]$RepoRootPath
    )

    $resolved = Resolve-OptionalPath -PathValue $RequestedPath -BasePath $RepoRootPath
    if (-not [string]::IsNullOrWhiteSpace($resolved)) {
        if (-not (Test-Path $resolved)) {
            Write-Error ("Checkpoint manifest not found: {0}" -f $resolved)
            exit 1
        }
        return $resolved
    }

    $latest = Resolve-LatestManifestPath -SearchRoot (Join-Path $LogsRootPath "ga-steady-state") -Filter "ga-steady-state-checkpoint-refresh.manifest.json"
    if ([string]::IsNullOrWhiteSpace($latest)) {
        Write-Error "No ga-steady-state-checkpoint-refresh.manifest.json was found."
        exit 1
    }
    return $latest
}

function Resolve-PreviousRoutingManifestPath {
    param(
        [string]$RequestedPath,
        [string]$LogsRootPath,
        [string]$RepoRootPath
    )

    $resolved = Resolve-OptionalPath -PathValue $RequestedPath -BasePath $RepoRootPath
    if (-not [string]::IsNullOrWhiteSpace($resolved)) {
        if (Test-Path $resolved) {
            return $resolved
        }
        return ""
    }

    $latest = Resolve-LatestManifestPath -SearchRoot (Join-Path $LogsRootPath "ga-steady-state") -Filter "ga-steady-state-escalation-watchlist-route.manifest.json"
    return $latest
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedLogsRoot = Resolve-OperatorAbsolutePath -Path $LogsRoot -BasePath $repoRoot
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-steady-state\watchlist-route-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-steady-state-escalation-watchlist-route.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-steady-state-escalation-watchlist-route.summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedCheckpointPath = Resolve-CheckpointManifestPath -RequestedPath $CheckpointManifestPath -LogsRootPath $resolvedLogsRoot -RepoRootPath $repoRoot
$resolvedPreviousRoutingPath = Resolve-PreviousRoutingManifestPath -RequestedPath $PreviousRoutingManifestPath -LogsRootPath $resolvedLogsRoot -RepoRootPath $repoRoot
$resolvedOwnerAckPath = Resolve-OwnerAckRulesPath -PathValue $OwnerAckPath -RepoRootPath $repoRoot

$checkpoint = Read-OperatorJsonFile -Path $resolvedCheckpointPath
if ([string]$checkpoint.bundle_type -ne "steady_state_checkpoint_refresh") {
    Write-Error ("Unsupported checkpoint bundle_type [{0}] in {1}" -f [string]$checkpoint.bundle_type, $resolvedCheckpointPath)
    exit 1
}

$nowUtc = [DateTime]::UtcNow
$watchlistRows = New-Object System.Collections.Generic.List[object]
$ownerRows = @{}
$ownerAckRules = Read-OwnerAckRules -ResolvedPath $resolvedOwnerAckPath
$ownerAckAppliedCount = 0

foreach ($entry in @($checkpoint.details.checkpoints)) {
    $lane = ([string]$entry.checkpoint_lane).Trim().ToLowerInvariant()
    $decision = ([string]$entry.checkpoint_decision).Trim().ToLowerInvariant()
    if ($decision -ne "watch" -and $decision -ne "escalate") {
        continue
    }

    $owner = Get-OwnerByLane -Lane $lane
    $slaDays = if ($decision -eq "escalate") { $EscalateSlaDays } else { $WatchSlaDays }
    $status = if ($decision -eq "escalate") { "owner_assignment_required" } else { "tracking" }
    $etaUtc = $nowUtc.AddDays($slaDays).ToString("o")
    $nextReviewUtc = $etaUtc
    $ackApplied = $false
    $ackRuleId = ""

    $ackRule = Get-MatchingOwnerAckRule `
        -Rules $ownerAckRules `
        -Lane $lane `
        -Decision $decision `
        -SourceBundleType ([string]$entry.source_bundle_type) `
        -SourceManifestPath ([string]$entry.source_manifest_path)
    if ($null -ne $ackRule) {
        $overrideOwner = ([string](Get-OperatorObjectPropertyValue -Object $ackRule -Name "owner")).Trim()
        if (-not [string]::IsNullOrWhiteSpace($overrideOwner)) {
            $owner = $overrideOwner
        }
        $overrideStatus = ([string](Get-OperatorObjectPropertyValue -Object $ackRule -Name "status")).Trim()
        if (-not [string]::IsNullOrWhiteSpace($overrideStatus)) {
            $status = $overrideStatus
        }
        $overrideSlaDaysValue = Get-OperatorObjectPropertyValue -Object $ackRule -Name "sla_days"
        if ($null -ne $overrideSlaDaysValue) {
            $overrideSlaDays = Convert-OperatorToInt -Value $overrideSlaDaysValue -Default $slaDays
            if ($overrideSlaDays -ge 1) {
                $slaDays = $overrideSlaDays
                $etaUtc = $nowUtc.AddDays($slaDays).ToString("o")
                $nextReviewUtc = $etaUtc
            }
        }
        $overrideNextReview = ([string](Get-OperatorObjectPropertyValue -Object $ackRule -Name "next_review_utc")).Trim()
        if (-not [string]::IsNullOrWhiteSpace($overrideNextReview)) {
            $nextReviewUtc = $overrideNextReview
        }
        $ackApplied = $true
        $ownerAckAppliedCount += 1
        $ackRuleId = ([string](Get-OperatorObjectPropertyValue -Object $ackRule -Name "id")).Trim()
    }

    if (-not $ownerRows.ContainsKey($owner)) {
        $ownerRows[$owner] = [ordered]@{
            owner = $owner
            open_item_count = 0
            escalate_item_count = 0
            watch_item_count = 0
            nearest_eta_utc = ""
        }
    }
    $ownerRows[$owner].open_item_count = [int]$ownerRows[$owner].open_item_count + 1
    if ($decision -eq "escalate") {
        $ownerRows[$owner].escalate_item_count = [int]$ownerRows[$owner].escalate_item_count + 1
    } else {
        $ownerRows[$owner].watch_item_count = [int]$ownerRows[$owner].watch_item_count + 1
    }

    $currentNearest = ([string]$ownerRows[$owner].nearest_eta_utc).Trim()
    if ([string]::IsNullOrWhiteSpace($currentNearest)) {
        $ownerRows[$owner].nearest_eta_utc = $etaUtc
    } else {
        try {
            $currentNearestUtc = [DateTime]::Parse($currentNearest).ToUniversalTime()
            $candidateUtc = [DateTime]::Parse($etaUtc).ToUniversalTime()
            if ($candidateUtc -lt $currentNearestUtc) {
                $ownerRows[$owner].nearest_eta_utc = $etaUtc
            }
        } catch {
            $ownerRows[$owner].nearest_eta_utc = $etaUtc
        }
    }

    $watchlistRows.Add([ordered]@{
        watch_item_id = [Guid]::NewGuid().ToString()
        checkpoint_lane = $lane
        source_manifest_path = [string]$entry.source_manifest_path
        source_bundle_type = [string]$entry.source_bundle_type
        decision = $decision
        owner = $owner
        status = $status
        eta_utc = $etaUtc
        next_review_utc = $nextReviewUtc
        sla_days = $slaDays
        escalation_reason = if ($entry.decision_reasons.Count -gt 0) { [string]$entry.decision_reasons[0] } else { "checkpoint decision requires ownership follow-up" }
        decision_reasons = @($entry.decision_reasons)
        owner_ack_applied = $ackApplied
        owner_ack_rule_id = $ackRuleId
    }) | Out-Null
}

$watchlistArray = @($watchlistRows.ToArray())
$ownerTable = @(
    $ownerRows.Values |
        Sort-Object -Property @{Expression = { [int]$_.escalate_item_count }; Descending = $true }, @{Expression = { [int]$_.open_item_count }; Descending = $true }, @{Expression = { [string]$_.owner }; Descending = $false }
)

$previousOpenCount = 0
if (-not [string]::IsNullOrWhiteSpace($resolvedPreviousRoutingPath) -and (Test-Path $resolvedPreviousRoutingPath)) {
    $previous = Read-OperatorJsonFile -Path $resolvedPreviousRoutingPath
    if ([string]$previous.bundle_type -eq "steady_state_escalation_watchlist_routing") {
        $previousOpenCount = Convert-OperatorToInt -Value $previous.summary.watchlist_item_count -Default 0
    }
}

$decisionCounts = [ordered]@{
    watch = @($watchlistArray | Where-Object { $_.decision -eq "watch" }).Count
    escalate = @($watchlistArray | Where-Object { $_.decision -eq "escalate" }).Count
}

$overallDecision = "go"
$overallReasons = New-Object System.Collections.Generic.List[string]
if ($decisionCounts.escalate -gt 0) {
    $overallDecision = "escalate"
    $overallReasons.Add("Escalate decision items exist in checkpoint watchlist routing.") | Out-Null
} elseif ($decisionCounts.watch -gt 0) {
    $overallDecision = "watch"
    $overallReasons.Add("Watch decision items exist and require bounded ownership tracking.") | Out-Null
} else {
    $overallReasons.Add("No watch/escalate checkpoint items remain.") | Out-Null
}

$deltaOpen = $watchlistArray.Count - $previousOpenCount
$summary = [ordered]@{
    generated_at_utc = $nowUtc.ToString("o")
    source_checkpoint_manifest_path = $resolvedCheckpointPath
    previous_watchlist_manifest_path = $resolvedPreviousRoutingPath
    owner_ack_rules_path = $resolvedOwnerAckPath
    owner_ack_rules_count = @($ownerAckRules).Count
    owner_ack_applied_count = $ownerAckAppliedCount
    watchlist_item_count = $watchlistArray.Count
    previous_watchlist_item_count = $previousOpenCount
    delta_watchlist_item_count = $deltaOpen
    owner_count = $ownerTable.Count
    decision_counts = $decisionCounts
    overall_watchlist_decision = $overallDecision
    overall_watchlist_decision_reasons = @($overallReasons.ToArray())
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$manifest = [ordered]@{
    bundle_type = "steady_state_escalation_watchlist_routing"
    bundle_version = 1
    generated_at_utc = $summary.generated_at_utc
    summary = $summary
    details = [ordered]@{
        owner_routing = $ownerTable
        watchlist_items = $watchlistArray
        next_steps = @(
            "1) assign owner acknowledgement for all status=owner_assignment_required items.",
            "2) close or downgrade watchlist items before next checkpoint refresh run.",
            "3) rerun watchlist routing and verify delta_watchlist_item_count trend."
        )
    }
}
Save-OperatorJson -Payload $manifest -OutPath $OutPath

$reportPath = Join-Path $resolvedOutputDir "ga-steady-state-escalation-watchlist-route.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# GA Steady-State Escalation Watchlist Routing") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- watchlist_item_count: {0}" -f [int]$summary.watchlist_item_count)) | Out-Null
$lines.Add(("- previous_watchlist_item_count: {0}" -f [int]$summary.previous_watchlist_item_count)) | Out-Null
$lines.Add(("- delta_watchlist_item_count: {0}" -f [int]$summary.delta_watchlist_item_count)) | Out-Null
$lines.Add(("- overall_watchlist_decision: {0}" -f [string]$summary.overall_watchlist_decision)) | Out-Null
[System.IO.File]::WriteAllLines($reportPath, $lines, [System.Text.Encoding]::UTF8)

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

Write-Host "[done] ga steady-state escalation watchlist routing completed"
Write-Host ("  watchlist_manifest : {0}" -f $OutPath)
Write-Host ("  watchlist_summary  : {0}" -f $SummaryOutPath)
Write-Host ("  decision           : {0}" -f [string]$summary.overall_watchlist_decision)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive            : {0}" -f $archiveOutputPath)
}
