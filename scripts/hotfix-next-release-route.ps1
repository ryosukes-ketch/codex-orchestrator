param(
    [string]$EarlyOpsManifestPath = "",
    [string]$RecurringHardeningManifestPath = "",
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [string]$OutputDir = "",
    [switch]$Zip,
    [string]$ArchivePath = "",
    [string]$OutPath = "",
    [string]$SummaryOutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

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

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-launch\hotfix-next-release-route-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "hotfix-next-release-route.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "hotfix-next-release-summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedEarlyOpsManifestPath = Resolve-OptionalPath -PathValue $EarlyOpsManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedEarlyOpsManifestPath)) {
    $resolvedEarlyOpsManifestPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $repoRoot "logs\ga-launch") `
        -Filter "early-ops-incident-loop.manifest.json"
}

$resolvedRecurringManifestPath = Resolve-OptionalPath -PathValue $RecurringHardeningManifestPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedRecurringManifestPath) -and -not [string]::IsNullOrWhiteSpace($resolvedEarlyOpsManifestPath) -and (Test-Path $resolvedEarlyOpsManifestPath)) {
    $earlyOps = Read-OperatorJsonFile -Path $resolvedEarlyOpsManifestPath
    if ([string]$earlyOps.bundle_type -ne "phase15_early_operations_incident_loop") {
        Write-Error ("Unexpected early ops bundle_type: {0}" -f [string]$earlyOps.bundle_type)
        exit 1
    }
    $resolvedRecurringManifestPath = Resolve-OperatorBundleArtifactPath `
        -Manifest $earlyOps `
        -ArtifactName "recurring_hardening_manifest" `
        -RepoRoot $repoRoot
}
if ([string]::IsNullOrWhiteSpace($resolvedRecurringManifestPath)) {
    $resolvedRecurringManifestPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $repoRoot "logs\post-launch-ops") `
        -Filter "recurring-issue-hardening.manifest.json"
}

if ([string]::IsNullOrWhiteSpace($resolvedRecurringManifestPath) -or -not (Test-Path $resolvedRecurringManifestPath)) {
    Write-Error "Recurring hardening manifest not found. Provide -RecurringHardeningManifestPath."
    exit 1
}

$resolvedKnownIssuesPath = Resolve-OptionalPath -PathValue $KnownIssuesPath -BasePath $repoRoot
if ([string]::IsNullOrWhiteSpace($resolvedKnownIssuesPath)) {
    $resolvedKnownIssuesPath = Resolve-OperatorAbsolutePath -Path "docs/known_issues_register.md" -BasePath $repoRoot
}

$triageManifestPath = Join-Path $resolvedOutputDir "post-launch-triage.manifest.json"
$priorityManifestPath = Join-Path $resolvedOutputDir "post-launch-priority-score.manifest.json"
$routingManifestPath = Join-Path $resolvedOutputDir "known-issue-routing.manifest.json"
$backlogManifestPath = Join-Path $resolvedOutputDir "post-launch-backlog-export.manifest.json"

$triageArgs = @{
    RecurringHardeningManifestPath = $resolvedRecurringManifestPath
    KnownIssuesPath = $resolvedKnownIssuesPath
    OutPath = $triageManifestPath
    TriageDocPath = "docs/post_launch_issue_triage.md"
}
& (Join-Path $PSScriptRoot "post-launch-triage.ps1") @triageArgs
if (-not $?) {
    exit 1
}

$priorityArgs = @{
    TriageManifestPath = $triageManifestPath
    OutPath = $priorityManifestPath
    ScoringDocPath = "docs/post_launch_priority_scoring.md"
}
& (Join-Path $PSScriptRoot "post-launch-priority-score.ps1") @priorityArgs
if (-not $?) {
    exit 1
}

$routingArgs = @{
    PriorityManifestPath = $priorityManifestPath
    KnownIssuesPath = $resolvedKnownIssuesPath
    OutPath = $routingManifestPath
    RoutingDocPath = "docs/known_issue_routing.md"
}
& (Join-Path $PSScriptRoot "known-issue-route.ps1") @routingArgs
if (-not $?) {
    exit 1
}

$backlogArgs = @{
    RoutingManifestPath = $routingManifestPath
    OutPath = $backlogManifestPath
    BacklogDocPath = "docs/post_launch_release_backlog_flow.md"
}
& (Join-Path $PSScriptRoot "post-launch-backlog-export.ps1") @backlogArgs
if (-not $?) {
    exit 1
}

$routing = Read-OperatorJsonFile -Path $routingManifestPath
$backlog = Read-OperatorJsonFile -Path $backlogManifestPath

$hotfixCount = 0
$nextReleaseCount = 0
foreach ($item in @($backlog.release_candidates)) {
    $lane = ([string]$item.backlog_lane).Trim().ToLowerInvariant()
    if ($lane -eq "hotfix") {
        $hotfixCount += 1
    } elseif ($lane -eq "next_release") {
        $nextReleaseCount += 1
    }
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    routed_item_count = Convert-OperatorToInt -Value $routing.routed_item_count -Default 0
    hotfix_candidate_count = $hotfixCount
    next_release_candidate_count = $nextReleaseCount
    runbook_patch_count = Convert-OperatorToInt -Value $backlog.summary.runbook_patch_count -Default 0
    monitoring_only_count = Convert-OperatorToInt -Value $backlog.summary.monitoring_only_count -Default 0
    deferred_count = Convert-OperatorToInt -Value $backlog.summary.deferred_count -Default 0
    stabilization_recommendation = if ($hotfixCount -gt 0) { "prioritize_hotfix_lane" } elseif ($nextReleaseCount -gt 0) { "prioritize_next_release_lane" } else { "monitor_only_cycle" }
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = ([string]$ArchivePath).Trim()
    if ([string]::IsNullOrWhiteSpace($archiveOutputPath)) {
        $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    } elseif (-not [System.IO.Path]::IsPathRooted($archiveOutputPath)) {
        $archiveOutputPath = Resolve-OperatorAbsolutePath -Path $archiveOutputPath -BasePath $repoRoot
    }
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

$markdownPath = Join-Path $resolvedOutputDir "hotfix-next-release-summary.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Hotfix and Next-Release Routing Summary") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- routed_item_count: {0}" -f $summary.routed_item_count)) | Out-Null
$lines.Add(("- hotfix_candidate_count: {0}" -f $summary.hotfix_candidate_count)) | Out-Null
$lines.Add(("- next_release_candidate_count: {0}" -f $summary.next_release_candidate_count)) | Out-Null
$lines.Add(("- runbook_patch_count: {0}" -f $summary.runbook_patch_count)) | Out-Null
$lines.Add(("- monitoring_only_count: {0}" -f $summary.monitoring_only_count)) | Out-Null
$lines.Add(("- deferred_count: {0}" -f $summary.deferred_count)) | Out-Null
$lines.Add(("- stabilization_recommendation: {0}" -f $summary.stabilization_recommendation)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Artifacts") | Out-Null
$lines.Add(("- triage_manifest: {0}" -f (Get-OperatorRelativePath -Path $triageManifestPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- priority_manifest: {0}" -f (Get-OperatorRelativePath -Path $priorityManifestPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- routing_manifest: {0}" -f (Get-OperatorRelativePath -Path $routingManifestPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- backlog_manifest: {0}" -f (Get-OperatorRelativePath -Path $backlogManifestPath -RootPath $repoRoot))) | Out-Null
[System.IO.File]::WriteAllLines($markdownPath, $lines, [System.Text.Encoding]::UTF8)

$manifest = [ordered]@{
    bundle_type = "phase15_hotfix_next_release_routing"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    output_dir = $resolvedOutputDir
    summary = $summary
    source_inputs = [ordered]@{
        early_ops_manifest_path = $resolvedEarlyOpsManifestPath
        recurring_hardening_manifest_path = $resolvedRecurringManifestPath
        known_issues_path = $resolvedKnownIssuesPath
    }
    artifacts = [ordered]@{
        triage_manifest = New-OperatorManifestArtifactEntry -Path $triageManifestPath -RepoRoot $repoRoot
        priority_manifest = New-OperatorManifestArtifactEntry -Path $priorityManifestPath -RepoRoot $repoRoot
        routing_manifest = New-OperatorManifestArtifactEntry -Path $routingManifestPath -RepoRoot $repoRoot
        backlog_export_manifest = New-OperatorManifestArtifactEntry -Path $backlogManifestPath -RepoRoot $repoRoot
        routing_summary_json = New-OperatorManifestArtifactEntry -Path $SummaryOutPath -RepoRoot $repoRoot
        routing_summary_markdown = New-OperatorManifestArtifactEntry -Path $markdownPath -RepoRoot $repoRoot
    }
    archive_path = $archiveOutputPath
    next_steps = @(
        "1) Promote hotfix candidates to immediate release-governance review.",
        "2) Keep next-release candidates in release-train planning lane.",
        "3) Record selected lane decisions in phase15 closeout evidence."
    )
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

Write-Host "[done] hotfix and next-release routing stabilization completed"
Write-Host ("  hotfix_candidates    : {0}" -f $summary.hotfix_candidate_count)
Write-Host ("  next_release_items   : {0}" -f $summary.next_release_candidate_count)
Write-Host ("  backlog_manifest     : {0}" -f $backlogManifestPath)
Write-Host ("  summary_json         : {0}" -f $SummaryOutPath)
Write-Host ("  manifest             : {0}" -f $OutPath)
