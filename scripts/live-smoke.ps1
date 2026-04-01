param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$ProjectId = "",
    [int]$TimeoutSec = 15,
    [switch]$SkipPreflight,
    [switch]$NoRuff
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$ruffExe = Join-Path $repoRoot ".venv\Scripts\ruff.exe"
if (-not (Test-Path $ruffExe)) { $ruffExe = "ruff" }

function Invoke-CurlJson {
    param(
        [string]$Method,
        [string]$Url,
        [string]$JsonBody = ""
    )

    $args = @("-sS", "-X", $Method, $Url, "-H", "Content-Type: application/json", "-w", "`n__STATUS__:%{http_code}")
    if ($JsonBody -ne "") {
        $args += @("-d", $JsonBody)
    }

    $output = & curl.exe @args
    if ($LASTEXITCODE -ne 0) {
        throw "curl failed for $Method $Url"
    }

    $lines = @($output -split "`r?`n")
    if ($lines.Count -eq 0) {
        throw "No response for $Method $Url"
    }

    $statusLine = $lines[-1]
    if ($statusLine -notmatch "^__STATUS__:(\d+)$") {
        throw "Could not parse status line for $Method $Url: $statusLine"
    }

    $statusCode = [int]$Matches[1]
    $bodyText = ""
    if ($lines.Count -gt 1) {
        $bodyText = ($lines[0..($lines.Count - 2)] -join "`n")
    }

    [pscustomobject]@{
        StatusCode = $statusCode
        BodyText = $bodyText
    }
}

if (-not $SkipPreflight) {
    & (Join-Path $repoRoot "scripts\preflight.ps1") -ApiBaseUrl $ApiBaseUrl -TimeoutSec $TimeoutSec
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$healthUrl = $ApiBaseUrl.TrimEnd("/") + "/health"
Write-Host "[1/3] live health"
$health = Invoke-CurlJson -Method "GET" -Url $healthUrl
if ($health.StatusCode -ne 200) {
    Write-Error ("Health endpoint returned {0}: {1}" -f $health.StatusCode, $health.BodyText)
    exit 1
}
if ($health.BodyText -notmatch '"status"\s*:\s*"ok"') {
    Write-Error ("Unexpected health payload: {0}" -f $health.BodyText)
    exit 1
}

$routes = @(
    [pscustomobject]@{ Name = "resume-approval"; Path = "/orchestrator/resume/approval" },
    [pscustomobject]@{ Name = "approval-reject"; Path = "/orchestrator/approval/reject" },
    [pscustomobject]@{ Name = "resume-revision"; Path = "/orchestrator/resume/revision" },
    [pscustomobject]@{ Name = "replanning-start"; Path = "/orchestrator/replanning/start" }
)

Write-Host "[2/3] schema-level live contract"
foreach ($route in $routes) {
    $url = $ApiBaseUrl.TrimEnd("/") + $route.Path
    $response = Invoke-CurlJson -Method "POST" -Url $url -JsonBody "{}"

    if ($response.StatusCode -notin @(400, 401, 404, 409, 422)) {
        Write-Error ("Unexpected schema response for {0}: {1} {2}" -f $route.Name, $response.StatusCode, $response.BodyText)
        exit 1
    }

    if ($response.StatusCode -eq 422) {
        if (($response.BodyText -notmatch "project_id") -and ($response.BodyText -notmatch "Field required")) {
            Write-Error ("422 without expected project_id hint for {0}: {1}" -f $route.Name, $response.BodyText)
            exit 1
        }
    }

    Write-Host ("  [ok] {0} -> {1}" -f $route.Name, $response.StatusCode)
}

Write-Host "[3/3] project-id live requests"
if ([string]::IsNullOrWhiteSpace($ProjectId)) {
    Write-Host "  [skip] No -ProjectId supplied; real flow calls skipped"
} else {
    foreach ($route in $routes) {
        $url = $ApiBaseUrl.TrimEnd("/") + $route.Path
        $body = @{ project_id = $ProjectId } | ConvertTo-Json -Compress
        $response = Invoke-CurlJson -Method "POST" -Url $url -JsonBody $body

        if ($response.StatusCode -ge 500) {
            Write-Error ("Server error for {0}: {1} {2}" -f $route.Name, $response.StatusCode, $response.BodyText)
            exit 1
        }

        Write-Host ("  [ok] {0} -> {1}" -f $route.Name, $response.StatusCode)
    }
}

if (-not $NoRuff) {
    & $ruffExe "check" "scripts" "README.md"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "[done] live smoke passed"
