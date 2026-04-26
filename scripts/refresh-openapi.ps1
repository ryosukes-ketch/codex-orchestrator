param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$OutputPath = "openapi.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$url = $ApiBaseUrl.TrimEnd("/") + "/openapi.json"
Write-Host "[refresh-openapi] GET $url"

$response = curl.exe -sS -X GET $url `
    -w "`n__STATUS__:%{http_code}"

$lines = @($response -split "`r?`n")
$statusLine = $lines[-1]
if ($statusLine -notmatch "^__STATUS__:(\d+)$") {
    Write-Error "Could not parse HTTP status: $statusLine"
    exit 1
}
$statusCode = [int]$Matches[1]
$body = ($lines[0..($lines.Count - 2)] -join "`n")

if ($statusCode -ne 200) {
    Write-Error "OpenAPI fetch failed ($statusCode): $body"
    exit 1
}

$outFull = Join-Path $repoRoot $OutputPath
$body | Set-Content $outFull -Encoding utf8
Write-Host "[done] refresh-openapi: written to $outFull"
