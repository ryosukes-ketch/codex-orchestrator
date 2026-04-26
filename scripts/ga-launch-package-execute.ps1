param(
    [string]$BacklogExportManifestPath = "",
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [string]$ReadinessManifestPath = "",
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

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\ga-launch\ga-launch-execution-{0}" -f $timestamp)
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "ga-launch-package.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

if ([string]::IsNullOrWhiteSpace($SummaryOutPath)) {
    $SummaryOutPath = Join-Path $resolvedOutputDir "ga-launch-summary.json"
} elseif (-not [System.IO.Path]::IsPathRooted($SummaryOutPath)) {
    $SummaryOutPath = Resolve-OperatorAbsolutePath -Path $SummaryOutPath -BasePath $repoRoot
}

$candidateManifestPath = Join-Path $resolvedOutputDir "release-candidate.manifest.json"
$decisionManifestPath = Join-Path $resolvedOutputDir "release-decision-package.manifest.json"
$notesManifestPath = Join-Path $resolvedOutputDir "release-notes.manifest.json"
$publicationManifestPath = Join-Path $resolvedOutputDir "known-issue-publication.manifest.json"
$evidenceManifestPath = Join-Path $resolvedOutputDir "release-train-evidence.manifest.json"

$candidateArgs = @{
    OutPath = $candidateManifestPath
    PromotionDocPath = "docs/release_candidate_promotion.md"
}
if (-not [string]::IsNullOrWhiteSpace($BacklogExportManifestPath)) {
    $candidateArgs.BacklogExportManifestPath = $BacklogExportManifestPath
}
if (-not [string]::IsNullOrWhiteSpace($KnownIssuesPath)) {
    $candidateArgs.KnownIssuesPath = $KnownIssuesPath
}
& (Join-Path $PSScriptRoot "release-candidate-promote.ps1") @candidateArgs
if (-not $?) {
    exit 1
}

$decisionArgs = @{
    ReleaseCandidateManifestPath = $candidateManifestPath
    OutPath = $decisionManifestPath
    DecisionDocPath = "docs/release_go_hold_rollback_decision.md"
}
if (-not [string]::IsNullOrWhiteSpace($ReadinessManifestPath)) {
    $decisionArgs.ReadinessManifestPath = $ReadinessManifestPath
}
& (Join-Path $PSScriptRoot "release-decision-package.ps1") @decisionArgs
if (-not $?) {
    exit 1
}

$notesArgs = @{
    ReleaseCandidateManifestPath = $candidateManifestPath
    ReleaseDecisionManifestPath = $decisionManifestPath
    OutPath = $notesManifestPath
    NotesDocPath = "docs/release_note_publication_flow.md"
}
if (-not [string]::IsNullOrWhiteSpace($KnownIssuesPath)) {
    $notesArgs.KnownIssuesPath = $KnownIssuesPath
}
& (Join-Path $PSScriptRoot "release-notes-assemble.ps1") @notesArgs
if (-not $?) {
    exit 1
}

$publicationArgs = @{
    OutPath = $publicationManifestPath
}
if (-not [string]::IsNullOrWhiteSpace($KnownIssuesPath)) {
    $publicationArgs.KnownIssuesPath = $KnownIssuesPath
}
if (Test-Path $decisionManifestPath) {
    $publicationArgs.ReleaseDecisionManifestPath = $decisionManifestPath
}
& (Join-Path $PSScriptRoot "known-issue-publication-route.ps1") @publicationArgs
if (-not $?) {
    exit 1
}

$evidenceArgs = @{
    ReleaseCandidateManifestPath = $candidateManifestPath
    ReleaseDecisionManifestPath = $decisionManifestPath
    ReleaseNotesManifestPath = $notesManifestPath
    KnownIssuePublicationManifestPath = $publicationManifestPath
    OutPath = $evidenceManifestPath
    EvidenceDocPath = "docs/release_train_evidence_flow.md"
}
if ($Zip) {
    $evidenceArgs.Zip = $true
}
if (-not [string]::IsNullOrWhiteSpace($ArchivePath)) {
    $evidenceArgs.ArchivePath = $ArchivePath
}
& (Join-Path $PSScriptRoot "release-train-evidence-export.ps1") @evidenceArgs
if (-not $?) {
    exit 1
}

$candidate = Read-OperatorJsonFile -Path $candidateManifestPath
$decision = Read-OperatorJsonFile -Path $decisionManifestPath
$notes = Read-OperatorJsonFile -Path $notesManifestPath
$publication = Read-OperatorJsonFile -Path $publicationManifestPath
$evidence = Read-OperatorJsonFile -Path $evidenceManifestPath

$summary = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    release_id = [string]$candidate.release_id
    release_version = [string]$candidate.release_version
    decision = [string]$decision.decision
    rollback_signal = [string]$decision.rollback_signal
    included_item_count = Convert-OperatorToInt -Value $candidate.included_items.Count -Default 0
    excluded_item_count = Convert-OperatorToInt -Value $candidate.excluded_items.Count -Default 0
    hold_reason_count = Convert-OperatorToInt -Value $candidate.hold_reasons.Count -Default 0
    known_issue_count = Convert-OperatorToInt -Value $notes.known_issue_count -Default 0
    blocker_launch_hold_count = Convert-OperatorToInt -Value $publication.route_counts.blocker_launch_hold -Default 0
}
Save-OperatorJson -Payload $summary -OutPath $SummaryOutPath

$markdownPath = Join-Path $resolvedOutputDir "ga-launch-summary.md"
$markdown = New-Object System.Collections.Generic.List[string]
$markdown.Add("# GA Launch Package Execution Summary") | Out-Null
$markdown.Add("") | Out-Null
$markdown.Add(("- generated_at_utc: {0}" -f $summary.generated_at_utc)) | Out-Null
$markdown.Add(("- release_id: {0}" -f $summary.release_id)) | Out-Null
$markdown.Add(("- release_version: {0}" -f $summary.release_version)) | Out-Null
$markdown.Add(("- decision: {0}" -f $summary.decision)) | Out-Null
$markdown.Add(("- rollback_signal: {0}" -f $summary.rollback_signal)) | Out-Null
$markdown.Add(("- included_item_count: {0}" -f $summary.included_item_count)) | Out-Null
$markdown.Add(("- known_issue_count: {0}" -f $summary.known_issue_count)) | Out-Null
$markdown.Add("") | Out-Null
$markdown.Add("## Artifacts") | Out-Null
$markdown.Add(("- release_candidate_manifest: {0}" -f (Get-OperatorRelativePath -Path $candidateManifestPath -RootPath $repoRoot))) | Out-Null
$markdown.Add(("- release_decision_manifest: {0}" -f (Get-OperatorRelativePath -Path $decisionManifestPath -RootPath $repoRoot))) | Out-Null
$markdown.Add(("- release_notes_manifest: {0}" -f (Get-OperatorRelativePath -Path $notesManifestPath -RootPath $repoRoot))) | Out-Null
$markdown.Add(("- known_issue_publication_manifest: {0}" -f (Get-OperatorRelativePath -Path $publicationManifestPath -RootPath $repoRoot))) | Out-Null
$markdown.Add(("- release_train_evidence_manifest: {0}" -f (Get-OperatorRelativePath -Path $evidenceManifestPath -RootPath $repoRoot))) | Out-Null
[System.IO.File]::WriteAllLines($markdownPath, $markdown, [System.Text.Encoding]::UTF8)

$manifest = [ordered]@{
    bundle_type = "phase15_ga_launch_execution_package"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    output_dir = $resolvedOutputDir
    summary = $summary
    artifacts = [ordered]@{
        release_candidate_manifest = New-OperatorManifestArtifactEntry -Path $candidateManifestPath -RepoRoot $repoRoot
        release_decision_manifest = New-OperatorManifestArtifactEntry -Path $decisionManifestPath -RepoRoot $repoRoot
        release_notes_manifest = New-OperatorManifestArtifactEntry -Path $notesManifestPath -RepoRoot $repoRoot
        known_issue_publication_manifest = New-OperatorManifestArtifactEntry -Path $publicationManifestPath -RepoRoot $repoRoot
        release_train_evidence_manifest = New-OperatorManifestArtifactEntry -Path $evidenceManifestPath -RepoRoot $repoRoot
        ga_launch_summary_json = New-OperatorManifestArtifactEntry -Path $SummaryOutPath -RepoRoot $repoRoot
        ga_launch_summary_markdown = New-OperatorManifestArtifactEntry -Path $markdownPath -RepoRoot $repoRoot
    }
    next_steps = @(
        "1) Record GA launch execution evidence in staging execution record.",
        "2) Run early-operations incident loop and update known issue routing.",
        "3) Route launch-week incidents into hotfix/next-release decision package."
    )
}

Save-OperatorJson -Payload $manifest -OutPath $OutPath

Write-Host "[done] ga launch package execution completed"
Write-Host ("  decision      : {0}" -f $summary.decision)
Write-Host ("  release_id    : {0}" -f $summary.release_id)
Write-Host ("  summary_json  : {0}" -f $SummaryOutPath)
Write-Host ("  manifest      : {0}" -f $OutPath)
