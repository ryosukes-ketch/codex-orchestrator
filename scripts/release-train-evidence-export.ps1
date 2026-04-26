param(
    [string]$ReleaseCandidateManifestPath = "",
    [string]$ReleaseDecisionManifestPath = "",
    [string]$ReleaseNotesManifestPath = "",
    [string]$KnownIssuePublicationManifestPath = "",
    [string]$OutputDir = "",
    [switch]$Zip,
    [string]$ArchivePath = "",
    [string]$OutPath = "",
    [string]$EvidenceDocPath = "docs/release_train_evidence_flow.md"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-LatestReleaseTrainManifestPath {
    param(
        [string]$RequestedPath,
        [string]$Filter
    )

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot)
    }

    $latest = Get-ChildItem -Path (Join-Path $repoRoot "logs\release-train") -Recurse -File -Filter $Filter |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw ("No {0} manifest found under logs/release-train." -f $Filter)
    }
    return $latest.FullName
}

$resolvedCandidatePath = Resolve-LatestReleaseTrainManifestPath -RequestedPath $ReleaseCandidateManifestPath -Filter "release-candidate.manifest.json"
$resolvedDecisionPath = Resolve-LatestReleaseTrainManifestPath -RequestedPath $ReleaseDecisionManifestPath -Filter "release-decision-package.manifest.json"
$resolvedNotesPath = Resolve-LatestReleaseTrainManifestPath -RequestedPath $ReleaseNotesManifestPath -Filter "release-notes.manifest.json"
$resolvedPublicationPath = Resolve-LatestReleaseTrainManifestPath -RequestedPath $KnownIssuePublicationManifestPath -Filter "known-issue-publication.manifest.json"

foreach ($path in @($resolvedCandidatePath, $resolvedDecisionPath, $resolvedNotesPath, $resolvedPublicationPath)) {
    if (-not (Test-Path $path)) {
        Write-Error ("Required release-train artifact not found: {0}" -f $path)
        exit 1
    }
}

$candidate = Read-OperatorJsonFile -Path $resolvedCandidatePath
$decision = Read-OperatorJsonFile -Path $resolvedDecisionPath
$notes = Read-OperatorJsonFile -Path $resolvedNotesPath
$publication = Read-OperatorJsonFile -Path $resolvedPublicationPath

if ([string]$candidate.bundle_type -ne "phase14_release_candidate_promotion") {
    Write-Error "Unexpected candidate bundle_type."
    exit 1
}
if ([string]$decision.bundle_type -ne "phase14_release_decision_package") {
    Write-Error "Unexpected decision bundle_type."
    exit 1
}
if ([string]$notes.bundle_type -ne "phase14_release_notes_assembly") {
    Write-Error "Unexpected release notes bundle_type."
    exit 1
}
if ([string]$publication.bundle_type -ne "phase14_known_issue_publication_routing") {
    Write-Error "Unexpected known issue publication bundle_type."
    exit 1
}

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\release-train\evidence-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "release-train-evidence.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

$summary = [ordered]@{
    release_id = [string]$candidate.release_id
    release_version = [string]$candidate.release_version
    decision = [string]$decision.decision
    rollback_signal = [string]$decision.rollback_signal
    included_item_count = Convert-OperatorToInt -Value $candidate.included_items.Count -Default 0
    excluded_item_count = Convert-OperatorToInt -Value $candidate.excluded_items.Count -Default 0
    known_issue_count = Convert-OperatorToInt -Value $notes.known_issue_count -Default 0
    publication_blocker_launch_hold = Convert-OperatorToInt -Value $publication.route_counts.blocker_launch_hold -Default 0
}

$evidenceMarkdownPath = Join-Path $resolvedOutputDir "release-train-evidence.md"
$markdown = New-Object System.Collections.Generic.List[string]
$markdown.Add("# Release Train Evidence Export") | Out-Null
$markdown.Add("") | Out-Null
$markdown.Add(("- generated_at_utc: {0}" -f [DateTime]::UtcNow.ToString("o"))) | Out-Null
$markdown.Add(("- release_id: {0}" -f $summary.release_id)) | Out-Null
$markdown.Add(("- release_version: {0}" -f $summary.release_version)) | Out-Null
$markdown.Add(("- decision: {0}" -f $summary.decision)) | Out-Null
$markdown.Add(("- rollback_signal: {0}" -f $summary.rollback_signal)) | Out-Null
$markdown.Add("") | Out-Null
$markdown.Add("## Included artifacts") | Out-Null
$markdown.Add(("- release_candidate_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedCandidatePath -RootPath $repoRoot))) | Out-Null
$markdown.Add(("- release_decision_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedDecisionPath -RootPath $repoRoot))) | Out-Null
$markdown.Add(("- release_notes_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedNotesPath -RootPath $repoRoot))) | Out-Null
$markdown.Add(("- known_issue_publication_manifest: {0}" -f (Get-OperatorRelativePath -Path $resolvedPublicationPath -RootPath $repoRoot))) | Out-Null
[System.IO.File]::WriteAllLines($evidenceMarkdownPath, $markdown, [System.Text.Encoding]::UTF8)

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

$payload = [ordered]@{
    bundle_type = "phase14_release_train_evidence"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    output_dir = $resolvedOutputDir
    summary = $summary
    artifacts = [ordered]@{
        release_candidate_manifest = New-OperatorManifestArtifactEntry -Path $resolvedCandidatePath -RepoRoot $repoRoot
        release_decision_manifest = New-OperatorManifestArtifactEntry -Path $resolvedDecisionPath -RepoRoot $repoRoot
        release_notes_manifest = New-OperatorManifestArtifactEntry -Path $resolvedNotesPath -RepoRoot $repoRoot
        known_issue_publication_manifest = New-OperatorManifestArtifactEntry -Path $resolvedPublicationPath -RepoRoot $repoRoot
        evidence_markdown = New-OperatorManifestArtifactEntry -Path $evidenceMarkdownPath -RepoRoot $repoRoot
    }
    archive_path = $archiveOutputPath
    next_steps = @(
        "1) Record release-train evidence in staging execution record.",
        "2) Use decision + publication routes during go/hold/rollback meeting.",
        "3) Sync release-train docs and roadmap closeout status."
    )
}

Save-OperatorJson -Payload $payload -OutPath $OutPath

if (-not [string]::IsNullOrWhiteSpace($EvidenceDocPath)) {
    $resolvedDocPath = Resolve-OperatorAbsolutePath -Path $EvidenceDocPath -BasePath $repoRoot
    $doc = New-Object System.Collections.Generic.List[string]
    $doc.Add("# Release Train Evidence Flow (Phase 14 / p14_t4)") | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Purpose") | Out-Null
    $doc.Add("Export release candidate promotion, decision package, release notes, and known-issue publication routing into one evidence bundle.") | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Command") | Out-Null
    $doc.Add('```powershell') | Out-Null
    $doc.Add('.\scripts\release-train-evidence-export.ps1 -Zip') | Out-Null
    $doc.Add('```') | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Latest metadata") | Out-Null
    $doc.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
    $doc.Add(("- evidence_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
    $doc.Add(("- evidence_markdown: {0}" -f (Get-OperatorRelativePath -Path $evidenceMarkdownPath -RootPath $repoRoot))) | Out-Null
    $doc.Add(("- decision: {0}" -f $summary.decision)) | Out-Null
    $doc.Add(("- rollback_signal: {0}" -f $summary.rollback_signal)) | Out-Null
    if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
        $doc.Add(("- archive_path: {0}" -f (Get-OperatorRelativePath -Path $archiveOutputPath -RootPath $repoRoot))) | Out-Null
    }
    [System.IO.File]::WriteAllLines($resolvedDocPath, $doc, [System.Text.Encoding]::UTF8)
}

Write-Host "[done] release-train evidence export completed"
Write-Host ("  decision                : {0}" -f $summary.decision)
Write-Host ("  release_id              : {0}" -f $summary.release_id)
Write-Host ("  manifest                : {0}" -f $OutPath)
if (-not [string]::IsNullOrWhiteSpace($archiveOutputPath)) {
    Write-Host ("  archive                 : {0}" -f $archiveOutputPath)
}
