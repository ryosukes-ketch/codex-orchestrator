function Get-OperatorRepoRoot {
    param([string]$ScriptRoot)
    return (Split-Path -Parent $ScriptRoot)
}

function Read-OperatorJsonFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw ("JSON file not found: {0}" -f $Path)
    }

    $raw = Get-Content -Raw -Path $Path
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw ("JSON file is empty: {0}" -f $Path)
    }

    try {
        return ($raw | ConvertFrom-Json)
    } catch {
        throw ("JSON parse failed for {0}: {1}" -f $Path, $_.Exception.Message)
    }
}

function Convert-OperatorBodyToJsonOrNull {
    param([string]$BodyText)

    if ([string]::IsNullOrWhiteSpace($BodyText)) {
        return $null
    }

    try {
        return ($BodyText | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Resolve-OperatorTimeoutSec {
    param(
        [int]$TimeoutSec = 0,
        [int]$DefaultTimeoutSec = 30
    )

    if ($TimeoutSec -gt 0) {
        return $TimeoutSec
    }

    $raw = [System.Environment]::GetEnvironmentVariable("OPERATOR_API_TIMEOUT_SECONDS", "Process")
    if (-not [string]::IsNullOrWhiteSpace($raw)) {
        $parsed = 0
        if ([int]::TryParse($raw, [ref]$parsed) -and $parsed -gt 0) {
            return $parsed
        }
    }

    return $DefaultTimeoutSec
}

function New-OperatorEmptyAuthRoleEvidence {
    param([string]$Role)

    return [ordered]@{
        role = $Role
        identities = @()
        actor_types = @()
        auth_sources = @()
        auth_modes = @()
        has_authentication_event = $false
        has_actor_resolved_event = $false
        has_authorization_granted_event = $false
        authentication_event_count = 0
        actor_resolved_event_count = 0
        authorization_granted_event_count = 0
        evidence_present = $false
    }
}

function Get-OperatorAuthEvidence {
    param([Parameter(Mandatory = $true)]$Audit)

    $trackedRoles = @("operator", "approver")
    $roleEntries = [ordered]@{}
    $identitySets = @{}
    $actorTypeSets = @{}
    $sourceSets = @{}
    $modeSets = @{}
    foreach ($role in $trackedRoles) {
        $roleEntries[$role] = New-OperatorEmptyAuthRoleEvidence -Role $role
        $identitySets[$role] = New-Object System.Collections.Generic.HashSet[string]
        $actorTypeSets[$role] = New-Object System.Collections.Generic.HashSet[string]
        $sourceSets[$role] = New-Object System.Collections.Generic.HashSet[string]
        $modeSets[$role] = New-Object System.Collections.Generic.HashSet[string]
    }

    foreach ($event in @($Audit.events)) {
        if ($null -eq $event) {
            continue
        }
        $role = ([string]$event.actor_role).Trim().ToLowerInvariant()
        if (-not $roleEntries.Contains($role)) {
            continue
        }
        $entry = $roleEntries[$role]

        $identity = ([string]$event.actor).Trim()
        if (-not [string]::IsNullOrWhiteSpace($identity)) {
            $identitySets[$role].Add($identity) | Out-Null
        }
        $actorType = ([string]$event.actor_type).Trim().ToLowerInvariant()
        if (-not [string]::IsNullOrWhiteSpace($actorType)) {
            $actorTypeSets[$role].Add($actorType) | Out-Null
        }

        $eventType = ([string]$event.event_type).Trim().ToLowerInvariant()
        $metadata = $event.metadata
        if ($null -eq $metadata) {
            $metadata = @{}
        }

        $authSource = ([string]$metadata.auth_source).Trim().ToLowerInvariant()
        $authMode = ([string]$metadata.auth_mode).Trim().ToLowerInvariant()

        switch ($eventType) {
            "authentication_succeeded" {
                $entry.has_authentication_event = $true
                $entry.authentication_event_count = [int]$entry.authentication_event_count + 1
                if ([string]::IsNullOrWhiteSpace($authSource)) { $authSource = "audit_event" }
                if ([string]::IsNullOrWhiteSpace($authMode)) { $authMode = "event_inferred" }
            }
            "actor_resolved" {
                $entry.has_actor_resolved_event = $true
                $entry.actor_resolved_event_count = [int]$entry.actor_resolved_event_count + 1
                if ([string]::IsNullOrWhiteSpace($authSource)) { $authSource = "audit_event" }
                if ([string]::IsNullOrWhiteSpace($authMode)) { $authMode = "event_inferred" }
            }
            "authorization_granted" {
                $entry.has_authorization_granted_event = $true
                $entry.authorization_granted_event_count = [int]$entry.authorization_granted_event_count + 1
                if ([string]::IsNullOrWhiteSpace($authSource)) { $authSource = "audit_event" }
                if ([string]::IsNullOrWhiteSpace($authMode)) { $authMode = "event_inferred" }
            }
        }

        if (-not [string]::IsNullOrWhiteSpace($authSource)) {
            $sourceSets[$role].Add($authSource) | Out-Null
        }
        if (-not [string]::IsNullOrWhiteSpace($authMode)) {
            $modeSets[$role].Add($authMode) | Out-Null
        }
    }

    $presentRoles = New-Object System.Collections.Generic.List[string]
    foreach ($role in $trackedRoles) {
        $entry = $roleEntries[$role]
        $entry.identities = @(Convert-OperatorSetToArray -Set $identitySets[$role] | Sort-Object)
        $entry.actor_types = @(Convert-OperatorSetToArray -Set $actorTypeSets[$role] | Sort-Object)
        $entry.auth_sources = @(Convert-OperatorSetToArray -Set $sourceSets[$role] | Sort-Object)
        $entry.auth_modes = @(Convert-OperatorSetToArray -Set $modeSets[$role] | Sort-Object)
        $requiresAuthorizationGranted = ($role -eq "approver")
        $entry.evidence_present = (
            $entry.has_authentication_event `
                -and $entry.has_actor_resolved_event `
                -and ($entry.identities.Count -gt 0) `
                -and (
                    (-not $requiresAuthorizationGranted) `
                        -or $entry.has_authorization_granted_event
                )
        )
        if ($entry.evidence_present) {
            $presentRoles.Add($role) | Out-Null
        }
    }

    return [pscustomobject]@{
        roles = [pscustomobject]$roleEntries
        auth_roles_present = @($presentRoles)
        overall_auth_evidence_present = ($presentRoles.Count -gt 0)
    }
}

function Invoke-OperatorApi {
    param(
        [string]$Method,
        [string]$ApiBaseUrl,
        [string]$Path,
        [object]$BodyObject = $null,
        [string]$Authorization = "",
        [int[]]$ExpectedStatusCodes = @(200),
        [int]$TimeoutSec = 30
    )

    $url = $ApiBaseUrl.TrimEnd("/") + $Path
    $bodyText = ""
    if ($null -ne $BodyObject) {
        $bodyText = $BodyObject | ConvertTo-Json -Compress -Depth 30
    }

    $tempBodyPath = ""
    $tempResponsePath = Join-Path ([System.IO.Path]::GetTempPath()) ("operator-api-response-" + [guid]::NewGuid().ToString("N") + ".txt")
    $curlArgs = @(
        "-sS",
        "-X",
        $Method,
        $url,
        "-H",
        "Content-Type: application/json",
        "--max-time",
        "$TimeoutSec",
        "--output",
        $tempResponsePath,
        "--write-out",
        "__STATUS__:%{http_code}"
    )
    if (-not [string]::IsNullOrWhiteSpace($Authorization)) {
        $curlArgs += @("-H", ("Authorization: " + $Authorization))
    }
    if (-not [string]::IsNullOrWhiteSpace($bodyText)) {
        $tempBodyPath = Join-Path ([System.IO.Path]::GetTempPath()) ("operator-api-body-" + [guid]::NewGuid().ToString("N") + ".json")
        [System.IO.File]::WriteAllText($tempBodyPath, $bodyText, [System.Text.Encoding]::UTF8)
        $curlArgs += @("--data-binary", ("@" + $tempBodyPath))
    }

    try {
        $output = & curl.exe @curlArgs
        if ($LASTEXITCODE -ne 0) {
            throw ("curl failed for {0} {1}" -f $Method, $url)
        }

        $statusLine = [string]$output
        if ($statusLine -notmatch "^__STATUS__:(\d+)$") {
            throw ("Could not parse status line for {0} {1}: {2}" -f $Method, $url, $statusLine)
        }

        $statusCode = [int]$Matches[1]
        $responseBody = ""
        if (Test-Path $tempResponsePath) {
            $responseBody = [System.IO.File]::ReadAllText($tempResponsePath, [System.Text.Encoding]::UTF8)
        }

        if ($ExpectedStatusCodes -notcontains $statusCode) {
            throw (
                "Unexpected status for {0} {1}: expected [{2}], got [{3}] body={4}" -f
                $Method,
                $url,
                ($ExpectedStatusCodes -join ","),
                $statusCode,
                $responseBody
            )
        }

        [pscustomobject]@{
            Url = $url
            StatusCode = $statusCode
            BodyText = $responseBody
            BodyJson = Convert-OperatorBodyToJsonOrNull -BodyText $responseBody
        }
    } finally {
        if (-not [string]::IsNullOrWhiteSpace($tempBodyPath) -and (Test-Path $tempBodyPath)) {
            Remove-Item -Path $tempBodyPath -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path $tempResponsePath) {
            Remove-Item -Path $tempResponsePath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Save-OperatorJson {
    param(
        [object]$Payload,
        [string]$OutPath
    )

    if ([string]::IsNullOrWhiteSpace($OutPath)) {
        return
    }

    $parent = Split-Path -Parent $OutPath
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 30 | Set-Content -Path $OutPath -Encoding utf8
}

function Convert-OperatorToInt {
    param(
        [object]$Value,
        [int]$Default = 0
    )

    if ($null -eq $Value) {
        return $Default
    }
    if ($Value -is [int]) {
        return [int]$Value
    }
    if ($Value -is [long]) {
        return [int]$Value
    }
    $parsed = 0
    if ([int]::TryParse([string]$Value, [ref]$parsed)) {
        return $parsed
    }
    return $Default
}

function Convert-OperatorToBool {
    param(
        [object]$Value,
        [bool]$Default = $false
    )

    if ($null -eq $Value) {
        return $Default
    }
    if ($Value -is [bool]) {
        return [bool]$Value
    }
    $parsed = $false
    if ([bool]::TryParse([string]$Value, [ref]$parsed)) {
        return $parsed
    }
    return $Default
}

function Convert-OperatorToStringArray {
    param([object]$Value)

    $items = New-Object System.Collections.Generic.List[string]
    if ($null -eq $Value) {
        return @()
    }
    if ($Value -is [string]) {
        $trimmedSingle = $Value.Trim()
        if (-not [string]::IsNullOrWhiteSpace($trimmedSingle)) {
            $items.Add($trimmedSingle) | Out-Null
        }
        return @($items.ToArray())
    }

    if ($Value -is [System.Collections.IEnumerable]) {
        foreach ($entry in $Value) {
            $trimmed = [string]$entry
            $trimmed = $trimmed.Trim()
            if (-not [string]::IsNullOrWhiteSpace($trimmed) -and -not $items.Contains($trimmed)) {
                $items.Add($trimmed) | Out-Null
            }
        }
    } else {
        $trimmed = [string]$Value
        $trimmed = $trimmed.Trim()
        if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
            $items.Add($trimmed) | Out-Null
        }
    }
    return @($items.ToArray())
}

function Convert-OperatorToIntArray {
    param([object]$Value)

    $items = New-Object System.Collections.Generic.List[int]
    if ($null -eq $Value) {
        return @()
    }

    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        foreach ($entry in $Value) {
            $parsed = Convert-OperatorToInt -Value $entry -Default 0
            if ($parsed -gt 0 -and -not $items.Contains($parsed)) {
                $items.Add($parsed) | Out-Null
            }
        }
    } else {
        $parsedSingle = Convert-OperatorToInt -Value $Value -Default 0
        if ($parsedSingle -gt 0) {
            $items.Add($parsedSingle) | Out-Null
        }
    }

    return @($items.ToArray())
}

function Convert-OperatorSetToArray {
    param([object]$Set)

    if ($null -eq $Set) {
        return @()
    }
    $items = New-Object System.Collections.Generic.List[string]
    foreach ($entry in $Set) {
        $value = [string]$entry
        $value = $value.Trim()
        if (-not [string]::IsNullOrWhiteSpace($value) -and -not $items.Contains($value)) {
            $items.Add($value) | Out-Null
        }
    }
    return @($items.ToArray())
}

function Get-OperatorBackendProviderFamily {
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

function Get-OperatorBackendOverrideMismatches {
    param(
        [object]$BackendOverrides,
        [object]$UpstreamProviders
    )

    $mismatches = New-Object System.Collections.Generic.List[string]
    $overrideValues = @(Convert-OperatorToStringArray -Value $BackendOverrides)
    $providerValues = @(Convert-OperatorToStringArray -Value $UpstreamProviders)
    if ($overrideValues.Count -eq 0 -or $providerValues.Count -eq 0) {
        return @()
    }

    foreach ($override in $overrideValues) {
        $expectedProvider = Get-OperatorBackendProviderFamily -BackendModel $override
        if ([string]::IsNullOrWhiteSpace($expectedProvider)) {
            continue
        }
        foreach ($provider in $providerValues) {
            $normalizedProvider = [string]$provider
            $normalizedProvider = $normalizedProvider.Trim().ToLowerInvariant()
            if ([string]::IsNullOrWhiteSpace($normalizedProvider)) {
                continue
            }
            if ($normalizedProvider -ne $expectedProvider) {
                $label = "{0}->{1}" -f $override, $normalizedProvider
                if (-not $mismatches.Contains($label)) {
                    $mismatches.Add($label) | Out-Null
                }
            }
        }
    }

    return @($mismatches.ToArray())
}

function New-OperatorEmptyStageTotals {
    return [ordered]@{
        total_stage_executions = 0
        total_successes = 0
        total_failures = 0
        total_fallbacks = 0
        total_llm_transport_fallbacks = 0
        has_failures = $false
        has_fallbacks = $false
        departments_covered = @()
        llm_endpoints_observed = @()
    }
}

function Normalize-OperatorStageSummaryEntry {
    param([Parameter(Mandatory = $true)]$Entry)

    return [pscustomobject]@{
        department = [string]$Entry.department
        stage_name = [string]$Entry.stage_name
        sequence = Convert-OperatorToInt -Value $Entry.sequence -Default 0
        parent_stage_name = [string]$Entry.parent_stage_name
        execution_count = Convert-OperatorToInt -Value $Entry.execution_count -Default 0
        success_count = Convert-OperatorToInt -Value $Entry.success_count -Default 0
        failure_count = Convert-OperatorToInt -Value $Entry.failure_count -Default 0
        fallback_count = Convert-OperatorToInt -Value $Entry.fallback_count -Default 0
        llm_transport_fallback_count = Convert-OperatorToInt -Value $Entry.llm_transport_fallback_count -Default 0
        failure_reasons = @(Convert-OperatorToStringArray -Value $Entry.failure_reasons)
        effective_providers = @(Convert-OperatorToStringArray -Value $Entry.effective_providers)
        effective_models = @(Convert-OperatorToStringArray -Value $Entry.effective_models)
        llm_endpoints = @(Convert-OperatorToStringArray -Value $Entry.llm_endpoints)
        llm_http_statuses = @(Convert-OperatorToIntArray -Value $Entry.llm_http_statuses)
        llm_error_kinds = @(Convert-OperatorToStringArray -Value $Entry.llm_error_kinds)
        llm_response_modes = @(Convert-OperatorToStringArray -Value $Entry.llm_response_modes)
        llm_content_kinds = @(Convert-OperatorToStringArray -Value $Entry.llm_content_kinds)
        llm_backend_overrides = @(Convert-OperatorToStringArray -Value $Entry.llm_backend_overrides)
        llm_upstream_providers = @(Convert-OperatorToStringArray -Value $Entry.llm_upstream_providers)
        llm_upstream_rejection_reasons = @(Convert-OperatorToStringArray -Value $Entry.llm_upstream_rejection_reasons)
        llm_backend_override_mismatches = @(Convert-OperatorToStringArray -Value $Entry.llm_backend_override_mismatches)
    }
}

function New-OperatorStageTotalsFromSummary {
    param([object[]]$StageSummary = @())

    $totals = New-OperatorEmptyStageTotals
    if ($null -eq $StageSummary -or $StageSummary.Count -eq 0) {
        return $totals
    }

    $deptSet = New-Object System.Collections.Generic.HashSet[string]
    $endpointSet = New-Object System.Collections.Generic.HashSet[string]

    foreach ($stage in $StageSummary) {
        $totals.total_stage_executions += Convert-OperatorToInt -Value $stage.execution_count -Default 0
        $totals.total_successes += Convert-OperatorToInt -Value $stage.success_count -Default 0
        $totals.total_failures += Convert-OperatorToInt -Value $stage.failure_count -Default 0
        $totals.total_fallbacks += Convert-OperatorToInt -Value $stage.fallback_count -Default 0
        $totals.total_llm_transport_fallbacks += Convert-OperatorToInt -Value $stage.llm_transport_fallback_count -Default 0

        $dept = [string]$stage.department
        if (-not [string]::IsNullOrWhiteSpace($dept)) {
            $deptSet.Add($dept) | Out-Null
        }
        foreach ($endpoint in @(Convert-OperatorToStringArray -Value $stage.llm_endpoints)) {
            $endpointSet.Add($endpoint) | Out-Null
        }
    }

    $totals.has_failures = ($totals.total_failures -gt 0)
    $totals.has_fallbacks = ($totals.total_fallbacks -gt 0)
    $totals.departments_covered = @(Convert-OperatorSetToArray -Set $deptSet | Sort-Object)
    $totals.llm_endpoints_observed = @(Convert-OperatorSetToArray -Set $endpointSet | Sort-Object)
    return $totals
}

function Resolve-OperatorStageEventOutcome {
    param([Parameter(Mandatory = $true)]$Metadata)

    $fallbackUsed = Convert-OperatorToBool -Value $Metadata.fallback_used -Default $false
    $reportedStageSuccess = Convert-OperatorToBool -Value $Metadata.stage_success -Default $true

    $failureReason = [string]$Metadata.stage_failure_reason
    if ([string]::IsNullOrWhiteSpace($failureReason)) {
        $failureReason = [string]$Metadata.failure_reason
    }
    $failureReason = $failureReason.Trim()

    $legacyFallbackNormalized = $false
    $effectiveStageSuccess = $reportedStageSuccess
    if (-not $effectiveStageSuccess -and $fallbackUsed -and [string]::IsNullOrWhiteSpace($failureReason)) {
        $effectiveStageSuccess = $true
        $legacyFallbackNormalized = $true
    }

    return [pscustomobject]@{
        reported_stage_success = $reportedStageSuccess
        effective_stage_success = $effectiveStageSuccess
        fallback_used = $fallbackUsed
        failure_reason = $failureReason
        legacy_fallback_normalized = $legacyFallbackNormalized
    }
}

function New-OperatorStageSummaryFromEvents {
    param([object[]]$Events = @())

    $grouped = @{}
    $legacyFallbackNormalizationCount = 0
    foreach ($event in @($Events)) {
        if ($null -eq $event -or [string]$event.event_type -ne "department_stage_executed") {
            continue
        }
        $metadata = $event.metadata
        if ($null -eq $metadata) {
            continue
        }

        $department = [string]$metadata.department
        $stageName = [string]$metadata.stage_name
        $sequence = Convert-OperatorToInt -Value $metadata.sequence -Default 0
        if ([string]::IsNullOrWhiteSpace($department) -or [string]::IsNullOrWhiteSpace($stageName)) {
            continue
        }

        $parentStageName = [string]$metadata.parent_stage_name
        $key = "{0}|{1}|{2}|{3}" -f $department, $sequence, $stageName, $parentStageName
        if (-not $grouped.ContainsKey($key)) {
            $grouped[$key] = [ordered]@{
                department = $department
                stage_name = $stageName
                sequence = $sequence
                parent_stage_name = $parentStageName
                execution_count = 0
                success_count = 0
                failure_count = 0
                fallback_count = 0
                llm_transport_fallback_count = 0
                failure_reasons = New-Object System.Collections.Generic.List[string]
                effective_providers = New-Object System.Collections.Generic.List[string]
                effective_models = New-Object System.Collections.Generic.List[string]
                llm_endpoints = New-Object System.Collections.Generic.List[string]
                llm_http_statuses = New-Object System.Collections.Generic.List[int]
                llm_error_kinds = New-Object System.Collections.Generic.List[string]
                llm_response_modes = New-Object System.Collections.Generic.List[string]
                llm_content_kinds = New-Object System.Collections.Generic.List[string]
                llm_backend_overrides = New-Object System.Collections.Generic.List[string]
                llm_upstream_providers = New-Object System.Collections.Generic.List[string]
                llm_upstream_rejection_reasons = New-Object System.Collections.Generic.List[string]
            }
        }

        $entry = $grouped[$key]
        $entry.execution_count = [int]$entry.execution_count + 1

        $outcome = Resolve-OperatorStageEventOutcome -Metadata $metadata
        if ($outcome.effective_stage_success) {
            $entry.success_count = [int]$entry.success_count + 1
        } else {
            $entry.failure_count = [int]$entry.failure_count + 1
            if (
                -not [string]::IsNullOrWhiteSpace($outcome.failure_reason) `
                    -and -not $entry.failure_reasons.Contains($outcome.failure_reason)
            ) {
                $entry.failure_reasons.Add($outcome.failure_reason) | Out-Null
            }
        }
        if ($outcome.legacy_fallback_normalized) {
            $legacyFallbackNormalizationCount += 1
        }

        if ($outcome.fallback_used) {
            $entry.fallback_count = [int]$entry.fallback_count + 1
        }
        if (Convert-OperatorToBool -Value $metadata.llm_transport_fallback_used -Default $false) {
            $entry.llm_transport_fallback_count = [int]$entry.llm_transport_fallback_count + 1
        }

        $provider = [string]$metadata.effective_provider
        $provider = $provider.Trim()
        if (-not [string]::IsNullOrWhiteSpace($provider) -and -not $entry.effective_providers.Contains($provider)) {
            $entry.effective_providers.Add($provider) | Out-Null
        }
        $model = [string]$metadata.effective_model
        $model = $model.Trim()
        if (-not [string]::IsNullOrWhiteSpace($model) -and -not $entry.effective_models.Contains($model)) {
            $entry.effective_models.Add($model) | Out-Null
        }
        $llmEndpoint = [string]$metadata.llm_endpoint
        $llmEndpoint = $llmEndpoint.Trim()
        if (-not [string]::IsNullOrWhiteSpace($llmEndpoint) -and -not $entry.llm_endpoints.Contains($llmEndpoint)) {
            $entry.llm_endpoints.Add($llmEndpoint) | Out-Null
        }
        $llmErrorKind = [string]$metadata.llm_error_kind
        $llmErrorKind = $llmErrorKind.Trim()
        if (-not [string]::IsNullOrWhiteSpace($llmErrorKind) -and -not $entry.llm_error_kinds.Contains($llmErrorKind)) {
            $entry.llm_error_kinds.Add($llmErrorKind) | Out-Null
        }
        $llmResponseMode = [string]$metadata.llm_response_mode
        $llmResponseMode = $llmResponseMode.Trim()
        if (-not [string]::IsNullOrWhiteSpace($llmResponseMode) -and -not $entry.llm_response_modes.Contains($llmResponseMode)) {
            $entry.llm_response_modes.Add($llmResponseMode) | Out-Null
        }
        $llmContentKind = [string]$metadata.llm_content_kind
        $llmContentKind = $llmContentKind.Trim()
        if (-not [string]::IsNullOrWhiteSpace($llmContentKind) -and -not $entry.llm_content_kinds.Contains($llmContentKind)) {
            $entry.llm_content_kinds.Add($llmContentKind) | Out-Null
        }
        $llmBackendOverride = [string]$metadata.llm_backend_override
        $llmBackendOverride = $llmBackendOverride.Trim()
        if (-not [string]::IsNullOrWhiteSpace($llmBackendOverride) -and -not $entry.llm_backend_overrides.Contains($llmBackendOverride)) {
            $entry.llm_backend_overrides.Add($llmBackendOverride) | Out-Null
        }
        $llmUpstreamProvider = [string]$metadata.llm_upstream_provider
        $llmUpstreamProvider = $llmUpstreamProvider.Trim()
        if (-not [string]::IsNullOrWhiteSpace($llmUpstreamProvider) -and -not $entry.llm_upstream_providers.Contains($llmUpstreamProvider)) {
            $entry.llm_upstream_providers.Add($llmUpstreamProvider) | Out-Null
        }
        $llmUpstreamReason = [string]$metadata.llm_upstream_rejection_reason
        $llmUpstreamReason = $llmUpstreamReason.Trim()
        if (-not [string]::IsNullOrWhiteSpace($llmUpstreamReason) -and -not $entry.llm_upstream_rejection_reasons.Contains($llmUpstreamReason)) {
            $entry.llm_upstream_rejection_reasons.Add($llmUpstreamReason) | Out-Null
        }
        $llmHttpStatus = Convert-OperatorToInt -Value $metadata.llm_http_status -Default 0
        if ($llmHttpStatus -gt 0 -and -not $entry.llm_http_statuses.Contains($llmHttpStatus)) {
            $entry.llm_http_statuses.Add($llmHttpStatus) | Out-Null
        }
    }

    $normalized = New-Object System.Collections.Generic.List[object]
    foreach ($entry in $grouped.Values) {
        $normalizedEntry = Normalize-OperatorStageSummaryEntry -Entry ([pscustomobject]@{
            department = $entry.department
            stage_name = $entry.stage_name
            sequence = $entry.sequence
            parent_stage_name = $entry.parent_stage_name
            execution_count = $entry.execution_count
            success_count = $entry.success_count
            failure_count = $entry.failure_count
            fallback_count = $entry.fallback_count
            llm_transport_fallback_count = $entry.llm_transport_fallback_count
            failure_reasons = @($entry.failure_reasons.ToArray())
            effective_providers = @($entry.effective_providers.ToArray())
            effective_models = @($entry.effective_models.ToArray())
            llm_endpoints = @($entry.llm_endpoints.ToArray())
            llm_http_statuses = @($entry.llm_http_statuses.ToArray())
            llm_error_kinds = @($entry.llm_error_kinds.ToArray())
            llm_response_modes = @($entry.llm_response_modes.ToArray())
            llm_content_kinds = @($entry.llm_content_kinds.ToArray())
            llm_backend_overrides = @($entry.llm_backend_overrides.ToArray())
            llm_upstream_providers = @($entry.llm_upstream_providers.ToArray())
            llm_upstream_rejection_reasons = @($entry.llm_upstream_rejection_reasons.ToArray())
        })
        $normalized.Add($normalizedEntry) | Out-Null
    }

    return [pscustomobject]@{
        stage_summary = @(
            $normalized.ToArray() |
            Sort-Object `
                @{ Expression = { [string]$_.department } }, `
                @{ Expression = { [int]$_.sequence } }, `
                @{ Expression = { [string]$_.stage_name } }
        )
        legacy_fallback_normalizations = $legacyFallbackNormalizationCount
    }
}

function Merge-OperatorStringArrayValues {
    param(
        [object]$Primary,
        [object]$Secondary
    )

    $items = New-Object System.Collections.Generic.List[string]
    foreach ($value in @(Convert-OperatorToStringArray -Value $Primary)) {
        if (-not $items.Contains($value)) {
            $items.Add($value) | Out-Null
        }
    }
    foreach ($value in @(Convert-OperatorToStringArray -Value $Secondary)) {
        if (-not $items.Contains($value)) {
            $items.Add($value) | Out-Null
        }
    }
    return @($items.ToArray())
}

function Merge-OperatorStageSummaryDiagnosticsFromEvents {
    param(
        [object[]]$StageSummary = @(),
        [object[]]$Events = @()
    )

    $eventTelemetry = New-OperatorStageSummaryFromEvents -Events $Events
    $eventSummary = @($eventTelemetry.stage_summary)
    if ($StageSummary.Count -eq 0 -or $eventSummary.Count -eq 0) {
        return [pscustomobject]@{
            stage_summary = @($StageSummary)
            legacy_fallback_normalizations = (Convert-OperatorToInt -Value $eventTelemetry.legacy_fallback_normalizations -Default 0)
        }
    }

    $lookup = @{}
    foreach ($entry in $eventSummary) {
        $key = "{0}|{1}|{2}|{3}" -f [string]$entry.department, [int]$entry.sequence, [string]$entry.stage_name, [string]$entry.parent_stage_name
        $lookup[$key] = $entry
    }

    $merged = New-Object System.Collections.Generic.List[object]
    foreach ($stage in @($StageSummary)) {
        $normalized = Normalize-OperatorStageSummaryEntry -Entry $stage
        $key = "{0}|{1}|{2}|{3}" -f [string]$normalized.department, [int]$normalized.sequence, [string]$normalized.stage_name, [string]$normalized.parent_stage_name
        if ($lookup.ContainsKey($key)) {
            $eventEntry = $lookup[$key]
            $normalized = Normalize-OperatorStageSummaryEntry -Entry ([pscustomobject]@{
                department = $normalized.department
                stage_name = $normalized.stage_name
                sequence = $normalized.sequence
                parent_stage_name = $normalized.parent_stage_name
                execution_count = $normalized.execution_count
                success_count = $normalized.success_count
                failure_count = $normalized.failure_count
                fallback_count = $normalized.fallback_count
                llm_transport_fallback_count = $normalized.llm_transport_fallback_count
                failure_reasons = $normalized.failure_reasons
                effective_providers = $normalized.effective_providers
                effective_models = $normalized.effective_models
                llm_endpoints = $normalized.llm_endpoints
                llm_http_statuses = $normalized.llm_http_statuses
                llm_error_kinds = $normalized.llm_error_kinds
                llm_response_modes = $normalized.llm_response_modes
                llm_content_kinds = Merge-OperatorStringArrayValues -Primary $normalized.llm_content_kinds -Secondary $eventEntry.llm_content_kinds
                llm_backend_overrides = Merge-OperatorStringArrayValues -Primary $normalized.llm_backend_overrides -Secondary $eventEntry.llm_backend_overrides
                llm_upstream_providers = Merge-OperatorStringArrayValues -Primary $normalized.llm_upstream_providers -Secondary $eventEntry.llm_upstream_providers
                llm_upstream_rejection_reasons = Merge-OperatorStringArrayValues -Primary $normalized.llm_upstream_rejection_reasons -Secondary $eventEntry.llm_upstream_rejection_reasons
            })
        }
        $merged.Add($normalized) | Out-Null
    }

    return [pscustomobject]@{
        stage_summary = @($merged.ToArray())
        legacy_fallback_normalizations = (Convert-OperatorToInt -Value $eventTelemetry.legacy_fallback_normalizations -Default 0)
    }
}

function Get-OperatorStageTelemetry {
    param(
        [Parameter(Mandatory = $true)]$Audit,
        [switch]$AllowDerivedFromEvents
    )

    $rawSummary = $Audit.department_stage_summary
    $normalizedSummary = New-Object System.Collections.Generic.List[object]
    if ($null -ne $rawSummary) {
        foreach ($entry in @($rawSummary | Where-Object { $null -ne $_ })) {
            $normalizedSummary.Add((Normalize-OperatorStageSummaryEntry -Entry $entry)) | Out-Null
        }
    }
    $summary = @($normalizedSummary.ToArray())
    if ($summary.Count -gt 0 -and $null -ne $Audit.events) {
        $summaryDiagnostics = Merge-OperatorStageSummaryDiagnosticsFromEvents -StageSummary $summary -Events @($Audit.events)
        $summary = @($summaryDiagnostics.stage_summary)
    }
    foreach ($stage in @($summary)) {
        $existingMismatches = @(Convert-OperatorToStringArray -Value $stage.llm_backend_override_mismatches)
        $mismatches = Get-OperatorBackendOverrideMismatches `
            -BackendOverrides $stage.llm_backend_overrides `
            -UpstreamProviders $stage.llm_upstream_providers
        $stage.llm_backend_override_mismatches = @(
            Merge-OperatorStringArrayValues `
                -Primary $existingMismatches `
                -Secondary $mismatches
        )
    }
    $rawTotals = $Audit.department_stage_totals
    $notes = New-Object System.Collections.Generic.List[string]

    if ($summary.Count -gt 0) {
        if ($null -ne $rawTotals) {
            $totals = New-OperatorEmptyStageTotals
            $totals.total_stage_executions = Convert-OperatorToInt -Value $rawTotals.total_stage_executions -Default 0
            $totals.total_successes = Convert-OperatorToInt -Value $rawTotals.total_successes -Default 0
            $totals.total_failures = Convert-OperatorToInt -Value $rawTotals.total_failures -Default 0
            $totals.total_fallbacks = Convert-OperatorToInt -Value $rawTotals.total_fallbacks -Default 0
            $totals.total_llm_transport_fallbacks = Convert-OperatorToInt -Value $rawTotals.total_llm_transport_fallbacks -Default 0
            $totals.has_failures = Convert-OperatorToBool -Value $rawTotals.has_failures -Default ($totals.total_failures -gt 0)
            $totals.has_fallbacks = Convert-OperatorToBool -Value $rawTotals.has_fallbacks -Default ($totals.total_fallbacks -gt 0)
            $totals.departments_covered = Convert-OperatorToStringArray -Value $rawTotals.departments_covered
            $totals.llm_endpoints_observed = Convert-OperatorToStringArray -Value $rawTotals.llm_endpoints_observed
            return [pscustomobject]@{
                telemetry_present = $true
                telemetry_source = "audit_totals"
                stage_summary = $summary
                stage_totals = $totals
                notes = @($notes.ToArray())
                legacy_fallback_normalizations = 0
            }
        }

        $notes.Add("department_stage_totals missing; derived totals from department_stage_summary.") | Out-Null
        return [pscustomobject]@{
            telemetry_present = $true
            telemetry_source = "summary_derived"
            stage_summary = $summary
            stage_totals = New-OperatorStageTotalsFromSummary -StageSummary $summary
            notes = @($notes.ToArray())
            legacy_fallback_normalizations = 0
        }
    }

    if ($AllowDerivedFromEvents) {
        $eventTelemetry = New-OperatorStageSummaryFromEvents -Events @($Audit.events)
        $eventSummary = @($eventTelemetry.stage_summary)
        $legacyFallbackNormalizations = Convert-OperatorToInt `
            -Value $eventTelemetry.legacy_fallback_normalizations `
            -Default 0
        if ($eventSummary.Count -gt 0) {
            foreach ($stage in @($eventSummary)) {
                $existingMismatches = @(Convert-OperatorToStringArray -Value $stage.llm_backend_override_mismatches)
                $mismatches = Get-OperatorBackendOverrideMismatches `
                    -BackendOverrides $stage.llm_backend_overrides `
                    -UpstreamProviders $stage.llm_upstream_providers
                $stage.llm_backend_override_mismatches = @(
                    Merge-OperatorStringArrayValues `
                        -Primary $existingMismatches `
                        -Secondary $mismatches
                )
            }
            $notes.Add("department_stage_summary/totals missing; reconstructed telemetry from department_stage_executed events.") | Out-Null
            if ($legacyFallbackNormalizations -gt 0) {
                $notes.Add((
                    "events_derived normalized {0} legacy fallback-only stage event(s) " +
                    "without stage_failure_reason as success+fallback." -f
                    $legacyFallbackNormalizations
                )) | Out-Null
            }
            return [pscustomobject]@{
                telemetry_present = $true
                telemetry_source = "events_derived"
                stage_summary = $eventSummary
                stage_totals = New-OperatorStageTotalsFromSummary -StageSummary $eventSummary
                notes = @($notes.ToArray())
                legacy_fallback_normalizations = $legacyFallbackNormalizations
            }
        }
    }

    $notes.Add("No department stage telemetry available in audit payload.") | Out-Null
    return [pscustomobject]@{
        telemetry_present = $false
        telemetry_source = "none"
        stage_summary = @()
        stage_totals = New-OperatorEmptyStageTotals
        notes = @($notes.ToArray())
        legacy_fallback_normalizations = 0
    }
}

function Resolve-OperatorAbsolutePath {
    param(
        [string]$Path,
        [string]$BasePath = ""
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ""
    }

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    if (-not [string]::IsNullOrWhiteSpace($BasePath)) {
        return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Path))
    }

    return [System.IO.Path]::GetFullPath($Path)
}

function Get-OperatorRelativePath {
    param(
        [string]$Path,
        [string]$RootPath
    )

    if ([string]::IsNullOrWhiteSpace($Path) -or [string]::IsNullOrWhiteSpace($RootPath)) {
        return ""
    }

    $resolvedPath = Resolve-OperatorAbsolutePath -Path $Path
    $resolvedRoot = Resolve-OperatorAbsolutePath -Path $RootPath
    $rootWithSlash = $resolvedRoot.TrimEnd('\') + '\'
    $rootUri = [System.Uri]$rootWithSlash
    $pathUri = [System.Uri]$resolvedPath
    return [System.Uri]::UnescapeDataString($rootUri.MakeRelativeUri($pathUri).ToString()).Replace('/', '\')
}

function Get-OperatorObjectPropertyValue {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object -or [string]::IsNullOrWhiteSpace($Name)) {
        return $null
    }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) {
            return $Object[$Name]
        }
        return $null
    }

    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) {
        return $property.Value
    }
    return $null
}

function New-OperatorManifestArtifactEntry {
    param(
        [string]$Path,
        [string]$RepoRoot
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    $resolvedPath = Resolve-OperatorAbsolutePath -Path $Path -BasePath $RepoRoot
    return [ordered]@{
        path = $resolvedPath
        relative_path = Get-OperatorRelativePath -Path $resolvedPath -RootPath $RepoRoot
    }
}

function Read-OperatorBundleManifest {
    param([string]$Path)

    $manifest = Read-OperatorJsonFile -Path $Path
    $bundleType = [string](Get-OperatorObjectPropertyValue -Object $manifest -Name "bundle_type")
    if ([string]::IsNullOrWhiteSpace($bundleType)) {
        throw ("Bundle manifest missing bundle_type: {0}" -f $Path)
    }
    return $manifest
}

function Get-OperatorBundleArtifactEntry {
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)][string]$ArtifactName
    )

    $artifacts = Get-OperatorObjectPropertyValue -Object $Manifest -Name "artifacts"
    if ($null -eq $artifacts) {
        return $null
    }
    return Get-OperatorObjectPropertyValue -Object $artifacts -Name $ArtifactName
}

function Resolve-OperatorBundleArtifactPath {
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)][string]$ArtifactName,
        [string]$RepoRoot = ""
    )

    $entry = Get-OperatorBundleArtifactEntry -Manifest $Manifest -ArtifactName $ArtifactName
    if ($null -eq $entry) {
        return ""
    }

    if ($entry -is [string]) {
        return Resolve-OperatorAbsolutePath -Path ([string]$entry) -BasePath $RepoRoot
    }

    $path = [string](Get-OperatorObjectPropertyValue -Object $entry -Name "path")
    if (-not [string]::IsNullOrWhiteSpace($path)) {
        return Resolve-OperatorAbsolutePath -Path $path -BasePath $RepoRoot
    }

    $relativePath = [string](Get-OperatorObjectPropertyValue -Object $entry -Name "relative_path")
    if (-not [string]::IsNullOrWhiteSpace($relativePath)) {
        return Resolve-OperatorAbsolutePath -Path $relativePath -BasePath $RepoRoot
    }
    return ""
}

function Resolve-OperatorBundlePrimarySummaryPath {
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [string]$RepoRoot = ""
    )

    $bundleType = [string](Get-OperatorObjectPropertyValue -Object $Manifest -Name "bundle_type")
    if ($bundleType -eq "cycle") {
        return Resolve-OperatorBundleArtifactPath -Manifest $Manifest -ArtifactName "summary" -RepoRoot $RepoRoot
    }
    if ($bundleType -eq "suite") {
        return Resolve-OperatorBundleArtifactPath -Manifest $Manifest -ArtifactName "suite_summary" -RepoRoot $RepoRoot
    }
    return ""
}

function Resolve-OperatorCycleBundleContext {
    param(
        [Parameter(Mandatory = $true)][string]$BundleManifestPath,
        [string]$RepoRoot = ""
    )

    $manifest = Read-OperatorBundleManifest -Path $BundleManifestPath
    $bundleType = [string](Get-OperatorObjectPropertyValue -Object $manifest -Name "bundle_type")
    if ($bundleType -ne "cycle") {
        throw ("Bundle manifest must be a cycle bundle: {0}" -f $BundleManifestPath)
    }

    return [pscustomobject]@{
        manifest = $manifest
        manifest_path = Resolve-OperatorAbsolutePath -Path $BundleManifestPath -BasePath $RepoRoot
        summary_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "summary" -RepoRoot $RepoRoot
        audit_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "audit" -RepoRoot $RepoRoot
        status_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "status" -RepoRoot $RepoRoot
        status_summary_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "status_summary" -RepoRoot $RepoRoot
        stage_report_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "stage_report" -RepoRoot $RepoRoot
        audit_assert_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "audit_assert" -RepoRoot $RepoRoot
        project_id = [string](Get-OperatorObjectPropertyValue -Object $manifest -Name "project_id")
        mode = [string](Get-OperatorObjectPropertyValue -Object $manifest -Name "mode")
        final_status = [string](Get-OperatorObjectPropertyValue -Object $manifest -Name "final_status")
    }
}

function Resolve-OperatorSuiteBundleContext {
    param(
        [Parameter(Mandatory = $true)][string]$BundleManifestPath,
        [string]$RepoRoot = ""
    )

    $manifest = Read-OperatorBundleManifest -Path $BundleManifestPath
    $bundleType = [string](Get-OperatorObjectPropertyValue -Object $manifest -Name "bundle_type")
    if ($bundleType -ne "suite") {
        throw ("Bundle manifest must be a suite bundle: {0}" -f $BundleManifestPath)
    }

    $cycles = New-Object System.Collections.Generic.List[object]
    foreach ($cycle in @($manifest.cycles)) {
        if ($null -eq $cycle) {
            continue
        }
        $cycles.Add([pscustomobject]@{
            mode = [string](Get-OperatorObjectPropertyValue -Object $cycle -Name "mode")
            summary_path = Resolve-OperatorAbsolutePath `
                -Path ([string](Get-OperatorObjectPropertyValue -Object $cycle -Name "summary_path")) `
                -BasePath $RepoRoot
            status_summary_path = Resolve-OperatorAbsolutePath `
                -Path ([string](Get-OperatorObjectPropertyValue -Object $cycle -Name "status_summary_path")) `
                -BasePath $RepoRoot
            bundle_manifest_path = Resolve-OperatorAbsolutePath `
                -Path ([string](Get-OperatorObjectPropertyValue -Object $cycle -Name "bundle_manifest_path")) `
                -BasePath $RepoRoot
            project_id = [string](Get-OperatorObjectPropertyValue -Object $cycle -Name "project_id")
            final_status = [string](Get-OperatorObjectPropertyValue -Object $cycle -Name "final_status")
        }) | Out-Null
    }

    return [pscustomobject]@{
        manifest = $manifest
        manifest_path = Resolve-OperatorAbsolutePath -Path $BundleManifestPath -BasePath $RepoRoot
        summary_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "suite_summary" -RepoRoot $RepoRoot
        stage_gate_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "stage_gate" -RepoRoot $RepoRoot
        handoff_json_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "handoff_json" -RepoRoot $RepoRoot
        handoff_markdown_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "handoff_markdown" -RepoRoot $RepoRoot
        cycles = @($cycles.ToArray())
    }
}

function Resolve-ReadinessBundleContext {
    param(
        [Parameter(Mandatory = $true)][string]$ReadinessManifestPath,
        [string]$RepoRoot = ""
    )

    $manifest = Read-OperatorBundleManifest -Path $ReadinessManifestPath
    $bundleType = [string](Get-OperatorObjectPropertyValue -Object $manifest -Name "bundle_type")
    if ($bundleType -ne "readiness") {
        throw ("Bundle manifest must be a readiness bundle: {0}" -f $ReadinessManifestPath)
    }

    $operatorSuiteManifestPath = Resolve-OperatorBundleArtifactPath `
        -Manifest $manifest `
        -ArtifactName "operator_suite_manifest" `
        -RepoRoot $RepoRoot
    $operatorSuiteSummaryPath = Resolve-OperatorBundleArtifactPath `
        -Manifest $manifest `
        -ArtifactName "operator_suite_summary" `
        -RepoRoot $RepoRoot
    $operatorSuiteStageGatePath = Resolve-OperatorBundleArtifactPath `
        -Manifest $manifest `
        -ArtifactName "operator_suite_stage_gate" `
        -RepoRoot $RepoRoot
    $operatorSuiteHandoffPath = Resolve-OperatorBundleArtifactPath `
        -Manifest $manifest `
        -ArtifactName "operator_suite_handoff" `
        -RepoRoot $RepoRoot

    return [pscustomobject]@{
        manifest = $manifest
        manifest_path = Resolve-OperatorAbsolutePath -Path $ReadinessManifestPath -BasePath $RepoRoot
        summary_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "readiness_summary" -RepoRoot $RepoRoot
        live_smoke_log_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "live_smoke_log" -RepoRoot $RepoRoot
        seed_log_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "full_live_flow_seed_log" -RepoRoot $RepoRoot
        operator_suite_manifest_path = $operatorSuiteManifestPath
        operator_suite_summary_path = $operatorSuiteSummaryPath
        operator_suite_stage_gate_path = $operatorSuiteStageGatePath
        operator_suite_handoff_path = $operatorSuiteHandoffPath
        openclaw_evidence_path = Resolve-OperatorBundleArtifactPath -Manifest $manifest -ArtifactName "openclaw_evidence" -RepoRoot $RepoRoot
    }
}
