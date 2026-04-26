param(
    [string]$ReadinessManifestPath = "",
    [string]$BundleManifestPath = "",
    [string]$OutputDir = "",
    [switch]$Zip,
    [string]$ArchivePath = "",
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

if (
    [string]::IsNullOrWhiteSpace($ReadinessManifestPath) `
        -and [string]::IsNullOrWhiteSpace($BundleManifestPath)
) {
    Write-Error "Provide -ReadinessManifestPath or -BundleManifestPath."
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\operator-replay-exports\{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedOutputDir))
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

$seenPaths = New-Object System.Collections.Generic.HashSet[string]
$artifactRecords = New-Object System.Collections.Generic.List[object]
$missingArtifacts = New-Object System.Collections.Generic.List[object]

function Add-ReplayArtifact {
    param(
        [string]$Role,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    $resolvedPath = Resolve-OperatorAbsolutePath -Path $Path -BasePath $repoRoot
    if ([string]::IsNullOrWhiteSpace($resolvedPath)) {
        return
    }
    if (-not (Test-Path $resolvedPath)) {
        $missingArtifacts.Add([pscustomobject]@{
            role = $Role
            source_path = $resolvedPath
        }) | Out-Null
        return
    }
    if ($seenPaths.Contains($resolvedPath)) {
        return
    }
    $seenPaths.Add($resolvedPath) | Out-Null

    $relativePath = Get-OperatorRelativePath -Path $resolvedPath -RootPath $repoRoot
    if (
        [string]::IsNullOrWhiteSpace($relativePath) `
            -or $relativePath.StartsWith("..") `
            -or [System.IO.Path]::IsPathRooted($relativePath) `
            -or $relativePath.Contains(":")
    ) {
        $relativePath = Join-Path "external" ([System.IO.Path]::GetFileName($resolvedPath))
    }
    $normalizedRelativePath = $relativePath.Replace("/", "\")
    $targetPath = Join-Path $resolvedOutputDir $normalizedRelativePath
    $targetParent = Split-Path -Parent $targetPath
    if (-not [string]::IsNullOrWhiteSpace($targetParent)) {
        New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
    }
    Copy-Item -Path $resolvedPath -Destination $targetPath -Force

    $artifactRecords.Add([pscustomobject]@{
        role = $Role
        source_path = $resolvedPath
        exported_path = $targetPath
        exported_relative_path = $normalizedRelativePath
    }) | Out-Null
}

function Add-CycleBundleArtifacts {
    param(
        [string]$CycleBundleManifestPath,
        [string]$ModePrefix = ""
    )

    if ([string]::IsNullOrWhiteSpace($CycleBundleManifestPath)) {
        return
    }
    $cycleContext = Resolve-OperatorCycleBundleContext `
        -BundleManifestPath $CycleBundleManifestPath `
        -RepoRoot $repoRoot
    $rolePrefix = if ([string]::IsNullOrWhiteSpace($ModePrefix)) { "cycle" } else { "cycle_{0}" -f $ModePrefix }

    Add-ReplayArtifact -Role ("{0}_bundle_manifest" -f $rolePrefix) -Path $cycleContext.manifest_path
    Add-ReplayArtifact -Role ("{0}_summary" -f $rolePrefix) -Path $cycleContext.summary_path
    Add-ReplayArtifact -Role ("{0}_status" -f $rolePrefix) -Path $cycleContext.status_path
    Add-ReplayArtifact -Role ("{0}_status_summary" -f $rolePrefix) -Path $cycleContext.status_summary_path
    Add-ReplayArtifact -Role ("{0}_audit" -f $rolePrefix) -Path $cycleContext.audit_path
    Add-ReplayArtifact -Role ("{0}_stage_report" -f $rolePrefix) -Path $cycleContext.stage_report_path
    Add-ReplayArtifact -Role ("{0}_audit_assert" -f $rolePrefix) -Path $cycleContext.audit_assert_path
}

$sourceType = ""
$sourceManifestPath = ""
if (-not [string]::IsNullOrWhiteSpace($ReadinessManifestPath)) {
    $readinessContext = Resolve-ReadinessBundleContext `
        -ReadinessManifestPath $ReadinessManifestPath `
        -RepoRoot $repoRoot
    $sourceType = "readiness"
    $sourceManifestPath = $readinessContext.manifest_path

    Add-ReplayArtifact -Role "readiness_manifest" -Path $readinessContext.manifest_path
    Add-ReplayArtifact -Role "readiness_summary" -Path $readinessContext.summary_path
    Add-ReplayArtifact -Role "readiness_live_smoke_log" -Path $readinessContext.live_smoke_log_path
    Add-ReplayArtifact -Role "readiness_seed_log" -Path $readinessContext.seed_log_path
    Add-ReplayArtifact -Role "readiness_openclaw_evidence" -Path $readinessContext.openclaw_evidence_path

    Add-ReplayArtifact -Role "suite_bundle_manifest" -Path $readinessContext.operator_suite_manifest_path
    Add-ReplayArtifact -Role "suite_summary" -Path $readinessContext.operator_suite_summary_path
    Add-ReplayArtifact -Role "suite_stage_gate" -Path $readinessContext.operator_suite_stage_gate_path
    Add-ReplayArtifact -Role "suite_handoff" -Path $readinessContext.operator_suite_handoff_path

    if (-not [string]::IsNullOrWhiteSpace($readinessContext.operator_suite_manifest_path)) {
        $suiteContext = Resolve-OperatorSuiteBundleContext `
            -BundleManifestPath $readinessContext.operator_suite_manifest_path `
            -RepoRoot $repoRoot
        Add-ReplayArtifact -Role "suite_bundle_manifest" -Path $suiteContext.manifest_path
        Add-ReplayArtifact -Role "suite_summary" -Path $suiteContext.summary_path
        Add-ReplayArtifact -Role "suite_stage_gate" -Path $suiteContext.stage_gate_path
        Add-ReplayArtifact -Role "suite_handoff_json" -Path $suiteContext.handoff_json_path
        Add-ReplayArtifact -Role "suite_handoff_markdown" -Path $suiteContext.handoff_markdown_path
        foreach ($cycle in @($suiteContext.cycles)) {
            Add-CycleBundleArtifacts `
                -CycleBundleManifestPath ([string]$cycle.bundle_manifest_path) `
                -ModePrefix ([string]$cycle.mode)
        }
    }
} else {
    $sourceManifestPath = Resolve-OperatorAbsolutePath -Path $BundleManifestPath -BasePath $repoRoot
    $manifest = Read-OperatorBundleManifest -Path $sourceManifestPath
    $bundleType = [string](Get-OperatorObjectPropertyValue -Object $manifest -Name "bundle_type")

    if ($bundleType -eq "cycle") {
        $sourceType = "cycle"
        Add-CycleBundleArtifacts -CycleBundleManifestPath $sourceManifestPath -ModePrefix "direct"
    } elseif ($bundleType -eq "suite") {
        $sourceType = "suite"
        $suiteContext = Resolve-OperatorSuiteBundleContext `
            -BundleManifestPath $sourceManifestPath `
            -RepoRoot $repoRoot
        Add-ReplayArtifact -Role "suite_bundle_manifest" -Path $suiteContext.manifest_path
        Add-ReplayArtifact -Role "suite_summary" -Path $suiteContext.summary_path
        Add-ReplayArtifact -Role "suite_stage_gate" -Path $suiteContext.stage_gate_path
        Add-ReplayArtifact -Role "suite_handoff_json" -Path $suiteContext.handoff_json_path
        Add-ReplayArtifact -Role "suite_handoff_markdown" -Path $suiteContext.handoff_markdown_path
        foreach ($cycle in @($suiteContext.cycles)) {
            Add-CycleBundleArtifacts `
                -CycleBundleManifestPath ([string]$cycle.bundle_manifest_path) `
                -ModePrefix ([string]$cycle.mode)
        }
    } elseif ($bundleType -eq "readiness") {
        $sourceType = "readiness"
        $readinessContext = Resolve-ReadinessBundleContext `
            -ReadinessManifestPath $sourceManifestPath `
            -RepoRoot $repoRoot
        Add-ReplayArtifact -Role "readiness_manifest" -Path $readinessContext.manifest_path
        Add-ReplayArtifact -Role "readiness_summary" -Path $readinessContext.summary_path
        Add-ReplayArtifact -Role "readiness_live_smoke_log" -Path $readinessContext.live_smoke_log_path
        Add-ReplayArtifact -Role "readiness_seed_log" -Path $readinessContext.seed_log_path
        Add-ReplayArtifact -Role "readiness_openclaw_evidence" -Path $readinessContext.openclaw_evidence_path
        if (-not [string]::IsNullOrWhiteSpace($readinessContext.operator_suite_manifest_path)) {
            $suiteContext = Resolve-OperatorSuiteBundleContext `
                -BundleManifestPath $readinessContext.operator_suite_manifest_path `
                -RepoRoot $repoRoot
            Add-ReplayArtifact -Role "suite_bundle_manifest" -Path $suiteContext.manifest_path
            Add-ReplayArtifact -Role "suite_summary" -Path $suiteContext.summary_path
            Add-ReplayArtifact -Role "suite_stage_gate" -Path $suiteContext.stage_gate_path
            Add-ReplayArtifact -Role "suite_handoff_json" -Path $suiteContext.handoff_json_path
            Add-ReplayArtifact -Role "suite_handoff_markdown" -Path $suiteContext.handoff_markdown_path
            foreach ($cycle in @($suiteContext.cycles)) {
                Add-CycleBundleArtifacts `
                    -CycleBundleManifestPath ([string]$cycle.bundle_manifest_path) `
                    -ModePrefix ([string]$cycle.mode)
            }
        }
    } else {
        Write-Error ("Unsupported bundle_type for replay export: {0}" -f $bundleType)
        exit 1
    }
}

$archiveOutputPath = ""
if ($Zip) {
    $archiveOutputPath = ([string]$ArchivePath).Trim()
    if ([string]::IsNullOrWhiteSpace($archiveOutputPath)) {
        $archiveOutputPath = $resolvedOutputDir.TrimEnd("\") + ".zip"
    } elseif (-not [System.IO.Path]::IsPathRooted($archiveOutputPath)) {
        $archiveOutputPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $archiveOutputPath))
    }
    if (Test-Path $archiveOutputPath) {
        Remove-Item -Path $archiveOutputPath -Force
    }
    Compress-Archive -Path (Join-Path $resolvedOutputDir "*") -DestinationPath $archiveOutputPath -Force
}

$exportManifest = [ordered]@{
    bundle_type = "operator_replay_export"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_type = $sourceType
    source_manifest_path = $sourceManifestPath
    output_dir = $resolvedOutputDir
    archive_path = $archiveOutputPath
    artifact_count = $artifactRecords.Count
    missing_artifact_count = $missingArtifacts.Count
    artifacts = @($artifactRecords.ToArray())
    missing_artifacts = @($missingArtifacts.ToArray())
}

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "replay-export.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutPath))
}
Save-OperatorJson -Payload $exportManifest -OutPath $OutPath

Write-Host "[done] operator-replay-export completed"
Write-Host ("  source_type   : {0}" -f $sourceType)
Write-Host ("  output_dir    : {0}" -f $resolvedOutputDir)
Write-Host ("  artifact_count: {0}" -f $artifactRecords.Count)
if ($missingArtifacts.Count -gt 0) {
    Write-Host ("  missing_count : {0}" -f $missingArtifacts.Count)
}
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive_path  : {0}" -f $archiveOutputPath)
}
Write-Host ("  export_manifest: {0}" -f $OutPath)
