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

if (
    -not [string]::IsNullOrWhiteSpace($ReadinessManifestPath) `
        -and -not [string]::IsNullOrWhiteSpace($BundleManifestPath)
) {
    Write-Error "Specify only one of -ReadinessManifestPath or -BundleManifestPath."
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\support-bundles\{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $resolvedOutputDir))
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

$replayExportDir = Join-Path $resolvedOutputDir "replay-export"
$replayExportManifestPath = Join-Path $resolvedOutputDir "replay-export.manifest.json"
$replayArgs = @{
    OutputDir = $replayExportDir
    OutPath = $replayExportManifestPath
}
if (-not [string]::IsNullOrWhiteSpace($ReadinessManifestPath)) {
    $replayArgs.ReadinessManifestPath = $ReadinessManifestPath
}
if (-not [string]::IsNullOrWhiteSpace($BundleManifestPath)) {
    $replayArgs.BundleManifestPath = $BundleManifestPath
}

& (Join-Path $PSScriptRoot "operator-replay-export.ps1") @replayArgs
if (-not $?) {
    exit 1
}

$replayManifest = Read-OperatorJsonFile -Path $replayExportManifestPath
$sourceType = [string]$replayManifest.source_type
$sourceManifestPath = [string]$replayManifest.source_manifest_path

$findings = New-Object System.Collections.Generic.List[object]
$findingSignatures = New-Object System.Collections.Generic.HashSet[string]

function Get-ClassificationCategory {
    param([string]$Text)

    $value = ([string]$Text).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($value)) {
        return "unknown"
    }

    if (
        $value.Contains("allowlist") `
            -or $value.Contains("auth evidence") `
            -or $value.Contains("auth role") `
            -or $value.Contains("policy") `
            -or $value.Contains("override mismatch") `
            -or $value.Contains("breakglass")
    ) {
        return "policy"
    }

    if (
        $value.Contains("credit") `
            -or $value.Contains("unauthorized") `
            -or $value.Contains("forbidden") `
            -or $value.Contains("auth token") `
            -or $value.Contains("upstream_rejection")
    ) {
        return "provider_auth"
    }

    if (
        $value.Contains("non_json") `
            -or $value.Contains("missing_required_keys") `
            -or $value.Contains("changes_requested")
    ) {
        return "semantic_output"
    }

    if (
        $value.Contains("sqlite") `
            -or $value.Contains("database") `
            -or $value.Contains("restore") `
            -or $value.Contains("backup") `
            -or $value.Contains("persistence")
    ) {
        return "persistence_restore"
    }

    if (
        $value.Contains("waiting_approval") `
            -or $value.Contains("revision_requested") `
            -or $value.Contains("cannot reject") `
            -or $value.Contains("state transition") `
            -or $value.Contains("project not found")
    ) {
        return "operator_flow"
    }

    if (
        $value.Contains("timeout") `
            -or $value.Contains("runtimeerror") `
            -or $value.Contains("llm_exception") `
            -or $value.Contains("connection") `
            -or $value.Contains("endpoint")
    ) {
        return "runtime"
    }

    return "runtime"
}

function Add-Finding {
    param(
        [string]$Category,
        [string]$Severity,
        [string]$Source,
        [string]$Message,
        [string]$ArtifactPath = ""
    )

    if ([string]::IsNullOrWhiteSpace($Message)) {
        return
    }

    $normalizedCategory = if ([string]::IsNullOrWhiteSpace($Category)) { "unknown" } else { $Category }
    $normalizedSeverity = if ([string]::IsNullOrWhiteSpace($Severity)) { "error" } else { $Severity }
    $signature = "{0}|{1}|{2}|{3}" -f $normalizedCategory, $normalizedSeverity, $Source, $Message
    if ($findingSignatures.Contains($signature)) {
        return
    }
    $findingSignatures.Add($signature) | Out-Null

    $artifactEntry = $null
    if (-not [string]::IsNullOrWhiteSpace($ArtifactPath)) {
        $artifactEntry = New-OperatorManifestArtifactEntry -Path $ArtifactPath -RepoRoot $repoRoot
    }

    $findings.Add([ordered]@{
        category = $normalizedCategory
        severity = $normalizedSeverity
        source = $Source
        message = $Message
        artifact = $artifactEntry
    }) | Out-Null
}

function Add-CycleSummaryFindings {
    param(
        [object]$Summary,
        [string]$Role,
        [string]$ArtifactPath
    )

    $mode = [string]$Summary.mode
    $status = [string]$Summary.final_status
    if (-not [string]::IsNullOrWhiteSpace($status) -and $status -ne "completed") {
        Add-Finding `
            -Category "operator_flow" `
            -Severity "error" `
            -Source ("{0}:cycle_summary" -f $Role) `
            -Message ("cycle final status is [{0}] (expected completed) mode={1}" -f $status, $mode) `
            -ArtifactPath $ArtifactPath
    }

    $llmFallbacks = Convert-OperatorToInt -Value $Summary.stage_llm_transport_fallbacks -Default 0
    if ($llmFallbacks -gt 0) {
        Add-Finding `
            -Category "runtime" `
            -Severity "warning" `
            -Source ("{0}:cycle_summary" -f $Role) `
            -Message ("llm transport fallbacks observed: {0}" -f $llmFallbacks) `
            -ArtifactPath $ArtifactPath
    }
}

function Add-AuditAssertFindings {
    param(
        [object]$AuditAssert,
        [string]$Role,
        [string]$ArtifactPath
    )

    foreach ($reason in @($AuditAssert.errors)) {
        $message = [string]$reason
        if ([string]::IsNullOrWhiteSpace($message)) {
            continue
        }
        Add-Finding `
            -Category (Get-ClassificationCategory -Text $message) `
            -Severity "error" `
            -Source ("{0}:audit_assert" -f $Role) `
            -Message $message `
            -ArtifactPath $ArtifactPath
    }
}

function Add-StageReportFindings {
    param(
        [object]$StageReport,
        [string]$Role,
        [string]$ArtifactPath
    )

    foreach ($stage in @($StageReport.failing_stages)) {
        $department = [string]$stage.department
        $stageName = [string]$stage.stage_name
        foreach ($reason in @($stage.failure_reasons)) {
            $reasonText = [string]$reason
            if ([string]::IsNullOrWhiteSpace($reasonText)) {
                continue
            }
            $message = "{0}:{1} failure reason [{2}]" -f $department, $stageName, $reasonText
            Add-Finding `
                -Category (Get-ClassificationCategory -Text $reasonText) `
                -Severity "error" `
                -Source ("{0}:stage_report" -f $Role) `
                -Message $message `
                -ArtifactPath $ArtifactPath
        }
    }

    $telemetrySource = [string]$StageReport.telemetry_source
    if ([string]::IsNullOrWhiteSpace($telemetrySource)) {
        $telemetrySource = [string]$StageReport.telemetry.telemetry_source
    }
    if ($telemetrySource -eq "none") {
        Add-Finding `
            -Category "runtime" `
            -Severity "warning" `
            -Source ("{0}:stage_report" -f $Role) `
            -Message "stage telemetry source resolved to none" `
            -ArtifactPath $ArtifactPath
    }
}

function Add-StageGateFindings {
    param(
        [object]$StageGate,
        [string]$Role,
        [string]$ArtifactPath
    )

    foreach ($reason in @($StageGate.deny_reasons)) {
        $message = [string]$reason
        if ([string]::IsNullOrWhiteSpace($message)) {
            continue
        }
        Add-Finding `
            -Category (Get-ClassificationCategory -Text $message) `
            -Severity "error" `
            -Source ("{0}:stage_gate" -f $Role) `
            -Message $message `
            -ArtifactPath $ArtifactPath
    }

    foreach ($violation in @($StageGate.violations)) {
        $message = [string]$violation
        if ([string]::IsNullOrWhiteSpace($message)) {
            continue
        }
        Add-Finding `
            -Category (Get-ClassificationCategory -Text $message) `
            -Severity "error" `
            -Source ("{0}:stage_gate" -f $Role) `
            -Message $message `
            -ArtifactPath $ArtifactPath
    }
}

function Add-OpenClawEvidenceFindings {
    param(
        [object]$Evidence,
        [string]$Role,
        [string]$ArtifactPath
    )

    if ([bool]$Evidence.gateway_response_success -ne $true) {
        Add-Finding `
            -Category "runtime" `
            -Severity "error" `
            -Source ("{0}:openclaw_evidence" -f $Role) `
            -Message ("gateway_response_success=false status_code={0} endpoint={1}" -f [string]$Evidence.status_code, [string]$Evidence.used_endpoint) `
            -ArtifactPath $ArtifactPath
    }

    if ([bool]$Evidence.upstream_rejection_detected -eq $true) {
        $reason = [string]$Evidence.upstream_rejection_reason
        $provider = [string]$Evidence.upstream_provider
        Add-Finding `
            -Category "provider_auth" `
            -Severity "error" `
            -Source ("{0}:openclaw_evidence" -f $Role) `
            -Message ("upstream rejection provider={0} reason={1}" -f $provider, $reason) `
            -ArtifactPath $ArtifactPath
    }

    if ([bool]$Evidence.backend_override_provider_mismatch -eq $true) {
        Add-Finding `
            -Category "policy" `
            -Severity "error" `
            -Source ("{0}:openclaw_evidence" -f $Role) `
            -Message ("backend override mismatch requested={0} upstream={1}" -f [string]$Evidence.backend_override_provider, [string]$Evidence.upstream_provider) `
            -ArtifactPath $ArtifactPath
    }
}

foreach ($entry in @($replayManifest.artifacts)) {
    $role = [string]$entry.role
    $artifactPath = [string]$entry.source_path
    if ([string]::IsNullOrWhiteSpace($artifactPath) -or -not (Test-Path $artifactPath)) {
        continue
    }

    if ($role -like "cycle_*_summary" -or $role -eq "cycle_direct_summary") {
        $summaryPayload = Read-OperatorJsonFile -Path $artifactPath
        Add-CycleSummaryFindings -Summary $summaryPayload -Role $role -ArtifactPath $artifactPath
        continue
    }

    if ($role -like "cycle_*_audit_assert" -or $role -eq "cycle_direct_audit_assert") {
        $auditAssertPayload = Read-OperatorJsonFile -Path $artifactPath
        Add-AuditAssertFindings -AuditAssert $auditAssertPayload -Role $role -ArtifactPath $artifactPath
        continue
    }

    if ($role -like "cycle_*_stage_report" -or $role -eq "cycle_direct_stage_report") {
        $stageReportPayload = Read-OperatorJsonFile -Path $artifactPath
        Add-StageReportFindings -StageReport $stageReportPayload -Role $role -ArtifactPath $artifactPath
        continue
    }

    if ($role -eq "suite_stage_gate") {
        $stageGatePayload = Read-OperatorJsonFile -Path $artifactPath
        Add-StageGateFindings -StageGate $stageGatePayload -Role $role -ArtifactPath $artifactPath
        continue
    }

    if ($role -eq "readiness_openclaw_evidence") {
        $openclawEvidencePayload = Read-OperatorJsonFile -Path $artifactPath
        Add-OpenClawEvidenceFindings -Evidence $openclawEvidencePayload -Role $role -ArtifactPath $artifactPath
    }
}

foreach ($missing in @($replayManifest.missing_artifacts)) {
    $missingRole = [string]$missing.role
    $missingPath = [string]$missing.source_path
    Add-Finding `
        -Category "runtime" `
        -Severity "warning" `
        -Source "replay_export:missing_artifact" `
        -Message ("missing artifact role={0} path={1}" -f $missingRole, $missingPath)
}

$categoryCounts = [ordered]@{
    runtime = 0
    provider_auth = 0
    policy = 0
    semantic_output = 0
    persistence_restore = 0
    operator_flow = 0
    unknown = 0
}

$severityCounts = [ordered]@{
    error = 0
    warning = 0
    info = 0
}

foreach ($finding in @($findings.ToArray())) {
    $category = [string]$finding.category
    if (-not $categoryCounts.Contains($category)) {
        $categoryCounts[$category] = 0
    }
    $categoryCounts[$category] = [int]$categoryCounts[$category] + 1

    $severity = [string]$finding.severity
    if (-not $severityCounts.Contains($severity)) {
        $severityCounts[$severity] = 0
    }
    $severityCounts[$severity] = [int]$severityCounts[$severity] + 1
}

$hasBlockingFindings = ([int]$severityCounts.error -gt 0)
$classificationStatus = if ($hasBlockingFindings) { "issues_detected" } else { "no_blocking_issues" }

$nextSteps = @(
    "1) Confirm support-bundle source manifest and replay-export artifacts are complete.",
    "2) If category=policy, inspect suite-stage-gate deny_reasons and cycle audit_assert errors first.",
    "3) If category=semantic_output or runtime, inspect cycle stage-report failure_reasons and department_stage_executed metadata.",
    "4) If category=provider_auth, inspect readiness_openclaw_evidence upstream provider/rejection fields and gateway token/config.",
    "5) If category=persistence_restore, run sqlite-verify -> sqlite-backup -> sqlite-restore checks before rerunning readiness/operator suite."
)

$supportBundle = [ordered]@{
    bundle_type = "pilot_support_bundle"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_type = $sourceType
    source_manifest_path = $sourceManifestPath
    replay_export_manifest_path = $replayExportManifestPath
    output_dir = $resolvedOutputDir
    classification_status = $classificationStatus
    has_blocking_findings = $hasBlockingFindings
    category_counts = $categoryCounts
    severity_counts = $severityCounts
    finding_count = $findings.Count
    findings = @($findings.ToArray())
    next_steps = $nextSteps
    environment = [ordered]@{
        generated_by = "operator-support-bundle.ps1"
        machine_name = $env:COMPUTERNAME
        user_name = $env:USERNAME
        state_backend = [System.Environment]::GetEnvironmentVariable("STATE_BACKEND", "Process")
        sqlite_db_path = [System.Environment]::GetEnvironmentVariable("SQLITE_DB_PATH", "Process")
        sqlite_backup_dir = [System.Environment]::GetEnvironmentVariable("SQLITE_BACKUP_DIR", "Process")
        openclaw_base_url = [System.Environment]::GetEnvironmentVariable("OPENCLAW_BASE_URL", "Process")
        operator_api_timeout_seconds = [System.Environment]::GetEnvironmentVariable("OPERATOR_API_TIMEOUT_SECONDS", "Process")
    }
}

$classificationReportPath = Join-Path $resolvedOutputDir "failure-classification.json"
Save-OperatorJson -Payload $supportBundle -OutPath $classificationReportPath

$classificationMarkdownPath = Join-Path $resolvedOutputDir "failure-classification.md"
$mdLines = New-Object System.Collections.Generic.List[string]
$mdLines.Add("# Pilot Support Bundle Failure Classification") | Out-Null
$mdLines.Add("") | Out-Null
$mdLines.Add(("- generated_at_utc: {0}" -f $supportBundle.generated_at_utc)) | Out-Null
$mdLines.Add(("- source_type: {0}" -f $sourceType)) | Out-Null
$mdLines.Add(("- source_manifest_path: {0}" -f $sourceManifestPath)) | Out-Null
$mdLines.Add(("- replay_export_manifest_path: {0}" -f $replayExportManifestPath)) | Out-Null
$mdLines.Add(("- classification_status: {0}" -f $classificationStatus)) | Out-Null
$mdLines.Add("") | Out-Null
$mdLines.Add("## Category counts") | Out-Null
foreach ($kv in $categoryCounts.GetEnumerator()) {
    $mdLines.Add(("- {0}: {1}" -f $kv.Key, [int]$kv.Value)) | Out-Null
}
$mdLines.Add("") | Out-Null
$mdLines.Add("## Severity counts") | Out-Null
foreach ($kv in $severityCounts.GetEnumerator()) {
    $mdLines.Add(("- {0}: {1}" -f $kv.Key, [int]$kv.Value)) | Out-Null
}
$mdLines.Add("") | Out-Null
$mdLines.Add("## Findings") | Out-Null
if ($findings.Count -eq 0) {
    $mdLines.Add("- none") | Out-Null
} else {
    foreach ($finding in @($findings.ToArray())) {
        $artifactPath = ""
        if ($finding.artifact -and $finding.artifact.path) {
            $artifactPath = [string]$finding.artifact.path
        }
        if ([string]::IsNullOrWhiteSpace($artifactPath)) {
            $mdLines.Add(("- [{0}/{1}] {2} :: {3}" -f [string]$finding.category, [string]$finding.severity, [string]$finding.source, [string]$finding.message)) | Out-Null
        } else {
            $mdLines.Add(("- [{0}/{1}] {2} :: {3} (`{4}`)" -f [string]$finding.category, [string]$finding.severity, [string]$finding.source, [string]$finding.message, $artifactPath)) | Out-Null
        }
    }
}
$mdLines.Add("") | Out-Null
$mdLines.Add("## Next steps") | Out-Null
foreach ($step in $nextSteps) {
    $mdLines.Add(("- {0}" -f $step)) | Out-Null
}
$mdLines.Add("") | Out-Null
$mdLines.Add("## Failure categories (pilot guidance)") | Out-Null
$mdLines.Add("- runtime: timeouts, endpoint issues, transport/runtime exceptions.") | Out-Null
$mdLines.Add("- provider_auth: upstream rejection, credit/auth/provider access limits.") | Out-Null
$mdLines.Add("- policy: allowlist/auth evidence/backend override mismatch/breakglass policy violations.") | Out-Null
$mdLines.Add("- semantic_output: non-JSON/missing required keys/review changes_requested stop conditions.") | Out-Null
$mdLines.Add("- persistence_restore: sqlite backup/restore/verify/export failures.") | Out-Null
$mdLines.Add("- operator_flow: lifecycle status/transition issues in approval/reject/revision/replan paths.") | Out-Null
[System.IO.File]::WriteAllLines($classificationMarkdownPath, $mdLines, [System.Text.Encoding]::UTF8)

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

$manifestOut = [ordered]@{
    bundle_type = "pilot_support_bundle_manifest"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_type = $sourceType
    source_manifest_path = $sourceManifestPath
    replay_export_manifest_path = $replayExportManifestPath
    failure_classification_json_path = $classificationReportPath
    failure_classification_markdown_path = $classificationMarkdownPath
    output_dir = $resolvedOutputDir
    archive_path = $archiveOutputPath
    classification_status = $classificationStatus
    finding_count = $findings.Count
    has_blocking_findings = $hasBlockingFindings
    category_counts = $categoryCounts
    severity_counts = $severityCounts
}

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "support-bundle.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutPath))
}
Save-OperatorJson -Payload $manifestOut -OutPath $OutPath

Write-Host "[done] operator-support-bundle completed"
Write-Host ("  source_type     : {0}" -f $sourceType)
Write-Host ("  output_dir      : {0}" -f $resolvedOutputDir)
Write-Host ("  finding_count   : {0}" -f $findings.Count)
Write-Host ("  blocking_issues : {0}" -f $hasBlockingFindings)
Write-Host ("  class_json      : {0}" -f $classificationReportPath)
Write-Host ("  class_markdown  : {0}" -f $classificationMarkdownPath)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive_path    : {0}" -f $archiveOutputPath)
}
Write-Host ("  manifest        : {0}" -f $OutPath)
