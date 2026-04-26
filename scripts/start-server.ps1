param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$Reload,
    [switch]$UseOpenClawDefaultProfile,
    [string]$DepartmentModel = "",
    [string]$ResearchModel = "",
    [string]$DesignModel = "",
    [string]$BuildModel = "",
    [string]$ReviewModel = "",
    [string]$OpenClawBaseUrl = "",
    [string]$OpenClawBackendModel = "",
    [switch]$PrintEffectiveConfigOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }

function Set-ProcessEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Key,
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return
    }

    [System.Environment]::SetEnvironmentVariable($Key, $Value.Trim(), "Process")
}

# Load .env if present, setting only variables not already in the environment.
$envFile = Join-Path $repoRoot ".env"
if (Test-Path $envFile) {
    if (-not $PrintEffectiveConfigOnly) {
        Write-Host "[start-server] Loading .env"
    }
    foreach ($line in (Get-Content $envFile -Encoding utf8)) {
        if ($line -match '^\s*#' -or [string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $key = $Matches[1]
            $val = $Matches[2].Trim()
            $existing = [System.Environment]::GetEnvironmentVariable($key, "Process")
            if ($null -eq $existing -or $existing -eq "") {
                [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
            }
        }
    }
} else {
    if (-not $PrintEffectiveConfigOnly) {
        Write-Host "[start-server] No .env found."
        Write-Host "  For persistent state, copy .env.example to .env first:"
        Write-Host "    Copy-Item .env.example .env"
        Write-Host ""
    }
}

if ($UseOpenClawDefaultProfile -and [string]::IsNullOrWhiteSpace($DepartmentModel)) {
    $DepartmentModel = "openclaw/codex-orchestrator"
}

if (-not [string]::IsNullOrWhiteSpace($DepartmentModel)) {
    foreach ($key in @("RESEARCH_MODEL", "DESIGN_MODEL", "BUILD_MODEL", "REVIEW_MODEL")) {
        Set-ProcessEnvValue -Key $key -Value $DepartmentModel
    }
}

Set-ProcessEnvValue -Key "RESEARCH_MODEL" -Value $ResearchModel
Set-ProcessEnvValue -Key "DESIGN_MODEL" -Value $DesignModel
Set-ProcessEnvValue -Key "BUILD_MODEL" -Value $BuildModel
Set-ProcessEnvValue -Key "REVIEW_MODEL" -Value $ReviewModel
Set-ProcessEnvValue -Key "OPENCLAW_BASE_URL" -Value $OpenClawBaseUrl
Set-ProcessEnvValue -Key "OPENCLAW_BACKEND_MODEL" -Value $OpenClawBackendModel

$stateBackend = [System.Environment]::GetEnvironmentVariable("STATE_BACKEND", "Process")
if ([string]::IsNullOrWhiteSpace($stateBackend)) { $stateBackend = "memory" }

if (-not $PrintEffectiveConfigOnly) {
    Write-Host ("[start-server] STATE_BACKEND={0}" -f $stateBackend)
}

if ($stateBackend -in @("sqlite", "sqlite3")) {
    $dbPath = [System.Environment]::GetEnvironmentVariable("SQLITE_DB_PATH", "Process")
    if ([string]::IsNullOrWhiteSpace($dbPath)) { $dbPath = "data/codex.db" }
    if (-not $PrintEffectiveConfigOnly) {
        Write-Host ("[start-server] SQLITE_DB_PATH={0}" -f $dbPath)
    }
    $dbDir = Split-Path -Parent $dbPath
    if (-not [string]::IsNullOrWhiteSpace($dbDir) -and -not (Test-Path $dbDir)) {
        New-Item -ItemType Directory -Force -Path $dbDir | Out-Null
        if (-not $PrintEffectiveConfigOnly) {
            Write-Host ("[start-server] Created directory: {0}" -f $dbDir)
        }
    }
}

$effectiveConfig = [ordered]@{
    bind_host = $BindHost
    port = $Port
    reload = [bool]$Reload
    state_backend = $stateBackend
    sqlite_db_path = [System.Environment]::GetEnvironmentVariable("SQLITE_DB_PATH", "Process")
    use_openclaw_default_profile = [bool]$UseOpenClawDefaultProfile
    department_models = [ordered]@{
        research = [System.Environment]::GetEnvironmentVariable("RESEARCH_MODEL", "Process")
        design   = [System.Environment]::GetEnvironmentVariable("DESIGN_MODEL", "Process")
        build    = [System.Environment]::GetEnvironmentVariable("BUILD_MODEL", "Process")
        review   = [System.Environment]::GetEnvironmentVariable("REVIEW_MODEL", "Process")
    }
    openclaw = [ordered]@{
        base_url = [System.Environment]::GetEnvironmentVariable("OPENCLAW_BASE_URL", "Process")
        backend_model = [System.Environment]::GetEnvironmentVariable("OPENCLAW_BACKEND_MODEL", "Process")
    }
}

if (-not $PrintEffectiveConfigOnly) {
    Write-Host (
        "[start-server] Department models: research={0} design={1} build={2} review={3}" -f
        $effectiveConfig.department_models.research,
        $effectiveConfig.department_models.design,
        $effectiveConfig.department_models.build,
        $effectiveConfig.department_models.review
    )
    if (-not [string]::IsNullOrWhiteSpace($effectiveConfig.openclaw.base_url)) {
        Write-Host ("[start-server] OPENCLAW_BASE_URL={0}" -f $effectiveConfig.openclaw.base_url)
    }
    if (-not [string]::IsNullOrWhiteSpace($effectiveConfig.openclaw.backend_model)) {
        Write-Host (
            "[start-server] OPENCLAW_BACKEND_MODEL={0}" -f
            $effectiveConfig.openclaw.backend_model
        )
    }
}

if ($PrintEffectiveConfigOnly) {
    $effectiveConfig | ConvertTo-Json -Depth 5 | Write-Output
    exit 0
}

$uvicornArgs = @(
    "-m", "uvicorn",
    "app.api.main:app",
    "--host", $BindHost,
    "--port", [string]$Port
)
if ($Reload) {
    $uvicornArgs += "--reload"
}

Write-Host ("[start-server] Starting on http://{0}:{1}" -f $BindHost, $Port)
Write-Host "  Press Ctrl+C to stop."
Write-Host ""

& $pythonExe @uvicornArgs
