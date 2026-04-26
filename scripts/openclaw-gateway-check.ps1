param(
    [string]$GatewayBaseUrl = "",
    [string]$AgentId = "default",
    [string]$BackendModel = "",
    [string]$AuthToken = "",
    [string]$Prompt = "Return a JSON object with fields: status, agent_id.",
    [string]$OutPath = "",
    [string]$EvidenceOutPath = "",
    [switch]$AppendStagingRecord,
    [string]$StagingRecordPath = "",
    [string]$VerifiedBy = "Codex unattended run",
    [int]$TimeoutSec = 0,
    [int]$ProbeTimeoutSec = 0,
    [string]$OpenClawConfigPath = "",
    [switch]$NoResponsesFallback
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$executionTimestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")

function Resolve-PositiveIntFromProcessEnv {
    param(
        [string]$Name,
        [int]$DefaultValue
    )
    $raw = [System.Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($raw)) {
        $parsed = 0
        if ([int]::TryParse($raw, [ref]$parsed) -and $parsed -gt 0) {
            return $parsed
        }
    }
    return $DefaultValue
}

function Get-OpenClawTokenFromConfigText {
    param(
        [Parameter(Mandatory = $true)][string]$ConfigText
    )
    if ([string]::IsNullOrWhiteSpace($ConfigText)) {
        return ""
    }

    try {
        $parsed = $ConfigText | ConvertFrom-Json
        $jsonToken = $parsed.gateway.auth.token
        if (-not [string]::IsNullOrWhiteSpace($jsonToken)) {
            return $jsonToken.Trim()
        }
    } catch {
        # Continue to lightweight JSON5-ish pattern extraction.
    }

    $regex = [regex]::new(
        '(?is)(?:"gateway"|gateway)\s*:\s*\{[\s\S]*?(?:"auth"|auth)\s*:\s*\{[\s\S]*?(?:"token"|token)\s*:\s*"([^"]+)"'
    )
    $match = $regex.Match($ConfigText)
    if ($match.Success -and $match.Groups.Count -gt 1) {
        $token = $match.Groups[1].Value
        if (-not [string]::IsNullOrWhiteSpace($token)) {
            return $token.Trim()
        }
    }

    return ""
}

function Resolve-OpenClawConfigPath {
    param([string]$ConfiguredPath)

    if (-not [string]::IsNullOrWhiteSpace($ConfiguredPath)) {
        return $ConfiguredPath
    }

    $fromEnv = [System.Environment]::GetEnvironmentVariable("OPENCLAW_CONFIG_PATH", "Process")
    if (-not [string]::IsNullOrWhiteSpace($fromEnv)) {
        return $fromEnv
    }

    return (Join-Path $HOME ".openclaw\openclaw.json")
}

function Save-JsonPayload {
    param(
        [object]$Payload,
        [string]$Path
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    $parent = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 30 | Set-Content -Path $Path -Encoding utf8
}

function ConvertFrom-JsonCompat {
    param(
        [Parameter(Mandatory = $true)][string]$Json,
        [int]$Depth = 100
    )

    $cmd = Get-Command ConvertFrom-Json -ErrorAction Stop
    if ($cmd.Parameters.ContainsKey("Depth")) {
        return ($Json | ConvertFrom-Json -Depth $Depth)
    }
    return ($Json | ConvertFrom-Json)
}

function Append-OpenClawStagingRecordEntry {
    param(
        [object]$Evidence,
        [string]$RecordPath
    )
    $targetPath = $RecordPath
    if ([string]::IsNullOrWhiteSpace($targetPath)) {
        $targetPath = Join-Path $repoRoot "docs\staging_execution_record.md"
    }
    $parent = Split-Path -Parent $targetPath
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    $details = [string]$Evidence.details
    if ([string]::IsNullOrWhiteSpace($details)) {
        $details = [string]$Evidence.response_excerpt
    }
    if ($details.Length -gt 1000) {
        $details = $details.Substring(0, 1000)
    }

    $successLabel = if ($Evidence.gateway_response_success) { "yes" } else { "no" }
    $fallbackLabel = if ($Evidence.fallback_used) { "yes" } else { "no" }
    $backend = if ([string]::IsNullOrWhiteSpace([string]$Evidence.backend_model)) {
        "none"
    } else {
        [string]$Evidence.backend_model
    }
    $semanticMode = [string]$Evidence.content_response_mode
    if ([string]::IsNullOrWhiteSpace($semanticMode)) {
        $semanticMode = "unknown"
    }
    $semanticKind = [string]$Evidence.content_kind
    if ([string]::IsNullOrWhiteSpace($semanticKind)) {
        $semanticKind = "unknown"
    }
    $hintLine = if (-not [string]::IsNullOrWhiteSpace([string]$Evidence.hint)) {
        "- Hint: $($Evidence.hint)"
    } else {
        "- Hint: none"
    }
    $modelsList = @($Evidence.models_probe_model_ids | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $modelsLine = if ($modelsList.Count -gt 0) {
        "- Models probe IDs: " + ($modelsList -join ", ")
    } else {
        "- Models probe IDs: (none)"
    }
    $upstreamLines = @()
    if ($Evidence.upstream_rejection_detected) {
        $upstreamLines += ("- Upstream rejection detected: yes")
        $upstreamLines += ("- Upstream provider: {0}" -f $Evidence.upstream_provider)
        $upstreamLines += ("- Upstream rejection reason: {0}" -f $Evidence.upstream_rejection_reason)
        if ($Evidence.backend_override_provider_mismatch) {
            $upstreamLines += ("- Backend override provider mismatch: yes")
        }
    }

    $entryLines = @(
        "",
        ("## OpenClaw Gateway evidence ({0})" -f $Evidence.execution_timestamp),
        "",
        ("- Execution timestamp: {0}" -f $Evidence.execution_timestamp),
        "- Command: Set-Location D:\\codex; .\\scripts\\openclaw-gateway-check.ps1",
        ("- Base URL: {0}" -f $Evidence.gateway_base_url),
        ("- Agent: openclaw/{0}" -f $Evidence.agent_id),
        ("- Backend override: {0}" -f $backend),
        ("- Gateway response success: {0}" -f $successLabel),
        ("- Endpoint used: {0}" -f $Evidence.used_endpoint),
        ("- HTTP status: {0}" -f $Evidence.status_code),
        ("- Fallback used: {0}" -f $fallbackLabel),
        ("- Semantic response mode: {0}" -f $semanticMode),
        ("- Semantic content kind: {0}" -f $semanticKind),
        ("- Auth source: {0}" -f $Evidence.auth_source),
        ("- Verified by: {0}" -f $Evidence.verified_by),
        ("- Models probe control HTML detected: {0}" -f $Evidence.models_probe_control_html),
        ("- Models probe status/content-type: {0} / {1}" -f $Evidence.models_probe_status_code, $Evidence.models_probe_content_type),
        ("- Agent model listed in /models: {0}" -f $Evidence.models_probe_agent_model_present),
        $modelsLine,
        $hintLine,
        "",
        "Observed response excerpt:",
        "",
        '```text',
        $details,
        '```',
        ""
    )
    if ($upstreamLines.Count -gt 0) {
        $entryLines = $entryLines[0..17] + $upstreamLines + $entryLines[18..($entryLines.Count - 1)]
    }
    $entry = $entryLines -join "`r`n"

    Add-Content -Path $targetPath -Value $entry -Encoding utf8
}

function New-OpenClawEvidence {
    param(
        [bool]$GatewayResponseSuccess,
        [int]$StatusCode,
        [string]$UsedEndpoint,
        [bool]$FallbackUsed,
        [string]$Details,
        [string]$Hint,
        [string]$ResponseBody,
        [string]$AuthSource,
        [bool]$ModelsProbeControlHtml,
        [string]$ModelsProbeMessage,
        [int]$ModelsProbeStatusCode,
        [string]$ModelsProbeContentType,
        [object[]]$ModelsProbeModelIds,
        [bool]$ModelsProbeAgentModelPresent,
        [string]$ContentResponseMode = "",
        [string]$ContentKind = "",
        [bool]$UpstreamRejectionDetected = $false,
        [string]$UpstreamProvider = "",
        [string]$UpstreamRejectionReason = "",
        [string]$BackendOverrideProvider = "",
        [bool]$BackendOverrideProviderMismatch = $false
    )
    $responseExcerpt = $ResponseBody
    if ([string]::IsNullOrWhiteSpace($responseExcerpt)) {
        $responseExcerpt = $Details
    }
    if ([string]::IsNullOrWhiteSpace($responseExcerpt)) {
        $responseExcerpt = "(empty)"
    }
    if ($responseExcerpt.Length -gt 1000) {
        $responseExcerpt = $responseExcerpt.Substring(0, 1000)
    }

    return [pscustomobject]@{
        execution_timestamp = $executionTimestamp
        gateway_base_url = $GatewayBaseUrl
        agent_id = $AgentId
        backend_model = $BackendModel
        gateway_response_success = $GatewayResponseSuccess
        used_endpoint = $UsedEndpoint
        fallback_used = $FallbackUsed
        status_code = $StatusCode
        details = $Details
        hint = $Hint
        response_excerpt = $responseExcerpt
        auth_source = $AuthSource
        verified_by = $VerifiedBy
        timeout_sec = $effectiveTimeoutSec
        probe_timeout_sec = $effectiveProbeTimeoutSec
        models_probe_control_html = $ModelsProbeControlHtml
        models_probe_message = $ModelsProbeMessage
        models_probe_status_code = $ModelsProbeStatusCode
        models_probe_content_type = $ModelsProbeContentType
        models_probe_model_ids = @($ModelsProbeModelIds)
        models_probe_agent_model_present = $ModelsProbeAgentModelPresent
        content_response_mode = $ContentResponseMode
        content_kind = $ContentKind
        upstream_rejection_detected = $UpstreamRejectionDetected
        upstream_provider = $UpstreamProvider
        upstream_rejection_reason = $UpstreamRejectionReason
        backend_override_provider = $BackendOverrideProvider
        backend_override_provider_mismatch = $BackendOverrideProviderMismatch
    }
}

function Get-OpenClawBackendProviderFamily {
    param([string]$BackendModel)

    $value = [string]$BackendModel
    $value = $value.Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($value)) {
        return ""
    }

    $providerToken = $value
    if ($providerToken.Contains("/")) {
        $providerToken = $providerToken.Split("/", 2)[0]
    }

    if ($providerToken.StartsWith("openai")) { return "openai" }
    if ($providerToken -eq "anthropic") { return "anthropic" }
    if ($providerToken -eq "gemini" -or $providerToken -eq "google") { return "gemini" }
    if ($providerToken -eq "grok" -or $providerToken -eq "xai" -or $providerToken -eq "x.ai") {
        return "grok"
    }
    return $providerToken
}

function Emit-OpenClawEvidence {
    param([object]$Evidence)
    if (-not [string]::IsNullOrWhiteSpace($EvidenceOutPath)) {
        Save-JsonPayload -Payload $Evidence -Path $EvidenceOutPath
        Write-Host ("[evidence] saved json: {0}" -f $EvidenceOutPath)
    }
    if ($AppendStagingRecord) {
        Append-OpenClawStagingRecordEntry -Evidence $Evidence -RecordPath $StagingRecordPath
        $targetPath = $StagingRecordPath
        if ([string]::IsNullOrWhiteSpace($targetPath)) {
            $targetPath = Join-Path $repoRoot "docs\staging_execution_record.md"
        }
        Write-Host ("[evidence] appended staging record: {0}" -f $targetPath)
    }
}

function Invoke-OpenClawCurl {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$JsonBody,
        [int]$RequestTimeoutSec = 30
    )
    $tempBodyPath = Join-Path ([System.IO.Path]::GetTempPath()) ("openclaw-gateway-body-" + [guid]::NewGuid().ToString("N") + ".json")
    $tempResponsePath = Join-Path ([System.IO.Path]::GetTempPath()) ("openclaw-gateway-response-" + [guid]::NewGuid().ToString("N") + ".txt")
    try {
        [System.IO.File]::WriteAllText($tempBodyPath, $JsonBody, [System.Text.Encoding]::UTF8)

        $curlArgs = @(
        "-sS",
        "-X", "POST",
        $Url,
        "-H", "Content-Type: application/json",
        "--max-time", "$RequestTimeoutSec",
        "--data-binary", ("@" + $tempBodyPath),
        "--output", $tempResponsePath,
        "--write-out", "__STATUS__:%{http_code}"
        )
        if (-not [string]::IsNullOrWhiteSpace($AuthToken)) {
            $curlArgs += @("-H", ("Authorization: Bearer " + $AuthToken))
        }
        if (-not [string]::IsNullOrWhiteSpace($BackendModel)) {
            $curlArgs += @("-H", ("x-openclaw-model: " + $BackendModel))
        }

        $output = & curl.exe @curlArgs
        if ($LASTEXITCODE -ne 0) {
            throw ("curl failed while calling OpenClaw gateway: exit={0}" -f $LASTEXITCODE)
        }
        $statusLine = [string]$output
        if ($statusLine -notmatch "^__STATUS__:(\d+)$") {
            throw ("Could not parse status line: {0}" -f $statusLine)
        }
        $statusCode = [int]$Matches[1]
        $body = ""
        if (Test-Path $tempResponsePath) {
            $body = [System.IO.File]::ReadAllText($tempResponsePath, [System.Text.Encoding]::UTF8)
        }
        return @{
            status = $statusCode
            body   = [string]$body
        }
    } finally {
        if (Test-Path $tempBodyPath) {
            Remove-Item -Path $tempBodyPath -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path $tempResponsePath) {
            Remove-Item -Path $tempResponsePath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Normalize-GatewayJsonBody {
    param([string]$Body)

    $normalized = ([string]$Body).Replace([string][char]0, "").Trim()
    $normalized = $normalized.TrimStart([char]0xFEFF)
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return ""
    }

    $firstBrace = $normalized.IndexOf("{")
    $lastBrace = $normalized.LastIndexOf("}")
    if ($firstBrace -ge 0 -and $lastBrace -gt $firstBrace) {
        $normalized = $normalized.Substring($firstBrace, $lastBrace - $firstBrace + 1)
    }
    return $normalized.Trim()
}

function Test-OpenClawResponsePayload {
    param(
        [Parameter(Mandatory = $true)][string]$EndpointName,
        [Parameter(Mandatory = $true)][string]$Body
    )

    $normalizedBody = Normalize-GatewayJsonBody -Body $Body

    if ([string]::IsNullOrWhiteSpace($normalizedBody)) {
        return [pscustomobject]@{
            valid = $false
            reason = "empty response body"
        }
    }

    $parsed = $null
    try {
        $parsed = ConvertFrom-JsonCompat -Json $normalizedBody -Depth 100
    } catch {
        return [pscustomobject]@{
            valid = $false
            reason = "non-JSON response body"
        }
    }

    if ($EndpointName -eq "chat/completions") {
        $choices = @($parsed.choices)
        if ($choices.Count -lt 1) {
            return [pscustomobject]@{
                valid = $false
                reason = "missing choices[0]"
            }
        }
        $content = [string]$choices[0].message.content
        if ([string]::IsNullOrWhiteSpace($content)) {
            return [pscustomobject]@{
                valid = $false
                reason = "missing choices[0].message.content"
            }
        }
        return [pscustomobject]@{
            valid = $true
            reason = ""
        }
    }

    if ($EndpointName -eq "responses") {
        $outputText = [string]$parsed.output_text
        if (-not [string]::IsNullOrWhiteSpace($outputText)) {
            return [pscustomobject]@{
                valid = $true
                reason = ""
            }
        }
        $output = @($parsed.output)
        foreach ($item in $output) {
            foreach ($block in @($item.content)) {
                $textValue = [string]($block.text)
                if (-not [string]::IsNullOrWhiteSpace($textValue)) {
                    return [pscustomobject]@{
                        valid = $true
                        reason = ""
                    }
                }
                $outputTextValue = [string]($block.output_text)
                if (-not [string]::IsNullOrWhiteSpace($outputTextValue)) {
                    return [pscustomobject]@{
                        valid = $true
                        reason = ""
                    }
                }
            }
        }
        return [pscustomobject]@{
            valid = $false
            reason = "missing output_text/output[].content[].text"
        }
    }

    return [pscustomobject]@{
        valid = $true
        reason = ""
    }
}

function Get-OpenClawContentDiagnostics {
    param(
        [Parameter(Mandatory = $true)][string]$EndpointName,
        [Parameter(Mandatory = $true)][string]$Body
    )

    $result = [ordered]@{
        response_mode = ""
        content_kind = ""
        upstream_rejection_detected = $false
        upstream_provider = ""
        upstream_rejection_reason = ""
    }

    $normalizedBody = Normalize-GatewayJsonBody -Body $Body

    if ([string]::IsNullOrWhiteSpace($normalizedBody)) {
        $result.response_mode = "empty_body"
        $result.content_kind = "empty_body"
        return [pscustomobject]$result
    }

    try {
        $parsed = ConvertFrom-JsonCompat -Json $normalizedBody -Depth 100
    } catch {
        $result.response_mode = "non_json_body"
        $result.content_kind = "non_json_body"
        return [pscustomobject]$result
    }

    $contentText = ""
    if ($EndpointName -eq "chat/completions") {
        $choices = @($parsed.choices)
        if ($choices.Count -gt 0) {
            $contentText = [string]$choices[0].message.content
        }
    } elseif ($EndpointName -eq "responses") {
        $outputText = [string]$parsed.output_text
        if (-not [string]::IsNullOrWhiteSpace($outputText)) {
            $contentText = $outputText
        } else {
            foreach ($item in @($parsed.output)) {
                foreach ($block in @($item.content)) {
                    $textValue = [string]($block.text)
                    if (-not [string]::IsNullOrWhiteSpace($textValue)) {
                        $contentText = $textValue
                        break
                    }
                    $outputTextValue = [string]($block.output_text)
                    if (-not [string]::IsNullOrWhiteSpace($outputTextValue)) {
                        $contentText = $outputTextValue
                        break
                    }
                }
                if (-not [string]::IsNullOrWhiteSpace($contentText)) {
                    break
                }
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($contentText)) {
        $result.response_mode = "empty_text"
        $result.content_kind = "empty_text"
        return [pscustomobject]$result
    }

    $contentText = $contentText.Trim()
    try {
        $parsedContent = ConvertFrom-JsonCompat -Json $contentText -Depth 20
        if ($null -ne $parsedContent -and -not ($parsedContent -is [string])) {
            $result.response_mode = "json_text"
            $result.content_kind = "json_text"
            return [pscustomobject]$result
        }
    } catch {
        # treat as plain text
    }

    $result.response_mode = "plain_text"
    $result.content_kind = "plain_text"

    if ($contentText -match '(?i)(?:llm\s+)?request rejected|credit balance is too low|plans?\s*&\s*billing|purchase credits?|quota exceeded|rate limit(?:ed)?|access denied|forbidden') {
        $result.response_mode = "plain_text_upstream_rejection"
        $result.content_kind = "upstream_rejection"
        $result.upstream_rejection_detected = $true

        if ($contentText -match '(?i)\banthropic\b') {
            $result.upstream_provider = "anthropic"
        } elseif ($contentText -match '(?i)\bopenai\b') {
            $result.upstream_provider = "openai"
        } elseif ($contentText -match '(?i)\b(?:gemini|google ai|google api)\b') {
            $result.upstream_provider = "gemini"
        } elseif ($contentText -match '(?i)\b(?:grok|xai|x\.ai)\b') {
            $result.upstream_provider = "grok"
        } else {
            $result.upstream_provider = "unknown_provider"
        }

        if ($contentText -match '(?i)credit balance is too low|plans?\s*&\s*billing|purchase credits?') {
            $result.upstream_rejection_reason = "credit_balance_too_low"
        } elseif ($contentText -match '(?i)rate limit(?:ed)?|too many requests|quota exceeded') {
            $result.upstream_rejection_reason = "rate_limited"
        } elseif ($contentText -match '(?i)invalid api key|authentication failed|unauthorized') {
            $result.upstream_rejection_reason = "authentication_failed"
        } elseif ($contentText -match '(?i)access denied|forbidden|permission denied') {
            $result.upstream_rejection_reason = "access_denied"
        } elseif ($contentText -match '(?i)service unavailable|overloaded|temporarily unavailable') {
            $result.upstream_rejection_reason = "provider_unavailable"
        } else {
            $result.upstream_rejection_reason = "unknown_reason"
        }
    }

    return [pscustomobject]$result
}

function Test-OpenClawModelsProbe {
    param(
        [Parameter(Mandatory = $true)][string]$ModelsUrl,
        [int]$ProbeTimeoutSec = 10
    )
    try {
        $headers = @{}
        if (-not [string]::IsNullOrWhiteSpace($AuthToken)) {
            $headers["Authorization"] = ("Bearer " + $AuthToken)
        }
        $modelsProbe = Invoke-WebRequest -Uri $ModelsUrl -Method GET -Headers $headers -UseBasicParsing -TimeoutSec $ProbeTimeoutSec
        $statusCode = [int]$modelsProbe.StatusCode
        $contentType = [string]$modelsProbe.Headers["Content-Type"]
        $modelIds = @()
        $agentModelPresent = $false
        if ($modelsProbe.Content) {
            try {
                $parsed = ConvertFrom-JsonCompat -Json ([string]$modelsProbe.Content) -Depth 100
                $rawData = @($parsed.data)
                $modelIds = @(
                    $rawData |
                    ForEach-Object { [string]$_.id } |
                    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                    Select-Object -Unique
                )
                $agentModelPresent = ($modelIds -contains ("openclaw/" + $AgentId))
            } catch {
                # Keep non-fatal; this probe is diagnostic.
            }
        }
        if ($modelsProbe.StatusCode -eq 200 -and $modelsProbe.Content -match "<openclaw-app>") {
            $msg = ("{0} returned OpenClaw Control HTML, not API JSON. HTTP API endpoints may be disabled." -f $ModelsUrl)
            Write-Warning $msg
            return [pscustomobject]@{
                control_html_detected = $true
                message = $msg
                status_code = $statusCode
                content_type = $contentType
                model_ids = @($modelIds)
                agent_model_present = $agentModelPresent
            }
        }
        return [pscustomobject]@{
            control_html_detected = $false
            message = ""
            status_code = $statusCode
            content_type = $contentType
            model_ids = @($modelIds)
            agent_model_present = $agentModelPresent
        }
    } catch {
        $msg = ("[probe] models endpoint check skipped: {0}" -f $_.Exception.Message)
        Write-Host $msg
        return [pscustomobject]@{
            control_html_detected = $false
            message = $msg
            status_code = 0
            content_type = ""
            model_ids = @()
            agent_model_present = $false
        }
    }
}

$effectiveTimeoutSec = if ($TimeoutSec -gt 0) {
    $TimeoutSec
} else {
    Resolve-PositiveIntFromProcessEnv -Name "OPENCLAW_TIMEOUT_SECONDS" -DefaultValue 30
}
$effectiveProbeTimeoutSec = if ($ProbeTimeoutSec -gt 0) {
    $ProbeTimeoutSec
} else {
    Resolve-PositiveIntFromProcessEnv -Name "OPENCLAW_GATEWAY_PROBE_TIMEOUT_SECONDS" -DefaultValue 10
}

if ([string]::IsNullOrWhiteSpace($GatewayBaseUrl)) {
    $GatewayBaseUrl = [System.Environment]::GetEnvironmentVariable("OPENCLAW_BASE_URL", "Process")
}
if ([string]::IsNullOrWhiteSpace($GatewayBaseUrl)) {
    $GatewayBaseUrl = "http://127.0.0.1:18789/v1"
}

$authSource = "none"
if (-not [string]::IsNullOrWhiteSpace($AuthToken)) {
    $authSource = "parameter"
} else {
    $envToken = [System.Environment]::GetEnvironmentVariable("OPENCLAW_GATEWAY_TOKEN", "Process")
    if (-not [string]::IsNullOrWhiteSpace($envToken)) {
        $AuthToken = $envToken
        $authSource = "env:OPENCLAW_GATEWAY_TOKEN"
    } else {
        $resolvedConfigPath = Resolve-OpenClawConfigPath -ConfiguredPath $OpenClawConfigPath
        if (Test-Path $resolvedConfigPath) {
            try {
                $configText = Get-Content -Path $resolvedConfigPath -Raw
                $configToken = Get-OpenClawTokenFromConfigText -ConfigText $configText
                if (-not [string]::IsNullOrWhiteSpace($configToken)) {
                    $AuthToken = $configToken
                    $authSource = ("config:{0}" -f $resolvedConfigPath)
                }
            } catch {
                Write-Host ("[config] OpenClaw token auto-load skipped: {0}" -f $_.Exception.Message)
            }
        }
    }
}

$chatPayloadObj = @{
    model = ("openclaw/" + $AgentId)
    messages = @(
        @{ role = "system"; content = "You are a strict JSON assistant. Reply with a valid JSON object only." },
        @{ role = "user"; content = $Prompt }
    )
    response_format = @{ type = "json_object" }
}
$chatPayload = $chatPayloadObj | ConvertTo-Json -Compress -Depth 20

$chatUrl = $GatewayBaseUrl.TrimEnd("/") + "/chat/completions"
Write-Host "[openclaw-gateway-check] POST $chatUrl"
Write-Host ("  model         : openclaw/{0}" -f $AgentId)
Write-Host ("  timeout sec   : {0}" -f $effectiveTimeoutSec)
Write-Host ("  probe sec     : {0}" -f $effectiveProbeTimeoutSec)
if (-not [string]::IsNullOrWhiteSpace($BackendModel)) {
    Write-Host ("  backend model : {0}" -f $BackendModel)
}
Write-Host ("  auth source   : {0}" -f $authSource)
if (-not [string]::IsNullOrWhiteSpace($AuthToken)) {
    Write-Host "  auth          : bearer token provided"
} else {
    Write-Host "  auth          : none"
}

$statusCode = 0
$body = ""
$usedEndpoint = "chat/completions"
$chatError = ""
$fallbackUsed = $false
$payloadValidationError = ""
$modelsUrl = $GatewayBaseUrl.TrimEnd("/") + "/models"
$modelsProbeResult = Test-OpenClawModelsProbe -ModelsUrl $modelsUrl -ProbeTimeoutSec $effectiveProbeTimeoutSec

try {
    $chatResult = Invoke-OpenClawCurl -Url $chatUrl -JsonBody $chatPayload -RequestTimeoutSec $effectiveTimeoutSec
    $statusCode = $chatResult.status
    $body = $chatResult.body
} catch {
    $chatError = $_.Exception.Message
    if ($NoResponsesFallback) {
        $evidence = New-OpenClawEvidence `
            -GatewayResponseSuccess $false `
            -StatusCode 0 `
            -UsedEndpoint "chat/completions" `
            -FallbackUsed $false `
            -Details ("chat/completions call failed: " + $chatError) `
            -Hint "" `
            -ResponseBody "" `
            -AuthSource $authSource `
            -ModelsProbeControlHtml $modelsProbeResult.control_html_detected `
            -ModelsProbeMessage $modelsProbeResult.message `
            -ModelsProbeStatusCode $modelsProbeResult.status_code `
            -ModelsProbeContentType $modelsProbeResult.content_type `
            -ModelsProbeModelIds @($modelsProbeResult.model_ids) `
            -ModelsProbeAgentModelPresent $modelsProbeResult.agent_model_present
        Emit-OpenClawEvidence -Evidence $evidence
        Write-Error ("Gateway check failed via chat/completions: {0}" -f $chatError)
        exit 1
    }
    $fallbackUsed = $true
    Write-Warning ("chat/completions call failed, trying /v1/responses fallback: {0}" -f $chatError)
}

if (($statusCode -eq 404 -or -not [string]::IsNullOrWhiteSpace($chatError)) -and -not $NoResponsesFallback) {
    if ($statusCode -eq 404) {
        $fallbackUsed = $true
        Write-Host "  [fallback] chat/completions returned 404; trying /v1/responses"
    }
    $responsesPayloadObj = @{
        model = ("openclaw/" + $AgentId)
        instructions = "You are a strict JSON assistant. Reply with a valid JSON object only."
        input = $Prompt
    }
    $responsesPayload = $responsesPayloadObj | ConvertTo-Json -Compress -Depth 20
    $responsesUrl = $GatewayBaseUrl.TrimEnd("/") + "/responses"
    try {
        $responsesResult = Invoke-OpenClawCurl -Url $responsesUrl -JsonBody $responsesPayload -RequestTimeoutSec $effectiveTimeoutSec
        $statusCode = $responsesResult.status
        $body = $responsesResult.body
        $usedEndpoint = "responses"
    } catch {
        $statusCode = 0
        $body = ""
        $usedEndpoint = "responses"
        $chatError = ($chatError + " | responses fallback failed: " + $_.Exception.Message).Trim(" ", "|")
    }
}

$contentDiagnostics = [pscustomobject]@{
    response_mode = ""
    content_kind = ""
    upstream_rejection_detected = $false
    upstream_provider = ""
    upstream_rejection_reason = ""
}
$backendOverrideProvider = Get-OpenClawBackendProviderFamily -BackendModel $BackendModel
$backendOverrideProviderMismatch = $false

if ($statusCode -eq 200) {
    $validation = Test-OpenClawResponsePayload -EndpointName $usedEndpoint -Body $body
    if (-not $validation.valid) {
        $bodyExcerpt = [string]$body
        if ($bodyExcerpt.Length -gt 300) {
            $bodyExcerpt = $bodyExcerpt.Substring(0, 300)
        }
        if ($usedEndpoint -eq "chat/completions" -and -not $NoResponsesFallback) {
            $fallbackUsed = $true
            Write-Warning (
                "chat/completions returned invalid payload, trying /v1/responses fallback: {0}" -f
                $validation.reason
            )
            $responsesPayloadObj = @{
                model = ("openclaw/" + $AgentId)
                instructions = "You are a strict JSON assistant. Reply with a valid JSON object only."
                input = $Prompt
            }
            $responsesPayload = $responsesPayloadObj | ConvertTo-Json -Compress -Depth 20
            $responsesUrl = $GatewayBaseUrl.TrimEnd("/") + "/responses"
            try {
                $responsesResult = Invoke-OpenClawCurl -Url $responsesUrl -JsonBody $responsesPayload -RequestTimeoutSec $effectiveTimeoutSec
                $statusCode = $responsesResult.status
                $body = $responsesResult.body
                $usedEndpoint = "responses"
                if ($statusCode -eq 200) {
                    $responsesValidation = Test-OpenClawResponsePayload -EndpointName "responses" -Body $body
                    if (-not $responsesValidation.valid) {
                        $responsesExcerpt = [string]$body
                        if ($responsesExcerpt.Length -gt 300) {
                            $responsesExcerpt = $responsesExcerpt.Substring(0, 300)
                        }
                        $payloadValidationError = (
                            "responses payload invalid: {0}; body_excerpt={1}" -f
                            $responsesValidation.reason,
                            $responsesExcerpt
                        )
                    }
                }
            } catch {
                $statusCode = 0
                $body = ""
                $usedEndpoint = "responses"
                $payloadValidationError = ("responses fallback failed after invalid chat payload: {0}" -f $_.Exception.Message)
            }
        } else {
            $payloadValidationError = (
                "{0} payload invalid: {1}; body_excerpt={2}" -f
                $usedEndpoint,
                $validation.reason,
                $bodyExcerpt
            )
        }
    } else {
        $contentDiagnostics = Get-OpenClawContentDiagnostics -EndpointName $usedEndpoint -Body $body
        if ($contentDiagnostics.upstream_rejection_detected) {
            $backendOverrideProviderMismatch = (
                -not [string]::IsNullOrWhiteSpace($backendOverrideProvider) -and
                -not [string]::IsNullOrWhiteSpace([string]$contentDiagnostics.upstream_provider) -and
                $backendOverrideProvider -ne [string]$contentDiagnostics.upstream_provider
            )
            Write-Warning (
                "Gateway transport is live, but upstream rejection was detected: provider={0} reason={1}" -f
                [string]$contentDiagnostics.upstream_provider,
                [string]$contentDiagnostics.upstream_rejection_reason
            )
            if ($backendOverrideProviderMismatch) {
                Write-Warning (
                    "Configured backend override provider does not match rejecting upstream provider: expected={0} actual={1}" -f
                    $backendOverrideProvider,
                    [string]$contentDiagnostics.upstream_provider
                )
            }
        }
    }
}

if ($statusCode -ne 200 -or -not [string]::IsNullOrWhiteSpace($payloadValidationError)) {
    $hint = ""
    if ($statusCode -eq 404) {
        $hint = "enable OpenClaw HTTP endpoint: gateway.http.endpoints.chatCompletions.enabled=true or gateway.http.endpoints.responses.enabled=true"
    }
    if (-not [string]::IsNullOrWhiteSpace($payloadValidationError)) {
        $hint = "gateway returned 200 with unexpected payload shape; verify endpoint exposes OpenAI-compatible JSON"
    }
    $details = if (-not [string]::IsNullOrWhiteSpace($payloadValidationError)) { $payloadValidationError } else { $body }
    if ([string]::IsNullOrWhiteSpace($details)) {
        $details = $chatError
    }

    $evidence = New-OpenClawEvidence `
        -GatewayResponseSuccess $false `
        -StatusCode $statusCode `
        -UsedEndpoint $usedEndpoint `
        -FallbackUsed $fallbackUsed `
        -Details $details `
        -Hint $hint `
        -ResponseBody $body `
        -AuthSource $authSource `
        -ModelsProbeControlHtml $modelsProbeResult.control_html_detected `
        -ModelsProbeMessage $modelsProbeResult.message `
        -ModelsProbeStatusCode $modelsProbeResult.status_code `
        -ModelsProbeContentType $modelsProbeResult.content_type `
        -ModelsProbeModelIds @($modelsProbeResult.model_ids) `
        -ModelsProbeAgentModelPresent $modelsProbeResult.agent_model_present `
        -ContentResponseMode ([string]$contentDiagnostics.response_mode) `
        -ContentKind ([string]$contentDiagnostics.content_kind) `
        -UpstreamRejectionDetected ([bool]$contentDiagnostics.upstream_rejection_detected) `
        -UpstreamProvider ([string]$contentDiagnostics.upstream_provider) `
        -UpstreamRejectionReason ([string]$contentDiagnostics.upstream_rejection_reason) `
        -BackendOverrideProvider $backendOverrideProvider `
        -BackendOverrideProviderMismatch $backendOverrideProviderMismatch
    Emit-OpenClawEvidence -Evidence $evidence

    $hintSuffix = ""
    if (-not [string]::IsNullOrWhiteSpace($hint)) {
        $hintSuffix = " (hint: " + $hint + ")"
    }
    Write-Error ("Gateway check failed ({0}) via {1}: {2}{3}" -f $statusCode, $usedEndpoint, $details, $hintSuffix)
    exit 1
}

Write-Host ""
Write-Host ("[endpoint] {0}" -f $usedEndpoint)
Write-Host "[response]"
Write-Host $body

if (-not [string]::IsNullOrWhiteSpace($OutPath)) {
    $parent = Split-Path -Parent $OutPath
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $body | Set-Content -Path $OutPath -Encoding utf8
    Write-Host ("[saved] {0}" -f $OutPath)
}

$successDetails = if ($contentDiagnostics.upstream_rejection_detected) {
    "gateway check passed; upstream rejection detected"
} else {
    "gateway check passed"
}
$successHint = if ($contentDiagnostics.upstream_rejection_detected) {
    if ($backendOverrideProviderMismatch) {
        "gateway transport is live but the configured backend override provider was not honored by the rejecting upstream provider"
    } else {
        "gateway transport is live but upstream provider rejected the semantic request"
    }
} else {
    ""
}

$successEvidence = New-OpenClawEvidence `
    -GatewayResponseSuccess $true `
    -StatusCode 200 `
    -UsedEndpoint $usedEndpoint `
    -FallbackUsed $fallbackUsed `
    -Details $successDetails `
    -Hint $successHint `
    -ResponseBody $body `
    -AuthSource $authSource `
    -ModelsProbeControlHtml $modelsProbeResult.control_html_detected `
    -ModelsProbeMessage $modelsProbeResult.message `
    -ModelsProbeStatusCode $modelsProbeResult.status_code `
    -ModelsProbeContentType $modelsProbeResult.content_type `
    -ModelsProbeModelIds @($modelsProbeResult.model_ids) `
    -ModelsProbeAgentModelPresent $modelsProbeResult.agent_model_present `
    -ContentResponseMode ([string]$contentDiagnostics.response_mode) `
    -ContentKind ([string]$contentDiagnostics.content_kind) `
    -UpstreamRejectionDetected ([bool]$contentDiagnostics.upstream_rejection_detected) `
    -UpstreamProvider ([string]$contentDiagnostics.upstream_provider) `
    -UpstreamRejectionReason ([string]$contentDiagnostics.upstream_rejection_reason) `
    -BackendOverrideProvider $backendOverrideProvider `
    -BackendOverrideProviderMismatch $backendOverrideProviderMismatch
Emit-OpenClawEvidence -Evidence $successEvidence

Write-Host ""
Write-Host "[done] openclaw gateway check passed"
