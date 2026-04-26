param(
    [string]$ReleaseCandidateManifestPath = "",
    [string]$ReleaseDecisionManifestPath = "",
    [string]$KnownIssuesPath = "docs/known_issues_register.md",
    [string]$OutputDir = "",
    [string]$OutPath = "",
    [string]$NotesDocPath = "docs/release_note_publication_flow.md"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot "operator-common.ps1")

function Resolve-CandidateManifestPathInternal {
    param([string]$RequestedPath)

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot)
    }

    $latest = Get-ChildItem -Path (Join-Path $repoRoot "logs\release-train") -Recurse -File -Filter "release-candidate.manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw "No release-candidate manifest found under logs/release-train."
    }
    return $latest.FullName
}

function Resolve-DecisionManifestPathInternal {
    param([string]$RequestedPath)

    $requested = ([string]$RequestedPath).Trim()
    if (-not [string]::IsNullOrWhiteSpace($requested)) {
        return (Resolve-OperatorAbsolutePath -Path $requested -BasePath $repoRoot)
    }

    $latest = Get-ChildItem -Path (Join-Path $repoRoot "logs\release-train") -Recurse -File -Filter "release-decision-package.manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw "No release-decision-package manifest found under logs/release-train."
    }
    return $latest.FullName
}

function Get-KnownIssueRows {
    param([string]$Content)

    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($line in $Content -split "`n") {
        $trimmed = $line.Trim()
        if ($trimmed -notlike "| KI-*") {
            continue
        }
        $cells = @($trimmed.Split("|")) | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
        if ($cells.Count -lt 8) {
            continue
        }
        $rows.Add([ordered]@{
            issue_id = [string]$cells[0]
            title = [string]$cells[1]
            severity = ([string]$cells[2]).ToUpperInvariant()
            status = ([string]$cells[3]).ToLowerInvariant()
            owner = [string]$cells[4]
            first_seen_utc = [string]$cells[5]
            workaround = [string]$cells[6]
            next_action = [string]$cells[7]
        }) | Out-Null
    }
    return @($rows.ToArray())
}

$resolvedCandidatePath = Resolve-CandidateManifestPathInternal -RequestedPath $ReleaseCandidateManifestPath
$resolvedDecisionPath = Resolve-DecisionManifestPathInternal -RequestedPath $ReleaseDecisionManifestPath
$resolvedKnownIssuesPath = Resolve-OperatorAbsolutePath -Path $KnownIssuesPath -BasePath $repoRoot

if (-not (Test-Path $resolvedCandidatePath)) {
    Write-Error ("Release candidate manifest not found: {0}" -f $resolvedCandidatePath)
    exit 1
}
if (-not (Test-Path $resolvedDecisionPath)) {
    Write-Error ("Release decision manifest not found: {0}" -f $resolvedDecisionPath)
    exit 1
}

$candidate = Read-OperatorJsonFile -Path $resolvedCandidatePath
$decision = Read-OperatorJsonFile -Path $resolvedDecisionPath
if ([string]$candidate.bundle_type -ne "phase14_release_candidate_promotion") {
    Write-Error "Unexpected release candidate bundle_type."
    exit 1
}
if ([string]$decision.bundle_type -ne "phase14_release_decision_package") {
    Write-Error "Unexpected release decision bundle_type."
    exit 1
}

$knownIssuesContent = if (Test-Path $resolvedKnownIssuesPath) { Get-Content -Raw -Path $resolvedKnownIssuesPath } else { "" }
$knownIssueRows = Get-KnownIssueRows -Content $knownIssuesContent
$knownIssuesForRelease = New-Object System.Collections.Generic.List[object]
foreach ($issue in @($knownIssueRows)) {
    $status = ([string]$issue.status).ToLowerInvariant()
    if ($status -ne "open" -and $status -ne "mitigated") {
        continue
    }
    $severity = ([string]$issue.severity).ToUpperInvariant()
    $knownIssuesForRelease.Add([ordered]@{
        issue_id = [string]$issue.issue_id
        title = [string]$issue.title
        severity = $severity
        status = $status
        release_note_required = ($severity -in @("P0", "P1", "P2"))
        workaround = [string]$issue.workaround
        next_action = [string]$issue.next_action
    }) | Out-Null
}

$resolvedOutputDir = ([string]$OutputDir).Trim()
if ([string]::IsNullOrWhiteSpace($resolvedOutputDir)) {
    $resolvedOutputDir = Join-Path $repoRoot ("logs\release-train\notes-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
} elseif (-not [System.IO.Path]::IsPathRooted($resolvedOutputDir)) {
    $resolvedOutputDir = Resolve-OperatorAbsolutePath -Path $resolvedOutputDir -BasePath $repoRoot
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

if ([string]::IsNullOrWhiteSpace($OutPath)) {
    $OutPath = Join-Path $resolvedOutputDir "release-notes.manifest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($OutPath)) {
    $OutPath = Resolve-OperatorAbsolutePath -Path $OutPath -BasePath $repoRoot
}

$includedCount = @($candidate.included_items).Count
$excludedCount = @($candidate.excluded_items).Count
$openIssueCount = Convert-OperatorToInt -Value $knownIssuesForRelease.Count -Default 0
$decisionValue = [string]$decision.decision
$rollbackSignal = [string]$decision.rollback_signal
$releaseId = [string]$candidate.release_id
$releaseVersion = [string]$candidate.release_version

$notesMarkdownPath = Join-Path $resolvedOutputDir "release-notes.md"
$markdown = New-Object System.Collections.Generic.List[string]
$markdown.Add(("# Release Notes - {0}" -f $releaseVersion)) | Out-Null
$markdown.Add("") | Out-Null
$markdown.Add(("- release_id: {0}" -f $releaseId)) | Out-Null
$markdown.Add(("- decision: {0}" -f $decisionValue)) | Out-Null
$markdown.Add(("- rollback_signal: {0}" -f $rollbackSignal)) | Out-Null
$markdown.Add(("- included_items: {0}" -f $includedCount)) | Out-Null
$markdown.Add(("- excluded_items: {0}" -f $excludedCount)) | Out-Null
$markdown.Add("") | Out-Null
$markdown.Add("## Included scope") | Out-Null
if ($includedCount -eq 0) {
    $markdown.Add("- none") | Out-Null
} else {
    foreach ($item in @($candidate.included_items)) {
        $markdown.Add(("- {0} [{1}] lane={2} score={3}" -f [string]$item.triage_id, [string]$item.category, [string]$item.lane, (Convert-OperatorToInt -Value $item.score -Default 0))) | Out-Null
    }
}
$markdown.Add("") | Out-Null
$markdown.Add("## Deferred or excluded scope") | Out-Null
if ($excludedCount -eq 0) {
    $markdown.Add("- none") | Out-Null
} else {
    foreach ($item in @($candidate.excluded_items)) {
        $markdown.Add(("- {0} [{1}] reason={2}" -f [string]$item.triage_id, [string]$item.category, [string]$item.reason)) | Out-Null
    }
}
$markdown.Add("") | Out-Null
$markdown.Add("## Known issues and workarounds") | Out-Null
if ($openIssueCount -eq 0) {
    $markdown.Add("- none") | Out-Null
} else {
    foreach ($issue in @($knownIssuesForRelease.ToArray())) {
        $markdown.Add(("- {0} {1} [{2}/{3}] workaround={4}" -f [string]$issue.issue_id, [string]$issue.title, [string]$issue.severity, [string]$issue.status, [string]$issue.workaround)) | Out-Null
    }
}
$markdown.Add("") | Out-Null
$markdown.Add("## Operator guidance") | Out-Null
if ($decisionValue -eq "GO") {
    $markdown.Add("- Proceed with release using standard launch checklist.") | Out-Null
} elseif ($decisionValue -eq "ROLLBACK_READY") {
    $markdown.Add("- Proceed with heightened monitoring and rollback readiness.") | Out-Null
} elseif ($decisionValue -eq "ROLLBACK_REQUIRED") {
    $markdown.Add("- Do not proceed without rollback execution and remediation.") | Out-Null
} else {
    $markdown.Add("- Hold release and resolve blocking findings before retry.") | Out-Null
}
[System.IO.File]::WriteAllLines($notesMarkdownPath, $markdown, [System.Text.Encoding]::UTF8)

$payload = [ordered]@{
    bundle_type = "phase14_release_notes_assembly"
    bundle_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    source_release_candidate_manifest_path = $resolvedCandidatePath
    source_release_decision_manifest_path = $resolvedDecisionPath
    source_known_issues_path = $resolvedKnownIssuesPath
    release_id = $releaseId
    release_version = $releaseVersion
    decision = $decisionValue
    rollback_signal = $rollbackSignal
    included_item_count = $includedCount
    excluded_item_count = $excludedCount
    known_issue_count = $openIssueCount
    known_issues = @($knownIssuesForRelease.ToArray())
    release_notes_markdown_path = $notesMarkdownPath
    next_steps = @(
        "1) Route known issues to publication levels (internal/operator/customer/release-note).",
        "2) Export release-train evidence package with candidate, decision, notes, and publication routing.",
        "3) Record representative release-train evidence in staging execution record."
    )
}

Save-OperatorJson -Payload $payload -OutPath $OutPath

if (-not [string]::IsNullOrWhiteSpace($NotesDocPath)) {
    $resolvedDocPath = Resolve-OperatorAbsolutePath -Path $NotesDocPath -BasePath $repoRoot
    $doc = New-Object System.Collections.Generic.List[string]
    $doc.Add("# Release Notes and Known-Issue Publication Flow (Phase 14 / p14_t3)") | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Purpose") | Out-Null
    $doc.Add("Assemble release notes from candidate + decision artifacts and connect known issues to operator/customer publication expectations.") | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Commands") | Out-Null
    $doc.Add('```powershell') | Out-Null
    $doc.Add('.\scripts\release-notes-assemble.ps1') | Out-Null
    $doc.Add('.\scripts\known-issue-publication-route.ps1') | Out-Null
    $doc.Add('```') | Out-Null
    $doc.Add("") | Out-Null
    $doc.Add("## Latest metadata") | Out-Null
    $doc.Add(("- generated_at_utc: {0}" -f $payload.generated_at_utc)) | Out-Null
    $doc.Add(("- release_notes_manifest: {0}" -f (Get-OperatorRelativePath -Path $OutPath -RootPath $repoRoot))) | Out-Null
    $doc.Add(("- release_notes_markdown: {0}" -f (Get-OperatorRelativePath -Path $notesMarkdownPath -RootPath $repoRoot))) | Out-Null
    $doc.Add(("- decision: {0}" -f $decisionValue)) | Out-Null
    $doc.Add(("- rollback_signal: {0}" -f $rollbackSignal)) | Out-Null
    $doc.Add(("- known_issue_count: {0}" -f $openIssueCount)) | Out-Null
    [System.IO.File]::WriteAllLines($resolvedDocPath, $doc, [System.Text.Encoding]::UTF8)
}

Write-Host "[done] release notes assembly completed"
Write-Host ("  source_candidate : {0}" -f $resolvedCandidatePath)
Write-Host ("  source_decision  : {0}" -f $resolvedDecisionPath)
Write-Host ("  known_issues     : {0}" -f $openIssueCount)
Write-Host ("  manifest         : {0}" -f $OutPath)
