# Operator Workflow Runbook

## Overview

This runbook describes the end-to-end operator workflow for running projects through the AI Work System orchestrator.

Runtime/storage split reference:
- `docs/runtime_storage_boundary.md`

## Server Setup

Before running any operator commands, start the API server.

**Recommended (uses `.env` for configuration):**

```powershell
# Copy env template once (edit as needed)
Copy-Item .env.example .env

# Start server — reads .env automatically, creates data/ if needed
.\scripts\ai_work_system\start-server.ps1
# Phase 6 OpenClaw baseline — forces department routing to openclaw/codex-orchestrator
.\scripts\ai_work_system\start-server.ps1 -UseOpenClawDefaultProfile
# Dry-run the effective startup profile without launching uvicorn
.\scripts\ai_work_system\start-server.ps1 -UseOpenClawDefaultProfile -PrintEffectiveConfigOnly
```

Legacy compatibility aliases (still supported):

```powershell
.\scripts\start-server.ps1
.\scripts\start-server.ps1 -UseOpenClawDefaultProfile
```

**Manual (inline env vars):**

```powershell
$env:STATE_BACKEND = "sqlite"
$env:SQLITE_DB_PATH = "data/codex.db"
$env:STATE_BACKEND_STRICT = "true"
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

The server runs in the foreground. Open a second terminal for operator commands.

## Prerequisites

1. API server running (see Server Setup above)
2. Readiness gate passed: `.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token"`
3. For persistent state: set `STATE_BACKEND=sqlite` in environment or `.env`

Commercial auth mode (optional, non-dev profile):

```powershell
$env:AUTH_SERVICE_MODE = "commercial_token"
$env:AUTH_ENABLED = "true"
$env:AUTH_TOKEN_SEED = "commercial-operator:ops-1:operator:human,commercial-approver:apr-1:approver:human"
```

When enabled:
- use `Bearer commercial-approver` for approve/reject routes
- use `Bearer commercial-operator` for revise/replan routes
- `DEV_AUTH_*` token mappings are not used for route authentication

Optional (if using OpenClaw-routed department models):

```powershell
.\scripts\openclaw-gateway-check.ps1
.\scripts\openclaw-gateway-check.ps1 -AgentId codex-orchestrator -BackendModel openai-codex/gpt-5.2
.\scripts\openclaw-gateway-check.ps1 -TimeoutSec 60 -ProbeTimeoutSec 20
.\scripts\openclaw-gateway-check.ps1 -NoResponsesFallback
.\scripts\openclaw-gateway-check.ps1 -EvidenceOutPath .\logs\staging\openclaw-check.json -AppendStagingRecord
.\scripts\openclaw-evidence-capture.ps1
```

Token resolution order:
1. `-AuthToken` parameter
2. `OPENCLAW_GATEWAY_TOKEN` environment variable
3. `~/.openclaw/openclaw.json` (`gateway.auth.token`)

If the check returns `404`, OpenClaw HTTP endpoints are likely disabled.
Enable at least one endpoint in `~/.openclaw/openclaw.json` (JSON5):

```json5
{
  gateway: {
    http: {
      endpoints: {
        chatCompletions: { enabled: true },
        responses: { enabled: true },
      },
    },
  },
}
```

After updating config, restart/reload OpenClaw Gateway and rerun `openclaw-gateway-check.ps1`.
Evidence JSON includes `/v1/models` probe details:
- `models_probe_status_code`
- `models_probe_content_type`
- `models_probe_model_ids`
- `models_probe_agent_model_present`

Intake extraction mode:
- Default is deterministic regex-first intake (`INTAKE_USE_LLM=0`).
- To allow intake to fill missing fields via LLM, set `INTAKE_USE_LLM=1`.
- `INTAKE_MODEL` is optional and falls back to `RESEARCH_MODEL` when unset.

Live LLM structured-output contract (opt-in):

```powershell
$env:RUN_LIVE_LLM_CONTRACT = "1"
$env:OPENCLAW_BASE_URL = "http://127.0.0.1:18789"
$env:OPENCLAW_AGENT_ID = "codex-orchestrator"
$env:OPENCLAW_GATEWAY_TOKEN = "<gateway-token>"
python -m pytest -q tests/test_live_llm_contract_optin.py
```

Use this only for live runtime validation and staging evidence capture.
If the test fails with `401 Unauthorized`, refresh gateway auth/token (`OPENCLAW_GATEWAY_TOKEN`) and retry.

Operator API timeout policy:
- all operator scripts accept `-TimeoutSec <seconds>`
- when omitted, scripts use `OPERATOR_API_TIMEOUT_SECONDS` from environment (default `30`)

### OpenClaw live profile timeout guidance (phase_6 strict)

When department models are routed through OpenClaw (`-UseOpenClawDefaultProfile`),
end-to-end latency can exceed the default 30-second operator timeout even when the
transport path is healthy.

Operational recommendation for strict phase_6 runs:
- use `-TimeoutSec 600` for `operator-run.ps1` and `operator-full-cycle.ps1`
- or set `OPERATOR_API_TIMEOUT_SECONDS=600` in the current shell/session

Example:

```powershell
$env:OPERATOR_API_TIMEOUT_SECONDS = "600"

.\scripts\operator-run.ps1 `
  -BriefPath .\examples\briefs\phase6_real_brief.json `
  -TrendProvider gemini-flash-lite-latest

.\scripts\operator-full-cycle.ps1 `
  -Mode approval `
  -BriefPath .\examples\briefs\phase6_real_brief.json `
  -RunTrendProvider gemini-flash-lite-latest `
  -RequireStageTelemetry `
  -FailOnFallback `
  -MaxLlmTransportFallbacks 0 `
  -TimeoutSec 600
```

If a run times out at 30/180 seconds but succeeds at 600 seconds, classify it as a
latency-budget issue (not an endpoint/transport outage) and keep strict gate policy
unchanged (`completed` required, no fallback budget relaxation).

## Project Status Reference

| Status | Meaning | Next Action |
|--------|---------|-------------|
| `in_progress` | Execution running | Wait or check audit |
| `waiting_approval` | Paused at approval gate | Run `operator-approve.ps1` or `operator-reject.ps1` |
| `revision_requested` | Review failed or rejected | Run `operator-revise.ps1` |
| `ready_for_planning` | Waiting for replanning execution | Run `operator-replan.ps1` |
| `completed` | All tasks done | Review audit with `operator-audit.ps1` |

## Full Workflow: mock provider (no approval needed)

```powershell
# 1. Start a project
.\scripts\operator-run.ps1 -BriefPath .\examples\briefs\sample_brief.json

# 2. Check status (use project_id from step 1)
.\scripts\operator-status.ps1 -ProjectId <project_id> -TimeoutSec 45

# 3. View full audit
.\scripts\operator-audit.ps1 -ProjectId <project_id> -Full -TimeoutSec 45
# 4. Optional: compact stage diagnostics
.\scripts\operator-stage-report.ps1 -ProjectId <project_id> -TimeoutSec 45
# 5. Optional: assert audit invariants
.\scripts\operator-audit-assert.ps1 -ProjectId <project_id> -ExpectedStatus completed -TimeoutSec 45
```

Expected final status: `completed`

One-command equivalent (writes run/status/audit/stage evidence bundle):

```powershell
.\scripts\operator-full-cycle.ps1 -Mode approval -RunTrendProvider mock
```

## Full Workflow: external provider with approval gate

```powershell
# 1. Start with external provider (will pause at waiting_approval)
.\scripts\operator-run.ps1 -BriefPath .\examples\briefs\sample_brief.json -TrendProvider gemini-flash-lite-latest -TimeoutSec 45

# 2. Check status -> should show waiting_approval
.\scripts\operator-status.ps1 -ProjectId <project_id> -TimeoutSec 45

# 3a. Approve and continue
.\scripts\operator-approve.ps1 -ProjectId <project_id> -TimeoutSec 45

# OR 3b. Reject
.\scripts\operator-reject.ps1 -ProjectId <project_id> -Reason "Security policy violation" -TimeoutSec 45

# If rejected -> revision_requested, then:
.\scripts\operator-revise.ps1 -ProjectId <project_id> -ResumeMode replanning -TimeoutSec 45

# After revise -> ready_for_planning, then:
.\scripts\operator-replan.ps1 -ProjectId <project_id> -TimeoutSec 45

# 4. Final audit
.\scripts\operator-audit.ps1 -ProjectId <project_id> -Full -TimeoutSec 45
# 5. Optional: compact stage diagnostics
.\scripts\operator-stage-report.ps1 -ProjectId <project_id> -TimeoutSec 45
# 6. Optional: assert audit invariants
.\scripts\operator-audit-assert.ps1 -ProjectId <project_id> -ExpectedStatus completed -TimeoutSec 45
```

One-command alternatives:

```powershell
# approval path
.\scripts\operator-full-cycle.ps1 -Mode approval

# reject -> revision -> replanning path
.\scripts\operator-full-cycle.ps1 -Mode reject-replan
```

Two-path suite (approval + reject/replan in one command):

```powershell
.\scripts\operator-cycle-suite.ps1
.\scripts\operator-cycle-suite.ps1 -OutputDir .\logs\operator-suites\manual-suite-001
```

## Script Reference

### operator-run.ps1
Start a new project from a brief JSON file.

```powershell
.\scripts\operator-run.ps1 -BriefPath .\examples\briefs\sample_brief.json
.\scripts\operator-run.ps1 -BriefPath .\examples\briefs\sample_brief.json -TrendProvider gemini-flash-lite-latest
.\scripts\operator-run.ps1 -BriefPath .\examples\briefs\sample_brief.json -ApprovedActions "external_api_send"
.\scripts\operator-run.ps1 -BriefPath .\examples\briefs\sample_brief.json -TimeoutSec 45
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-BriefPath` | `.\examples\briefs\sample_brief.json` | Path to brief JSON |
| `-TrendProvider` | `mock` | `mock`, `gemini-flash-lite-latest`, `openai`, `grok` |
| `-ApprovedActions` | `""` | Comma-separated action types to pre-approve |
| `-SimulateReviewFailure` | off | Force review failure for testing |
| `-TimeoutSec` | env/default | API timeout seconds (`OPERATOR_API_TIMEOUT_SECONDS` fallback) |

### operator-status.ps1
Show current project status and approval summary.

```powershell
.\scripts\operator-status.ps1 -ProjectId <id>
.\scripts\operator-status.ps1 -ProjectId <id> -TimeoutSec 45
.\scripts\operator-status.ps1 -ProjectId <id> -OutPath .\logs\operator-status.json
.\scripts\operator-status.ps1 -ProjectId <id> -SummaryOutPath .\logs\operator-status-summary.json
.\scripts\operator-status.ps1 -ProjectId <id> -AuditJsonPath .\logs\operator-cycles\<stamp>\approval\audit.json
.\scripts\operator-status.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json
.\scripts\operator-status.ps1 -ProjectId <id> -NoEventDerivedTelemetry
```

`operator-status.ps1` now prints:
- telemetry source (`audit_totals`, `summary_derived`, `events_derived`, `none`)
- `llm fb` transport fallback totals
- `legacy fix` count when fallback-only legacy events were normalized
- stage endpoints/departments when telemetry is available

`-OutPath` still writes the raw audit payload.
`-SummaryOutPath` writes a compact status + telemetry JSON for dashboards/replay.
`operator-full-cycle.ps1` now writes the same compact file as
`<outputDir>\status-summary.json`, and `operator-cycle-suite.ps1` carries those
paths into `suite-summary.json`, `suite-handoff.json`, and `suite-stage-gate.json`.
Each cycle/suite bundle also writes `bundle-manifest.json`, which is the
preferred replay entrypoint for downstream tools.

### operator-approve.ps1
Approve pending actions and resume execution.

```powershell
.\scripts\operator-approve.ps1 -ProjectId <id>
.\scripts\operator-approve.ps1 -ProjectId <id> -Authorization "Bearer dev-approver-token"
.\scripts\operator-approve.ps1 -ProjectId <id> -ApprovedActions "external_api_send" -Note "Reviewed and approved"
.\scripts\operator-approve.ps1 -ProjectId <id> -TimeoutSec 45
.\scripts\operator-approve.ps1 -ProjectId <id> -OutPath .\logs\operator-approve.json
```

### operator-reject.ps1
Reject pending actions (transitions to `revision_requested`).

```powershell
.\scripts\operator-reject.ps1 -ProjectId <id> -Reason "Security policy"
.\scripts\operator-reject.ps1 -ProjectId <id> -Reason "Not compliant" -RejectedActions "external_api_send"
.\scripts\operator-reject.ps1 -ProjectId <id> -Reason "Security policy" -TimeoutSec 45
.\scripts\operator-reject.ps1 -ProjectId <id> -Reason "Security policy" -OutPath .\logs\operator-reject.json
```

### operator-revise.ps1
Resume from `revision_requested` state.

```powershell
.\scripts\operator-revise.ps1 -ProjectId <id>
.\scripts\operator-revise.ps1 -ProjectId <id> -ResumeMode replanning
.\scripts\operator-revise.ps1 -ProjectId <id> -ResumeMode rebuilding -Reason "Architecture change required"
.\scripts\operator-revise.ps1 -ProjectId <id> -TimeoutSec 45
.\scripts\operator-revise.ps1 -ProjectId <id> -OutPath .\logs\operator-revise.json
```

Valid `-ResumeMode` values: `replanning`, `rebuilding`, `rereview`

### operator-replan.ps1
Execute replanning from `ready_for_planning` state.

```powershell
.\scripts\operator-replan.ps1 -ProjectId <id>
.\scripts\operator-replan.ps1 -ProjectId <id> -TrendProvider gemini-flash-lite-latest
.\scripts\operator-replan.ps1 -ProjectId <id> -Note "Architecture revised"
.\scripts\operator-replan.ps1 -ProjectId <id> -TimeoutSec 45
.\scripts\operator-replan.ps1 -ProjectId <id> -OutPath .\logs\operator-replan.json
```

### operator-audit.ps1
View project audit trail.

```powershell
.\scripts\operator-audit.ps1 -ProjectId <id>
.\scripts\operator-audit.ps1 -ProjectId <id> -Full
.\scripts\operator-audit.ps1 -ProjectId <id> -TimeoutSec 45
.\scripts\operator-audit.ps1 -ProjectId <id> -AuditJsonPath .\logs\operator-cycles\<stamp>\approval\audit.json
.\scripts\operator-audit.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json
```

`-Full` adds state history and all events with actor context.

`operator-audit.ps1` prints a `[Department Stage Summary]` section whenever
telemetry can be resolved, including:
- runs / success / failure / fallback counts per stage
- distinct failure reasons (if any)
- observed effective models
- telemetry source (`audit_totals`, `summary_derived`, or `events_derived`)

When `department_stage_totals` are missing, scripts derive telemetry from
`department_stage_executed` events for backward compatibility.
If older fallback-only stage events omit `stage_failure_reason`, scripts
normalize them as `success + fallback`, surface a telemetry note, and carry the
normalization count into stage/suite/handoff evidence.

### operator-stage-report.ps1
Generate a compact stage diagnostics report from audit data.

```powershell
.\scripts\operator-stage-report.ps1 -ProjectId <id>
.\scripts\operator-stage-report.ps1 -ProjectId <id> -TimeoutSec 45
.\scripts\operator-stage-report.ps1 -ProjectId <id> -OutPath .\logs\stage-report.json
.\scripts\operator-stage-report.ps1 -ProjectId <id> -RequireStageTelemetry
.\scripts\operator-stage-report.ps1 -ProjectId <id> -AuditJsonPath .\logs\operator-cycles\<stamp>\approval\audit.json
.\scripts\operator-stage-report.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json
.\scripts\operator-stage-report.ps1 -ProjectId <id> -NoEventDerivedTelemetry
```

Output includes:
- stage totals (`runs/success/failure/fallback`)
- failing stages (with failure reasons)
- fallback stages
- telemetry source and derivation notes
- `telemetry_legacy_fallback_normalizations` when old fallback-only events were normalized

### operator-audit-assert.ps1
Run machine-checkable assertions against audit/stage telemetry consistency.

```powershell
.\scripts\operator-audit-assert.ps1 -ProjectId <id> -ExpectedStatus completed
.\scripts\operator-audit-assert.ps1 -ProjectId <id> -ExpectedStatus completed -FailOnFallback
.\scripts\operator-audit-assert.ps1 -ProjectId <id> -RequireDepartments "build,review" -OutPath .\logs\audit-assert.json
.\scripts\operator-audit-assert.ps1 -ProjectId <id> -ExpectedStatus completed -MaxLlmTransportFallbacks 0
.\scripts\operator-audit-assert.ps1 -ProjectId <id> -ExpectedStatus completed -EnforceModelAllowlist -PolicyMode strict -FailOnBackendOverrideMismatch
.\scripts\operator-audit-assert.ps1 -ProjectId <id> -ExpectedStatus completed -RequireAuthEvidence -ExpectedAuthRoles "operator,approver" -AuthPolicyMode strict
.\scripts\operator-audit-assert.ps1 -ProjectId <id> -ExpectedStatus completed -Breakglass -BreakglassReason "temporary remediation" -BreakglassActor "<operator-id>"
.\scripts\operator-audit-assert.ps1 -ProjectId <id> -AuditJsonPath .\logs\operator-cycles\<stamp>\approval\audit.json
.\scripts\operator-audit-assert.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json -ExpectedStatus completed
.\scripts\operator-audit-assert.ps1 -ProjectId <id> -RequireStageTelemetry -NoEventDerivedTelemetry
```

Assertions include:
- `project_id` and optional expected status match
- stage summary uniqueness (`department + sequence + stage_name`)
- per-stage count consistency (`success + failure == execution`)
- totals consistency (`summary` sums match `department_stage_totals`)
- optional fallback policy (`-FailOnFallback`)
- optional LLM transport fallback budget (`-MaxLlmTransportFallbacks`)
- optional strict model allowlist policy (`-EnforceModelAllowlist`, default policy file `docs/model_routing_policy.json`)
- optional deny-on-backend-override-mismatch policy (`-FailOnBackendOverrideMismatch`)
- optional strict auth boundary assertions (`-RequireAuthEvidence`, `-ExpectedAuthRoles`, `-AuthPolicyMode`)
- optional breakglass evidence assertions (`-Breakglass`, `-BreakglassReason`, `-BreakglassActor`)

### operator-full-cycle.ps1
Run a complete operator flow and persist all intermediate outputs in one bundle.

```powershell
.\scripts\operator-full-cycle.ps1 -Mode approval
.\scripts\operator-full-cycle.ps1 -Mode reject-replan
.\scripts\operator-full-cycle.ps1 -Mode approval -OutputDir .\logs\operator-cycles\manual-run-001
```

Bundle outputs:
- run.json
- approve.json or reject.json + revise.json + replan.json (mode dependent)
- status.json
- status-summary.json
- audit.json
- stage-report.json (unless `-SkipStageReport`)
- audit-assert.json (unless `-SkipAuditAssertions`)
- bundle-manifest.json
- summary.json (top-level pointer + final status)

### operator-cycle-suite.ps1
Run both major operator paths in one bundled command and generate suite handoff artifacts.

```powershell
.\scripts\operator-cycle-suite.ps1
.\scripts\operator-cycle-suite.ps1 -SkipRejectReplanMode
.\scripts\operator-cycle-suite.ps1 -FailOnFallback
.\scripts\operator-cycle-suite.ps1 -MaxSuiteStageFallbacks 0 -FailOnStageGateViolation
.\scripts\operator-cycle-suite.ps1 -MaxSuiteLlmTransportFallbacks 0 -FailOnStageGateViolation
.\scripts\operator-cycle-suite.ps1 -RequireStageTelemetry -FailOnStageGateViolation
```

Outputs:
- `<outputDir>\approval\summary.json`
- `<outputDir>\approval\status-summary.json`
- `<outputDir>\approval\bundle-manifest.json`
- `<outputDir>\reject-replan\summary.json` (unless skipped)
- `<outputDir>\reject-replan\status-summary.json` (unless skipped)
- `<outputDir>\reject-replan\bundle-manifest.json` (unless skipped)
- `<outputDir>\suite-summary.json`
- `<outputDir>\bundle-manifest.json`
- `<outputDir>\suite-handoff.json`
- `<outputDir>\suite-handoff.md`
- `<outputDir>\suite-stage-gate.json` (unless `-SkipStageGate`)

`suite-summary.json` now records per-mode `status_summary_path`, and
`files.status_summaries` maps each mode to its compact replay artifact.
`files.cycle_manifests` maps each mode to the cycle-level `bundle-manifest.json`,
and the suite-level `bundle-manifest.json` is the stable replay root for menu /
handoff / stage-gate automation.

### operator-handoff-envelope.ps1
Generate handoff envelope from a cycle summary, suite summary, or bundle manifest.

```powershell
.\scripts\operator-handoff-envelope.ps1 -CycleSummaryPath .\logs\operator-cycles\<stamp>-approval\summary.json
.\scripts\operator-handoff-envelope.ps1 -SuiteSummaryPath .\logs\operator-suites\<stamp>\suite-summary.json
.\scripts\operator-handoff-envelope.ps1 -BundleManifestPath .\logs\operator-suites\<stamp>\bundle-manifest.json
```

### operator-stage-gate.ps1
Evaluate cycle/suite/handoff summaries or bundle manifests with machine-checkable gate policy.

```powershell
.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-summary.json
.\scripts\operator-stage-gate.ps1 -BundleManifestPath .\logs\operator-suites\<stamp>\bundle-manifest.json
.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-summary.json -MaxStageFailures 0 -MaxStageFallbacks 0
.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-summary.json -MaxLlmTransportFallbacks 0
.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-handoff.json -RequireAuditAssertions $true
.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-summary.json -RequireStageTelemetry $true
.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-summary.json -RequirePolicyAssertions $true -PolicyMode strict -EnforceModelAllowlist -FailOnBackendOverrideMismatch
.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-summary.json -RequireAuthEvidence $true -ExpectedAuthRoles "operator,approver" -AuthPolicyMode strict
.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-summary.json -Breakglass -BreakglassReason "temporary remediation" -BreakglassActor "<operator-id>"
```

Gate checks include:
- cycle completion requirement (`final_status == completed`)
- audit assertion requirement (when available in summary)
- optional stage-failure/fallback budget thresholds
- optional LLM transport fallback threshold (`MaxLlmTransportFallbacks`)
- optional strict policy evidence requirement (`RequirePolicyAssertions`)
- optional strict allowlist and backend override mismatch deny checks
- optional strict auth evidence requirement (`RequireAuthEvidence`, `ExpectedAuthRoles`, `AuthPolicyMode`)
- optional breakglass evidence requirement (`Breakglass`, `BreakglassReason`, `BreakglassActor`)
- per-cycle detail + aggregate totals in report JSON

### operator-support-bundle.ps1
Collect replay artifacts and emit pilot support diagnostics in one package.

```powershell
.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\operator-support-bundle.ps1 -BundleManifestPath .\logs\operator-suites\<timestamp>\bundle-manifest.json
```

Outputs:
- `support-bundle.manifest.json`
- `failure-classification.json`
- `failure-classification.md`
- embedded `replay-export\...` artifact mirror

Failure categories:
- `runtime`
- `provider_auth`
- `policy`
- `semantic_output`
- `persistence_restore`
- `operator_flow`

Use this before escalation so support receives one deterministic package with
classification and replay-ready artifacts.

### operator-menu.ps1
Interactive menu for local operator use. Cycle bundle manifests can now be fed
directly into:
- `Check Status`
- `Full Audit`
- `Audit Assert`
- `Stage Report`

Readiness manifests can also be used as the top-level replay root. When a
readiness manifest is supplied, the menu resolves the embedded operator suite
bundle and lets the operator pick the cycle mode (`approval` /
`reject-replan`) before replaying:
- `Check Status`
- `Full Audit`
- `Audit Assert`
- `Stage Report`
- `Handoff Envelope`
- `Stage Gate`
- `Readiness Replay Summary`
- `Handoff Envelope`
- `Stage Gate`

This avoids manual path reconstruction once `operator-full-cycle.ps1` or
`operator-cycle-suite.ps1` has produced a bundle.

### openclaw-evidence-capture.ps1
Run gateway check with evidence JSON + staging record append defaults.

```powershell
.\scripts\openclaw-evidence-capture.ps1
.\scripts\openclaw-evidence-capture.ps1 -EvidenceOutPath .\logs\staging\openclaw-check.json
.\scripts\openclaw-evidence-capture.ps1 -NoResponsesFallback
```

When department internal pipelines run, audit events include:
- `event_type = department_stage_executed`
- `metadata.stage_name`
  - Research: `ScopeFraming`, `EvidenceDraft`, `RiskChallenge`
  - Design: `ArchitectureDraft`, `ConstraintCheck`, `DecisionFinalizer`
  - Build: `Architect`, `Coder`, `Tester`
  - Review: `InitialReview`, `CounterCheck`, `FinalJudgment`
- `metadata.department`, `metadata.sequence`, `metadata.parent_stage_name`
- `metadata.effective_provider`, `metadata.effective_model`
- `metadata.fallback_used`
- `metadata.stage_failure_reason` (present when a stage fell back due to non-JSON/missing-keys/LLM exception)
- `metadata.llm_endpoint`, `metadata.llm_http_status`, `metadata.llm_transport_fallback_used`
- `metadata.llm_response_mode` (for deterministic/mock schema-aware traces)

## SQLite Persistence Setup

Local operation scope: SQLite is intended for single-operator use in local development and day-to-day validation workflows. It is not optimized for high-concurrency or multi-instance deployments. For team-wide or production deployments, use PostgreSQL.

To retain projects across server restarts:

```powershell
# In .env or before starting the server:
$env:STATE_BACKEND = "sqlite"
$env:SQLITE_DB_PATH = "data/codex.db"
$env:STATE_BACKEND_STRICT = "true"

# Start server
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

Projects created with `operator-run.ps1` will survive server restarts.

SQLite recovery helpers:

```powershell
.\scripts\sqlite-verify.ps1
.\scripts\sqlite-backup.ps1 -Label pre-operator-run
.\scripts\sqlite-restore.ps1 -BackupManifestPath .\logs\sqlite-backups\<backup>.manifest.json -Force
.\scripts\sqlite-verify.ps1
.\scripts\sqlite-export.ps1 -Label operator-handoff -Zip
```

Notes:
- default backup root can be configured with `SQLITE_BACKUP_DIR` (default `logs/sqlite-backups`).
- stop the API server before running `sqlite-restore.ps1`.
- `sqlite-restore.ps1` writes a pre-restore safety snapshot unless `-SkipPreRestoreBackup` is used.

### Replay evidence export

Manifest-first replay exports produce a deterministic handoff package for support
or pilot operations.

```powershell
# readiness-root export (preferred)
.\scripts\operator-replay-export.ps1 `
  -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json `
  -Zip

# suite/cycle-root export
.\scripts\operator-replay-export.ps1 `
  -BundleManifestPath .\logs\operator-suites\<timestamp>\bundle-manifest.json `
  -Zip
```

`operator-replay-export.ps1` writes `replay-export.manifest.json` with copied
artifact paths and any missing artifact entries.

## Build/Review internal loop verification (developer check)

The operator flow can be validated independently from department-internal
sub-role loops. To verify the current Build and Review internal pipelines:

```powershell
python -m pytest -q tests/test_roles_pipeline.py tests/test_departments.py
```

What this covers:
- Research pipeline order: `ScopeFraming -> EvidenceDraft -> RiskChallenge`
- Design pipeline order: `ArchitectureDraft -> ConstraintCheck -> DecisionFinalizer`
- Build pipeline order: `Architect -> Coder -> Tester`
- Review pipeline order: `InitialReview -> CounterCheck -> FinalJudgment`
- Progressive context wiring: downstream stages receive prior-stage outputs
- Safe fallback behavior when a stage returns invalid JSON

If this test set fails, resolve it before treating operator workflow results as
evidence of full internal-loop behavior.

## Commercial pilot operator package references (phase_9)

For assisted pilot delivery and support handoff, pair this runbook with:

- `docs/commercial_pilot_delivery_kit.md`
- `docs/commercial_pilot_support_runbook.md`
- `docs/commercial_pilot_scope_and_constraints.md`
- `docs/commercial_pilot_acceptance_checklist.md`
- `docs/commercial_pilot_handoff_checklist.md`
- `docs/commercial_pilot_inquiry_template.md`

## Self-serve packaging references (phase_10)

- `docs/self_serve_distribution_kit_baseline.md`
- `docs/self_serve_onboarding_guardrails.md`
- `docs/self_serve_update_rollback_safety.md`
- `docs/self_serve_support_safe_packaging.md`
- `docs/self_serve_commercial_handoff_readiness.md`
- `docs/self_serve_product_acceptance_checklist.md`

Self-serve operator handoff commands:

```powershell
.\scripts\self-serve-preflight.ps1 -EnvPath .\.env
.\scripts\self-serve-update-guard.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\self-serve-support-intake.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\self-serve-handoff-package.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```

## Post-launch support trend references (phase_12)

- `docs/launch_week_support_trend_review.md`
- `docs/launch_week_runbook_delta_backlog.md`
- `docs/phase12_recurring_issue_hardening.md`

Generate launch-week support trend + runbook delta backlog from support evidence:

```powershell
.\scripts\launch-week-trend-review.ps1 -WindowDays 7
```

Generate recurring issue hardening actions from trend evidence:

```powershell
.\scripts\support-recurring-hardening.ps1
```

## Post-launch feedback operationalization references (phase_13)

- `docs/post_launch_issue_triage.md`
- `docs/post_launch_priority_scoring.md`
- `docs/known_issue_routing.md`
- `docs/post_launch_release_backlog_flow.md`

```powershell
.\scripts\post-launch-triage.ps1
.\scripts\post-launch-priority-score.ps1
.\scripts\known-issue-route.ps1
.\scripts\post-launch-backlog-export.ps1
```

Pilot operator baseline (strict evidence path):

```powershell
.\scripts\ai_work_system\start-server.ps1 -UseOpenClawDefaultProfile -OpenClawBackendModel openai-codex/gpt-5.2
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorAuthorizationOperator "Bearer dev-operator-token" -OperatorRequireStageTelemetry -OperatorMaxLlmTransportFallbacks 0 -OperatorRequirePolicyAssertions -OperatorPolicyMode strict -OperatorEnforceModelAllowlist -OperatorFailOnBackendOverrideMismatch -OperatorRequireAuthEvidence -OperatorExpectedAuthRoles "operator,approver" -OperatorAuthPolicyMode strict -OperatorMaxRevisionReplanAttempts 3
.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```

## Phase 6 real-brief baseline

Use `examples\briefs\phase6_real_brief.json` as the first non-destructive live-operation brief.

- Keep `trend_provider` on a supported approval-gating value such as `gemini-flash-lite-latest`.
- The OpenClaw live path for the internal department loop is controlled by
  `RESEARCH_MODEL`, `DESIGN_MODEL`, `BUILD_MODEL`, and `REVIEW_MODEL`.
- The most reliable startup command for the baseline is:

```powershell
.\scripts\ai_work_system\start-server.ps1 -UseOpenClawDefaultProfile
```

- Recommended baseline command:

```powershell
.\scripts\operator-full-cycle.ps1 `
  -Mode approval `
  -BriefPath .\examples\briefs\phase6_real_brief.json `
  -RunTrendProvider gemini-flash-lite-latest `
  -RequireStageTelemetry `
  -MaxLlmTransportFallbacks 0
```

After completion, use the cycle bundle manifest as the replay root:

```powershell
.\scripts\operator-status.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json
.\scripts\operator-audit.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json
.\scripts\operator-handoff-envelope.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json
.\scripts\operator-stage-gate.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json -RequireStageTelemetry $true -MaxLlmTransportFallbacks 0
```

If the stage report shows:
- `effective_model = openclaw/codex-orchestrator`
- `llm_endpoints = chat/completions`
- `failure_reasons = upstream_rejection:anthropic:credit_balance_too_low`

then the OpenClaw transport path is live, but the upstream model rejected the
semantic request. The run now stops before persisting a deterministic fallback
artifact for that department, leaving the project `in_progress` with the
affected task marked `blocked`. Treat that as an external provider
credit/policy/configuration blocker, not a repository routing failure.
`operator-stage-report.ps1` and `operator-audit.ps1` now also surface
`content_kinds`, `upstream_providers`, and `upstream_rejections` so the
blocker is explicit in replay artifacts.

If a backend override was requested but replay shows
`backend_override_mismatches=<requested-backend>-><actual-upstream-provider>`,
the mismatch is upstream of the local server process. That evidence means the
phase_6 startup profile was applied, but the rejecting provider was not the
requested backend override.

## Authorization Tokens (Dev)

| Token | Role | Can Approve |
|-------|------|-------------|
| `dev-approver-token` | approver | Yes |
| `dev-operator-token` | operator | No |
| `dev-admin-token` | admin | Yes (including production_affecting_change) |
| `dev-owner-token` | owner | No |
| `dev-viewer-token` | viewer | No |

## Fail Handling

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| `Project not found` | Wrong project_id or server restarted with memory backend | Check id, use SQLite backend |
| `Project is not in waiting_approval state` | Already approved or wrong flow | Check status first |
| `Cannot reject non-pending action(s)` | Actions already processed | Check audit for current approval state |
| `401 Unauthorized` | Missing or wrong Authorization header | Use correct token for the action |
| `409 Conflict` | State transition not allowed | Check current status with operator-status.ps1 |

## Phase 14 release-train commands

Use these after phase_13 backlog export to build release candidate and shipment decision evidence:

```powershell
.\scripts\release-candidate-promote.ps1
.\scripts\release-decision-package.ps1
.\scripts\release-notes-assemble.ps1
.\scripts\known-issue-publication-route.ps1
.\scripts\release-train-evidence-export.ps1 -Zip
```

Reference docs:
- `docs/release_candidate_promotion.md`
- `docs/release_go_hold_rollback_decision.md`
- `docs/release_note_publication_flow.md`
- `docs/release_train_evidence_flow.md`

## Phase 15 GA launch execution baseline

Run one GA launch package flow and keep summary + evidence in one bundle:

```powershell
.\scripts\ga-launch-package-execute.ps1 -Zip
.\scripts\early-ops-incident-loop.ps1 -WindowDays 7
.\scripts\hotfix-next-release-route.ps1
.\scripts\phase15-evidence-closeout.ps1 -Zip
```

Reference docs:
- `docs/ga_launch_execution_baseline.md`
- `docs/phase15_early_operations_stabilization.md`
- `docs/phase15_hotfix_next_release_routing.md`
- `docs/phase15_evidence_closure.md`

## Phase 16 GA adoption weekly reliability review

Run the weekly reliability review as one deterministic bundle:

```powershell
.\scripts\ga-weekly-reliability-review.ps1 -WindowDays 7 -Zip
```

Reference doc:
- `docs/phase16_ga_weekly_reliability_review.md`

## Phase 17 monthly reliability governance package

Run the monthly GA reliability target package:

```powershell
.\scripts\ga-monthly-reliability-targets.ps1 -WindowDays 30 -Zip
.\scripts\ga-closure-sla-breach-route.ps1 -Zip
```

Reference doc:
- `docs/phase17_monthly_reliability_governance.md`
- `docs/phase17_closure_sla_routing.md`

## Phase 18 quarterly governance package

Run quarterly governance package generation:

```powershell
.\scripts\ga-quarterly-reliability-governance.ps1 -WindowDays 90 -Zip
.\scripts\ga-quarterly-closure-sla-ownership.ps1 -WindowDays 90 -Zip
.\scripts\ga-quarterly-review-package.ps1 -Zip
```

Reference doc:
- `docs/phase18_quarterly_governance.md`

## Phase 19 upgrade and migration safety package

Run upgrade/migration safety package generation:

```powershell
.\scripts\ga-upgrade-impact-matrix.ps1 -Zip
.\scripts\ga-migration-rehearsal-package.ps1 -Zip
.\scripts\ga-upgrade-rollback-safety.ps1 -Zip
.\scripts\ga-upgrade-evidence-closeout.ps1 -Zip
```

Reference doc:
- `docs/phase19_upgrade_migration_safety.md`

## Phase 20 environment compatibility/support baseline

```powershell
.\scripts\ga-supported-environment-matrix.ps1 -Zip
.\scripts\ga-compatibility-preflight.ps1 -Zip
.\scripts\ga-support-intake-normalization.ps1 -Zip
.\scripts\ga-environment-support-closeout.ps1 -Zip
```

Reference doc:
- `docs/phase20_environment_compatibility_support.md`

## Phase 21 auditability/retention governance package

```powershell
.\scripts\ga-artifact-retention-coverage.ps1 -Zip
.\scripts\ga-audit-traceability-index.ps1 -Zip
.\scripts\ga-incident-change-ledger.ps1 -Zip
.\scripts\ga-auditability-closeout.ps1 -Zip
```

Reference doc:
- `docs/phase21_auditability_retention_governance.md`

## Phase 22 steady-state closure package

```powershell
.\scripts\ga-steady-state-operations-handbook.ps1 -Zip
.\scripts\ga-release-ops-cadence-baseline.ps1 -Zip
.\scripts\ga-end-to-end-operations-evidence.ps1 -Zip
.\scripts\ga-steady-state-closeout.ps1 -Zip
```

Reference docs:
- `docs/steady_state_operations_handbook.md`
- `docs/release_ops_cadence_baseline.md`
- `docs/phase22_steady_state_operations_closure.md`

## Steady-state bounded improvement backlog

```powershell
.\scripts\ga-steady-state-improvement-backlog.ps1 -Zip
```

Reference doc:
- `docs/steady_state_improvement_backlog.md`

## Steady-state watch backlog burn-down

```powershell
.\scripts\ga-steady-state-burndown.ps1 -Zip
```

Reference doc:
- `docs/steady_state_burndown_tracking.md`

## Steady-state checkpoint refresh

```powershell
.\scripts\ga-steady-state-checkpoint-refresh.ps1 -Zip
```

Reference doc:
- `docs/steady_state_checkpoint_refresh.md`

## Steady-state watchlist ownership routing

```powershell
.\scripts\ga-steady-state-escalation-watchlist-route.ps1 -OwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

Reference doc:
- `docs/steady_state_watchlist_ownership_routing.md`
- `docs/steady_state_watchlist_owner_ack.json`

## Steady-state single-entry runtime loop

```powershell
.\scripts\steady-state-run.ps1 -Mode daily -WatchlistOwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

Weekly heavier cycle:

```powershell
.\scripts\steady-state-run.ps1 -Mode weekly -WatchlistOwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

Reference docs:
- `docs/steady_state_runtime_loop.md`
- `docs/steady_state_runtime_state.json`
