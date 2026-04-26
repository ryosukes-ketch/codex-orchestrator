param(
    [string]$GaLaunchManifestPath = "",
    [string]$EarlyOpsManifestPath = "",
    [string]$RoutingManifestPath = "",
    [string]$ReadinessManifestPath = "",
    [string]$BundleManifestPath = "",
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [int]$WindowDays = 7,
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
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-launch\phase15-closeout-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "phase15-closeout.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "phase15-closeout-summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$resolvedGaLaunchManifestPath = Resolve-OptionalPath -PathValue $GaLaunchManifestPath -BasePath $repoRoot
$resolvedEarlyOpsManifestPath = Resolve-OptionalPath -PathValue $EarlyOpsManifestPath -BasePath $repoRoot
$resolvedRoutingManifestPath = Resolve-OptionalPath -PathValue $RoutingManifestPath -BasePath $repoRoot
$resolvedReadinessManifestPath = Resolve-OptionalPath -PathValue $ReadinessManifestPath -BasePath $repoRoot
$resolvedBundleManifestPath = Resolve-OptionalPath -PathValue $BundleManifestPath -BasePath $repoRoot
$resolvedKnownIssuesPath = Resolve-OptionalPath -PathValue $KnownIssuesPath -BasePath $repoRoot

if ([string]::IsNullOrWhiteSpace($resolvedKnownIssuesPath)) {
    $resolvedKnownIssuesPath = Resolve-OperatorAbsolutePath -Path "docs/known_issues_register.md" -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($resolvedGaLaunchManifestPath)) {
    $resolvedGaLaunchManifestPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $repoRoot "logs\ga-launch") `
        -Filter "ga-launch-package.manifest.json"
}
if ([string]::IsNullOrWhiteSpace($resolvedEarlyOpsManifestPath)) {
    $resolvedEarlyOpsManifestPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $repoRoot "logs\ga-launch") `
        -Filter "early-ops-incident-loop.manifest.json"
}
if ([string]::IsNullOrWhiteSpace($resolvedRoutingManifestPath)) {
    $resolvedRoutingManifestPath = Resolve-LatestManifestPath `
        -SearchRoot (Join-Path $repoRoot "logs\ga-launch") `
        -Filter "hotfix-next-release-route.manifest.json"
}

$gaLaunchManifestOutputPath = Join-Path $resolvedOutputDir "ga-launch-package.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedGaLaunchManifestPath) -or -not (Test-Path $resolvedGaLaunchManifestPath)) {
    $gaLaunchArgs = @{
        KnownIssuesPath = $resolvedKnownIssuesPath
        OutputDir = (Join-Path $resolvedOutputDir "ga-launch")
        OutPath = $gaLaunchManifestOutputPath
        SummaryOutPath = (Join-Path $resolvedOutputDir "ga-launch-summary.json")
    }
    & (Join-Path $PSScriptRoot "ga-launch-package-execute.ps1") @gaLaunchArgs
    if (-not $?) {
        exit 1
    }
    $resolvedGaLaunchManifestPath = $gaLaunchManifestOutputPath
}

$earlyOpsManifestOutputPath = Join-Path $resolvedOutputDir "early-ops-incident-loop.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedEarlyOpsManifestPath) -or -not (Test-Path $resolvedEarlyOpsManifestPath)) {
    $earlyOpsArgs = @{
        GaLaunchManifestPath = $resolvedGaLaunchManifestPath
        KnownIssuesPath = $resolvedKnownIssuesPath
        WindowDays = $WindowDays
        OutputDir = (Join-Path $resolvedOutputDir "early-ops")
        OutPath = $earlyOpsManifestOutputPath
        SummaryOutPath = (Join-Path $resolvedOutputDir "early-ops-summary.json")
    }
    if (-not [string]::IsNullOrWhiteSpace($resolvedReadinessManifestPath)) {
        $earlyOpsArgs.ReadinessManifestPath = $resolvedReadinessManifestPath
    }
    if (-not [string]::IsNullOrWhiteSpace($resolvedBundleManifestPath)) {
        $earlyOpsArgs.BundleManifestPath = $resolvedBundleManifestPath
    }
    & (Join-Path $PSScriptRoot "early-ops-incident-loop.ps1") @earlyOpsArgs
    if (-not $?) {
        exit 1
    }
    $resolvedEarlyOpsManifestPath = $earlyOpsManifestOutputPath
}

$routingManifestOutputPath = Join-Path $resolvedOutputDir "hotfix-next-release-route.manifest.json"
if ([string]::IsNullOrWhiteSpace($resolvedRoutingManifestPath) -or -not (Test-Path $resolvedRoutingManifestPath)) {
    $routingArgs = @{
        EarlyOpsManifestPath = $resolvedEarlyOpsManifestPath
        KnownIssuesPath = $resolvedKnownIssuesPath
        OutputDir = (Join-Path $resolvedOutputDir "routing")
        OutPath = $routingManifestOutputPath
        SummaryOutPath = (Join-Path $resolvedOutputDir "routing-summary.json")
    }
    & (Join-Path $PSScriptRoot "hotfix-next-release-route.ps1") @routingArgs
    if (-not $?) {
        exit 1
    }
    $resolvedRoutingManifestPath = $routingManifestOutputPath
}

$gaLaunch = Read-OperatorJsonFile -Path $resolvedGaLaunchManifestPath
$earlyOps = Read-OperatorJsonFile -Path $resolvedEarlyOpsManifestPath
$routing = Read-OperatorJsonFile -Path $resolvedRoutingManifestPath

if ([string]$gaLaunch.bundle_type -ne "phase15_ga_launch_execution_package") {
    Write-Error ("Unexpected ga launch bundle_type: {0}" -f [string]$gaLaunch.bundle_type)
    exit 1
}
if ([string]$earlyOps.bundle_type -ne "phase15_early_operations_incident_loop") {
    Write-Error ("Unexpected early ops bundle_type: {0}" -f [string]$earlyOps.bundle_type)
    exit 1
}
if ([string]$routing.bundle_type -ne "phase15_hotfix_next_release_routing") {
    Write-Error ("Unexpected routing bundle_type: {0}" -f [string]$routing.bundle_type)
    exit 1
}

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    ga_launch_decision = [string]$gaLaunch.summary.decision
    ga_launch_rollback_signal = [string]$gaLaunch.summary.rollback_signal
    early_ops_blocking_findings = Convert-OperatorToBool -Value $earlyOps.summary.support_bundle_has_blocking_findings -Default $false
    early_ops_finding_count = Convert-OperatorToInt -Value $earlyOps.summary.support_bundle_finding_count -Default 0
    early_ops_hardening_action_count = Convert-OperatorToInt -Value $earlyOps.summary.recurring_hardening_action_count -Default 0
    routing_hotfix_candidate_count = Convert-OperatorToInt -Value $routing.summary.hotfix_candidate_count -Default 0
    routing_next_release_candidate_count = Convert-OperatorToInt -Value $routing.summary.next_release_candidate_count -Default 0
    routing_stabilization_recommendation = [string]$routing.summary.stabilization_recommendation
}

$summary.phase15_completion_ready = (
    -not $summary.early_ops_blocking_findings `
        -and (
            $summary.ga_launch_decision -eq "GO" `
                -or $summary.ga_launch_decision -eq "HOLD" `
                -or $summary.ga_launch_decision -eq "ROLLBACK_READY" `
                -or $summary.ga_launch_decision -eq "ROLLBACK_REQUIRED"
        )
)

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

$markdownPath = Join-Path $resolvedOutputDir "phase15-closeout-summary.md"
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Phase 15 Evidence Closeout Summary") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$lines.Add(("- ga_launch_decision: {0}" -f $summary.ga_launch_decision)) | Out-Null
$lines.Add(("- ga_launch_rollback_signal: {0}" -f $summary.ga_launch_rollback_signal)) | Out-Null
$lines.Add(("- early_ops_blocking_findings: {0}" -f $summary.early_ops_blocking_findings)) | Out-Null
$lines.Add(("- early_ops_finding_count: {0}" -f $summary.early_ops_finding_count)) | Out-Null
$lines.Add(("- early_ops_hardening_action_count: {0}" -f $summary.early_ops_hardening_action_count)) | Out-Null
$lines.Add(("- routing_hotfix_candidate_count: {0}" -f $summary.routing_hotfix_candidate_count)) | Out-Null
$lines.Add(("- routing_next_release_candidate_count: {0}" -f $summary.routing_next_release_candidate_count)) | Out-Null
$lines.Add(("- routing_stabilization_recommendation: {0}" -f $summary.routing_stabilization_recommendation)) | Out-Null
$lines.Add(("- phase15_completion_ready: {0}" -f $summary.phase15_completion_ready)) | Out-Null
$lines.Add("") | Out-Null
$lines.Add("## Artifacts") | Out-Null
$lines.Add(("- ga_launch_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedGaLaunchManifestPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- early_ops_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedEarlyOpsManifestPath -RootPath $repoRoot))) | Out-Null
$lines.Add(("- routing_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedRoutingManifestPath -RootPath $repoRoot))) | Out-Null
[System.IO.File]::WriteAllLines($markdownPath, $lines, [System.Text.Encoding]::UTF8)

$manifest = [ordered]@{
    bundle_type = "phase15_evidence_closeout"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    output_dir = $resolvedOutputDir
    summary = $summary
    artifacts = [ordered]@{
        ga_launch_manifest = New-OperatorManifestArtifactEntry -Path $resolvedGaLaunchManifestPath -RepoRoot $repoRoot
        early_ops_manifest = New-OperatorManifestArtifactEntry -Path $resolvedEarlyOpsManifestPath -RepoRoot $repoRoot
        routing_manifest = New-OperatorManifestArtifactEntry -Path $resolvedRoutingManifestPath -RepoRoot $repoRoot
        closeout_summary_json = New-OperatorManifestArtifactEntry -Path $SummaryOutPath -RepoRoot $repoRoot
        closeout_summary_markdown = New-OperatorManifestArtifactEntry -Path $markdownPath -RepoRoot $repoRoot
    }
    archive_path = $archiveOutputPath
    next_steps = @(
        "1) Sync phase_15 task statuses in roadmap after closeout evidence review.",
        "2) Record phase15 closeout artifacts in staging execution record.",
        "3) Decide next active phase and update direction guard."
    )
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

Write-Host "[done] phase15 evidence closeout completed"
Write-Host ("  completion_ready : {0}" -f $summary.phase15_completion_ready)
Write-Host ("  ga_launch        : {0}" -f $resolvedGaLaunchManifestPath)
Write-Host ("  early_ops        : {0}" -f $resolvedEarlyOpsManifestPath)
Write-Host ("  routing          : {0}" -f $resolvedRoutingManifestPath)
Write-Host ("  summary_json     : {0}" -f $SummaryOutPath)
Write-Host ("  manifest         : {0}" -f $OutPath)
