# AI Work System + MacroPulser Platform

This repository packages two production-oriented runtimes:

- `AI Work System` for intake/orchestration/approval/policy/audit workflows.
- `MacroPulser` for Kalshi macroeconomic release monitoring and signal operations.

Both runtimes share governance, operational scripts, and evidence-first runbook workflows.

## Product Overview

Supported release types in v1:
- FOMC rate decision
- CPI
- NFP (Employment Situation headline nonfarm payrolls)
- GDP advance estimate

Signal families:
- `PRE_RELEASE_PRESSURE`
- `RELEASE_SHOCK`
- `DELAYED_REPRICING`

This system is not a trading bot. It does not place orders or recommend trades.

## Architecture Summary

- `app/adapters`: external integrations (Kalshi, BLS, BEA, Fed, Telegram)
- `app/services`: ingestion, polling, parsing, signal detection, scoring, notification, replay/backfill/evaluation
- `app/services/monitoring_service.py`: operational anomaly detection, monitor event persistence, and critical monitor alerts
- `app/db`: SQLAlchemy async models/repositories and Alembic migrations
- `app/api`: minimal management and read endpoints
- `app/domain`: enums and typed models
- `config/market_mapping.yaml`: deterministic market mapping rules

## Product Split Entry Points

This repository currently contains two runtime entrypoint families under separate folders:

- MacroPulser runtime: `app/macro_pulser/main.py`
  - Backward compatible shim remains at `app/main.py`.
- AI Work System runtime: `app/ai_work_system/main.py`
  - Orchestrator API runtime remains at `app/api/main.py`.

Recommended direct startup commands:

```bash
python -m app.macro_pulser.main api
python -m app.ai_work_system.main --host 0.0.0.0 --port 8001
```

Runtime and persistence boundary is defined in:
- `docs/runtime_storage_boundary.md`

Separated script entry roots (non-breaking wrappers):

- MacroPulser:
  - `scripts/macro_pulser/run-api.ps1`
  - `scripts/macro_pulser/run-live.ps1`
  - `scripts/macro_pulser/run-backfill.ps1`
  - `scripts/macro_pulser/run-replay.ps1`
  - `scripts/macro_pulser/local-dev-smoke.ps1`
- AI Work System:
  - `scripts/ai_work_system/start-server.ps1`
  - `scripts/ai_work_system/release-readiness.ps1`
  - `scripts/ai_work_system/operator-menu.ps1`

Legacy root scripts remain available for backward compatibility.

Packaging note:
- `pyproject.toml` metadata is aligned to umbrella platform packaging (`ai-work-system-platform`).
- Runtime entrypoints remain split under `app/macro_pulser` and `app/ai_work_system` as documented above.

## Continuation Governance Artifacts

- `docs/current_brief_template.json`
- `docs/current_work_order_template.json`

Continuation decisions use `GO`, `PAUSE`, `REVIEW`.

Additional governance/runbook references:
- `docs/codex_continuation_runbook.md`
- `docs/codex_automation_prompts.md`
- `docs/model_governance_policy.md`
- `docs/model_routing_policy.json`
- `docs/operator_workflow_runbook.md`
- `docs/staging_validation_plan.md`
- `docs/staging_execution_record.md`
- `docs/staging_evidence_template.md`
- `docs/staging_issue_triage_template.md`
- `docs/staging_signoff_template.md`
- `docs/live_validation_checklist.md`
- `docs/rollout_plan.md`
- `docs/rollback_checklist.md`
- `docs/production_readiness_gaps.md`
- `docs/system_requirements.md`
- `docs/mvp_requirements.md`
- `docs/pre_production_requirements.md`
- `docs/non_goals.md`
- `docs/requirement_traceability_matrix.md`
- `docs/acceptance_criteria.md`
- `docs/commercial_pilot_delivery_kit.md`
- `docs/commercial_pilot_support_runbook.md`
- `docs/commercial_pilot_scope_and_constraints.md`
- `docs/commercial_pilot_acceptance_checklist.md`
- `docs/commercial_pilot_handoff_checklist.md`
- `docs/commercial_pilot_inquiry_template.md`
- `docs/self_serve_distribution_kit_baseline.md`
- `docs/self_serve_onboarding_guardrails.md`
- `docs/self_serve_update_rollback_safety.md`
- `docs/self_serve_support_safe_packaging.md`
- `docs/self_serve_commercial_handoff_readiness.md`
- `docs/self_serve_product_acceptance_checklist.md`
- `docs/release_governance_baseline.md`
- `docs/release_notes_template.md`
- `docs/release_notes_phase11_example.md`
- `docs/known_issues_register.md`
- `docs/commercial_launch_support_boundary.md`
- `docs/commercial_launch_sla_lite.md`
- `docs/commercial_launch_go_no_go_checklist.md`
- `docs/launch_week_support_trend_review.md`
- `docs/launch_week_runbook_delta_backlog.md`
- `docs/ga_launch_execution_baseline.md`
- `docs/phase15_early_operations_stabilization.md`
- `docs/phase15_hotfix_next_release_routing.md`
- `docs/phase15_evidence_closure.md`
- `docs/runtime_storage_boundary.md`

Readiness/operator script references (contract compatibility):
- `scripts\refresh-openapi.ps1`
- `scripts\openclaw-gateway-check.ps1`
- `openclaw-evidence-capture.ps1`
- `operator-stage-report.ps1`
- `operator-audit-assert.ps1`
- `operator-full-cycle.ps1`
- `operator-cycle-suite.ps1`
- `operator-handoff-envelope.ps1`
- `operator-stage-gate.ps1`
- `operator-replay-export.ps1`
- `operator-support-bundle.ps1`
- `scripts\early-ops-incident-loop.ps1`
- `scripts\hotfix-next-release-route.ps1`
- `scripts\phase15-evidence-closeout.ps1`
- `scripts\launch-week-trend-review.ps1`
- `operator-menu.ps1`
- `operator-status.ps1 -BundleManifestPath`
- `operator-stage-report.ps1 -BundleManifestPath`
- `operator-audit-assert.ps1 -BundleManifestPath`
- `Readiness Replay Summary`
- `legacy_fallback_normalizations`
- `status-summary.json`
- `bundle-manifest.json`
- `readiness-manifest-`
- `readiness-summary-`
- `sqlite-export.ps1`

Common readiness/operator flags:
- `-AuditJsonPath`
- `-NoEventDerivedTelemetry`
- `-SummaryOutPath`
- `-BundleManifestPath`
- `-RunOpenClawGatewayCheck`
- `-OperatorMaxLlmTransportFallbacks`
- `-OperatorMaxRevisionReplanAttempts`
- `-OperatorRequireAuthEvidence`
- `-OperatorAuthorizationOperator`
- `-OperatorExpectedAuthRoles`
- `-OperatorAuthPolicyMode`
- `-OperatorBreakglass`
- `-OperatorBreakglassReason`
- `-OperatorBreakglassActor`

## Setup

1. Create Python 3.12 environment.
2. Install dependencies:

```bash
pip install -e ".[dev]"
```

3. Copy env file and fill values:

```bash
cp .env.example .env
```

4. Ensure PostgreSQL is running and `DATABASE_URL` is valid.
   - `monitor --once` and `live --once` require reachable PostgreSQL.

## Environment Variables

Required/primary:
- `APP_ENV`
- `LOG_LEVEL`
- `DATABASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `API_WRITE_TOKEN`
- `KALSHI_BASE_URL`
- `BLS_BASE_URL`
- `BEA_BASE_URL`
- `FED_BASE_URL`
- `DISPLAY_TIMEZONE` (default `Asia/Tokyo`)
- `POLL_INTERVAL_SECONDS`
- `ACTIVE_RELEASE_WINDOW_MINUTES`

Retry/network:
- `REQUEST_TIMEOUT_SECONDS`
- `MAX_RETRIES`
- `BACKOFF_BASE_SECONDS`

Monitoring:
- `MONITORING_ENABLED`
- `MONITORING_INTERVAL_SECONDS`
- `MONITORING_TELEGRAM_CHAT_ID` (optional; falls back to `TELEGRAM_CHAT_ID`)
- `MONITORING_ALERT_COOLDOWN_CRITICAL_SECONDS`
- `MONITORING_ACTUAL_MISSING_GRACE_SECONDS`
- `MONITORING_NO_SIGNAL_GRACE_SECONDS`
- `MONITORING_SIGNAL_BURST_THRESHOLD`
- `MONITORING_SIGNAL_BURST_MARKET_THRESHOLD`
- `MONITORING_NOTIFICATION_FAILURE_BURST_THRESHOLD`

Operator/local profile:
- `STATE_BACKEND`
- `STATE_BACKEND_STRICT`
- `SQLITE_DB_PATH`
- `OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS`
- `OPERATOR_API_TIMEOUT_SECONDS`
- `INTAKE_USE_LLM` (`0/1`; default `0`)
- `INTAKE_MODEL` (optional override; defaults to `RESEARCH_MODEL` when enabled)
- `AUTH_SERVICE_MODE` (`dev_token` or `commercial_token`)
- `AUTH_ENABLED` (used when `AUTH_SERVICE_MODE=commercial_token`)
- `AUTH_TOKEN_SEED` (used when `AUTH_SERVICE_MODE=commercial_token`)
- `AUTH_TOKEN_STORE_PATH` (used when `AUTH_SERVICE_MODE=commercial_token`; defaults to `logs/auth/commercial-token-store.json`)
- `DEV_AUTH_ENABLED` (used when `AUTH_SERVICE_MODE=dev_token`)
- `DEV_AUTH_TOKEN_SEED` (used when `AUTH_SERVICE_MODE=dev_token`)
- `RUN_LIVE_LLM_CONTRACT` (`0/1`; opt-in live contract test)
- `OPENCLAW_AGENT_ID` (default `codex-orchestrator`)
- `OPENCLAW_BACKEND_MODEL` (optional backend override for gateway routing)
- `OPENCLAW_LIVE_CONTRACT_TIMEOUT_SECONDS`
- `OPENCLAW_LIVE_CONTRACT_MAX_RETRIES`
- `OPENCLAW_LIVE_CONTRACT_RETRY_BACKOFF_SECONDS`

Intake extraction profile:
- Default remains regex-first intake (`INTAKE_USE_LLM=0`) for deterministic local runs.
- Enable `INTAKE_USE_LLM=1` only when LLM-assisted completion of missing brief fields is required.
- `INTAKE_MODEL` is optional; when unset and LLM mode is enabled, intake falls back to `RESEARCH_MODEL`.

Live LLM structured-output contract (opt-in):

```powershell
$env:RUN_LIVE_LLM_CONTRACT = "1"
$env:OPENCLAW_BASE_URL = "http://127.0.0.1:18789"
$env:OPENCLAW_AGENT_ID = "codex-orchestrator"
$env:OPENCLAW_GATEWAY_TOKEN = "<gateway-token>"
python -m pytest -q tests/test_live_llm_contract_optin.py
```

Keep this test opt-in for runtime verification and support evidence capture, not as mandatory default CI.
If this test returns `401 Unauthorized`, refresh `OPENCLAW_GATEWAY_TOKEN` (or login/configure OpenClaw gateway auth) before retrying.

Commercial auth profile (least-privilege seed example):

```powershell
$env:AUTH_SERVICE_MODE = "commercial_token"
$env:AUTH_ENABLED = "true"
$env:AUTH_TOKEN_SEED = "commercial-operator:ops-1:operator:human,commercial-approver:apr-1:approver:human"

.\scripts\ai_work_system\release-readiness.ps1 `
  -AutoSeedFullFlow `
  -Authorization "Bearer commercial-approver" `
  -RunOperatorSuite `
  -OperatorAuthorizationOperator "Bearer commercial-operator" `
  -OperatorRequireAuthEvidence `
  -OperatorExpectedAuthRoles "operator,approver" `
  -OperatorAuthPolicyMode strict `
  -OperatorRequirePolicyAssertions `
  -OperatorPolicyMode strict `
  -OperatorEnforceModelAllowlist `
  -OperatorFailOnBackendOverrideMismatch
```

In this mode, `AUTH_TOKEN_SEED` is authoritative for protected route authentication.
Commercial token lifecycle state is persisted at `AUTH_TOKEN_STORE_PATH`.

Commercial token lifecycle admin API (requires admin bearer token):

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8001/auth/tokens" -Headers @{ Authorization = "Bearer <admin-token>" }
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/auth/tokens/issue" -Headers @{ Authorization = "Bearer <admin-token>" } -ContentType "application/json" -Body '{"actor_id":"apr-2","actor_role":"approver","actor_type":"human","description":"ops approver"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/auth/tokens/revoke" -Headers @{ Authorization = "Bearer <admin-token>" } -ContentType "application/json" -Body '{"token":"<issued-token>"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/auth/tokens/rotate" -Headers @{ Authorization = "Bearer <admin-token>" } -ContentType "application/json" -Body '{"token":"<issued-token>"}'
```

These endpoints are available only in `AUTH_SERVICE_MODE=commercial_token`.

Copy/paste env sample for this profile:

```powershell
Get-Content .\examples\env\commercial_auth_minimal.env | ForEach-Object {
  if ($_ -and -not $_.StartsWith("#")) {
    $name, $value = $_ -split "=", 2
    Set-Item -Path ("Env:{0}" -f $name) -Value $value
  }
}
```

## Database Migration

```bash
alembic upgrade head
```

Or:

```bash
./scripts/init_db.sh
```

## Run Modes

Live:

```bash
python -m app.macro_pulser.main live
```

Live once without remote schedule ingestion (local/dev fallback):

```bash
python -m app.macro_pulser.main live --once --skip-remote-schedules
```

Backfill:

```bash
python -m app.macro_pulser.main backfill --from 2026-01-01T00:00:00Z --to 2026-03-01T00:00:00Z
```

Replay:

```bash
python -m app.macro_pulser.main replay --release-id CPI-2026-04-10
```

API:

```powershell
.\scripts\macro_pulser\run-api.ps1
```

Monitoring (single tick):

```bash
python -m app.macro_pulser.main monitor --once
```

Monitoring (loop):

```bash
python -m app.macro_pulser.main monitor --loop
```

`monitor --once` is for deterministic local checks and CI smoke, while `monitor --loop` is for long-running watch mode.

Manual release seeding (YAML):

```bash
python -m app.macro_pulser.main seed-releases --file config/manual_releases.yaml
```

Manual actual seeding (YAML):

```bash
python -m app.macro_pulser.main seed-actuals --file config/manual_actuals.yaml
```

Manual market seeding (YAML):

```bash
python -m app.macro_pulser.main seed-markets --file config/manual_markets.yaml
```

Manual snapshot seeding (YAML):

```bash
python -m app.macro_pulser.main seed-snapshots --file config/manual_snapshots.yaml
```

Local BLS-free smoke (single command):

```powershell
.\scripts\macro_pulser\local-dev-smoke.ps1
```

Optional read-only API surface check (requires running API server):

```powershell
.\scripts\macro_pulser\run-api.ps1
.\scripts\macro_pulser\local-dev-smoke.ps1 -CheckReadOnlyApi -ApiBaseUrl http://127.0.0.1:8000
```

Legacy compatibility aliases (still supported):
- `python -m app.main api`
- `.\scripts\local-dev-smoke.ps1`

This runs:
1. `seed-releases`
2. `seed-actuals`
3. `seed-markets`
4. `seed-snapshots`
5. `live --once --skip-remote-schedules`
6. `monitor --once`

Seed file format (`config/manual_releases.yaml`):

```yaml
releases:
  - release_type: CPI
    release_name: Consumer Price Index
    scheduled_time_utc: "2026-06-11T12:30:00Z"
    source_url: "manual://cpi-2026-06-11"
    status: scheduled
```

Actual seed file format (`config/manual_actuals.yaml`):

```yaml
actuals:
  - release_type: CPI
    release_name: Consumer Price Index
    scheduled_time_utc: "2026-06-11T12:30:00Z"
    actual_value_num: 3.3
    actual_value_text: "Headline CPI YoY 3.3%"
    source_url: "manual://actual/cpi-dev-seed"
    released_at_utc: "2026-06-11T12:30:00Z"
    status: released
```

Market seed file format (`config/manual_markets.yaml`):

```yaml
markets:
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    platform: kalshi
    title: "Will CPI Dev Seed Near Term print above 3.1%?"
    close_time_utc: "2026-04-19T13:00:00Z"
    status: active
    release_type: CPI
    release_name: CPI Dev Seed Near Term
    scheduled_time_utc: "2026-04-19T12:30:00Z"
    mapping_confidence: 1.0
    mapping_payload_json:
      manual_seed: true
      threshold:
        comparator: above
        value: 3.1
        unit: "%"
```

Snapshot seed file format (`config/manual_snapshots.yaml`):

```yaml
snapshots:
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    captured_at_utc: "2026-04-19T12:20:00Z"
    yes_bid: 0.44
    yes_ask: 0.48
    volume: 130
```

Operational note:
- If runtime dependencies are unavailable (for example DB down or upstream HTTP errors), commands fail once with a clear error log and attempt graceful async cleanup.
- Manual release seeding and `--skip-remote-schedules` are intended for local development/internal validation when upstream schedule pages are temporarily unavailable.
- Manual actual seeding is intended for local development/internal validation when upstream actual-value ingestion is unavailable.
- Manual market seeding is intended for local development/internal validation when upstream discovery/mapping is insufficient.
- Manual snapshot seeding is intended for local development/internal validation when upstream polling data is unavailable or insufficient.
- For local/internal compatibility, manual market mappings can include `release_id`, `threshold`, and `contract_interpretation` in `mapping_payload_json`; non-manual production mapping behavior is unchanged.
- Manual markets with `mapping_payload_json.manual_seed=true` are treated as synthetic in local dev mode: upstream Kalshi detail/orderbook polling is skipped and seeded local snapshots are used as the source of truth.

## SQLite operational policy (local ops)

- Local readiness profile uses `STATE_BACKEND=sqlite` and `STATE_BACKEND_STRICT=true`.
- SQLite local operation is intentionally persistence-focused and is **not treated as a production-grade** concurrency validation profile.
- Keep `OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS` and `OPERATOR_API_TIMEOUT_SECONDS` explicitly configured for stable local operator runs.
- For recovery operations, keep `SQLITE_BACKUP_DIR` configured (default: `logs/sqlite-backups`).

SQLite recovery quick commands:

```powershell
.\scripts\sqlite-verify.ps1
.\scripts\sqlite-backup.ps1 -Label pre-change
.\scripts\sqlite-restore.ps1 -BackupManifestPath .\logs\sqlite-backups\<backup>.manifest.json -Force
.\scripts\sqlite-export.ps1 -Label handoff -Zip
```

Recommended recovery check after restore:

```powershell
.\scripts\sqlite-verify.ps1
.\scripts\operator-run.ps1 -BriefPath .\examples\briefs\sample_brief.json -TrendProvider gemini-flash-lite-latest
.\scripts\operator-status.ps1 -ProjectId <project_id>
```

Replay evidence export (cycle/suite/readiness manifests):

```powershell
.\scripts\operator-replay-export.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\operator-replay-export.ps1 -BundleManifestPath .\logs\operator-suites\<timestamp>\bundle-manifest.json
.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```

Support-bundle failure categories (`failure-classification.json` / `.md`):
- `runtime`
- `provider_auth`
- `policy`
- `semantic_output`
- `persistence_restore`
- `operator_flow`

## Commercial pilot package (phase_9)

Use these documents as the customer-facing pilot delivery kit:

- `docs/commercial_pilot_delivery_kit.md`
- `docs/commercial_pilot_support_runbook.md`
- `docs/commercial_pilot_scope_and_constraints.md`
- `docs/commercial_pilot_acceptance_checklist.md`
- `docs/commercial_pilot_handoff_checklist.md`
- `docs/commercial_pilot_inquiry_template.md`

Operator-first package flow:

```powershell
.\scripts\ai_work_system\start-server.ps1 -UseOpenClawDefaultProfile -OpenClawBackendModel openai-codex/gpt-5.2
.\scripts\openclaw-gateway-check.ps1 -AgentId codex-orchestrator -BackendModel openai-codex/gpt-5.2
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorAuthorizationOperator "Bearer dev-operator-token" -OperatorRequireStageTelemetry -OperatorMaxLlmTransportFallbacks 0 -OperatorRequirePolicyAssertions -OperatorPolicyMode strict -OperatorEnforceModelAllowlist -OperatorFailOnBackendOverrideMismatch -OperatorRequireAuthEvidence -OperatorExpectedAuthRoles "operator,approver" -OperatorAuthPolicyMode strict -OperatorMaxRevisionReplanAttempts 3
.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```

## Self-serve productization baseline (phase_10)

Self-serve packaging references:

- `docs/self_serve_distribution_kit_baseline.md`
- `docs/self_serve_onboarding_guardrails.md`
- `docs/self_serve_update_rollback_safety.md`

These documents define initial setup guardrails, distribution baseline, and update/rollback data-safety requirements without relaxing strict policy controls.

Self-serve preflight command:

```powershell
.\scripts\self-serve-preflight.ps1 -EnvPath .\.env
```

Self-serve update/support/handoff commands:

```powershell
.\scripts\self-serve-update-guard.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\self-serve-support-intake.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\self-serve-handoff-package.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```

## Commercial launch governance baseline (phase_11 closeout)

Launch-governance references:

- `docs/release_governance_baseline.md`
- `docs/release_notes_template.md`
- `docs/release_notes_phase11_example.md`
- `docs/known_issues_register.md`
- `docs/commercial_launch_support_boundary.md`
- `docs/commercial_launch_sla_lite.md`
- `docs/commercial_launch_go_no_go_checklist.md`

Representative evidence packaging commands:

```powershell
.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json
.\scripts\self-serve-support-intake.ps1 -SupportBundleManifestPath .\logs\self-serve\phase11-launch-evidence-<timestamp>\support-bundle.manifest.json
.\scripts\self-serve-handoff-package.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -SupportIntakeManifestPath .\logs\self-serve\phase11-launch-evidence-<timestamp>\support-intake.manifest.json
```

## Post-launch support trend loop (phase_12)

Post-launch operations use launch-week evidence review to keep runbooks aligned with recurring support patterns:

- `docs/launch_week_support_trend_review.md`
- `docs/launch_week_runbook_delta_backlog.md`
- `docs/phase12_recurring_issue_hardening.md`

Generate/update trend + backlog from recent support bundles:

```powershell
.\scripts\launch-week-trend-review.ps1 -WindowDays 7
```

Generate recurring issue hardening actions from the latest trend manifest:

```powershell
.\scripts\support-recurring-hardening.ps1
```

## Post-launch feedback operationalization (phase_13)

Convert support evidence into triage, scoring, known-issue routing, and release-backlog outputs:

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

## Release-train automation and GA-readiness (phase_14)

Transform post-launch backlog artifacts into release candidate, go/hold/rollback decision, notes/publication routing, and evidence package outputs:

- `docs/release_candidate_promotion.md`
- `docs/release_go_hold_rollback_decision.md`
- `docs/release_note_publication_flow.md`
- `docs/release_train_evidence_flow.md`

```powershell
.\scripts\release-candidate-promote.ps1
.\scripts\release-decision-package.ps1
.\scripts\release-notes-assemble.ps1
.\scripts\known-issue-publication-route.ps1
.\scripts\release-train-evidence-export.ps1 -Zip
```

## GA launch execution and early-operations stabilization (phase_15)

Phase_15 starts by executing one GA launch package end-to-end from the current release-train inputs:

- `docs/ga_launch_execution_baseline.md`
- `docs/phase15_early_operations_stabilization.md`
- `docs/phase15_hotfix_next_release_routing.md`
- `docs/phase15_evidence_closure.md`

```powershell
.\scripts\ga-launch-package-execute.ps1 -Zip
.\scripts\early-ops-incident-loop.ps1 -WindowDays 7
.\scripts\hotfix-next-release-route.ps1
.\scripts\phase15-evidence-closeout.ps1 -Zip
```

## GA adoption reliability and self-serve stabilization (phase_16)

Phase_16 starts with a deterministic weekly reliability review loop over support evidence:

- `docs/phase16_ga_weekly_reliability_review.md`

```powershell
.\scripts\ga-weekly-reliability-review.ps1 -WindowDays 7 -Zip
```

Primary outputs:
- `logs\ga-adoption\weekly-review-<timestamp>\ga-weekly-reliability-review.manifest.json`
- `logs\ga-adoption\weekly-review-<timestamp>\ga-weekly-reliability-review.summary.json`

## GA steady-state scaling and customer-success governance (phase_17)

Aggregate weekly reliability evidence into a deterministic monthly KPI/closure-SLA package:

- `docs/phase17_monthly_reliability_governance.md`
- `docs/phase17_closure_sla_routing.md`

```powershell
.\scripts\ga-monthly-reliability-targets.ps1 -WindowDays 30 -Zip
.\scripts\ga-closure-sla-breach-route.ps1 -Zip
```

Outputs:

- `logs\ga-adoption\monthly-targets-<timestamp>\ga-monthly-reliability-targets.manifest.json`
- `logs\ga-adoption\monthly-targets-<timestamp>\ga-monthly-reliability-targets.summary.json`
- `logs\ga-adoption\closure-sla-routing-<timestamp>\ga-closure-sla-routing.manifest.json`
- `logs\ga-adoption\closure-sla-routing-<timestamp>\ga-closure-sla-routing.summary.json`

## Quarterly GA governance and scale planning (phase_18)

Generate quarterly governance package outputs from monthly reliability and closure-SLA routing evidence:

- `docs/phase18_quarterly_governance.md`

```powershell
.\scripts\ga-quarterly-reliability-governance.ps1 -WindowDays 90 -Zip
.\scripts\ga-quarterly-closure-sla-ownership.ps1 -WindowDays 90 -Zip
.\scripts\ga-quarterly-review-package.ps1 -Zip
```

Outputs:

- `logs\ga-adoption\quarterly-reliability-<timestamp>\ga-quarterly-reliability-governance.manifest.json`
- `logs\ga-adoption\quarterly-closure-ownership-<timestamp>\ga-quarterly-closure-sla-ownership.manifest.json`
- `logs\ga-adoption\quarterly-review-package-<timestamp>\ga-quarterly-review-package.manifest.json`

## Upgrade and migration safety operations (phase_19)

Convert quarterly governance outputs into deterministic upgrade impact, migration rehearsal, rollback safety, and closeout evidence packages:

- `docs/phase19_upgrade_migration_safety.md`

```powershell
.\scripts\ga-upgrade-impact-matrix.ps1 -Zip
.\scripts\ga-migration-rehearsal-package.ps1 -Zip
.\scripts\ga-upgrade-rollback-safety.ps1 -Zip
.\scripts\ga-upgrade-evidence-closeout.ps1 -Zip
```

Outputs:

- `logs\ga-upgrade\impact-matrix-<timestamp>\ga-upgrade-impact-matrix.manifest.json`
- `logs\ga-upgrade\migration-rehearsal-<timestamp>\ga-migration-rehearsal-package.manifest.json`
- `logs\ga-upgrade\rollback-safety-<timestamp>\ga-upgrade-rollback-safety.manifest.json`
- `logs\ga-upgrade\phase19-closeout-<timestamp>\phase19-upgrade-evidence-closeout.manifest.json`

## Environment compatibility and support-at-scale baseline (phase_20)

Generate compatibility matrix, preflight report, support-intake normalization, and closeout package:

```powershell
.\scripts\ga-supported-environment-matrix.ps1 -Zip
.\scripts\ga-compatibility-preflight.ps1 -Zip
.\scripts\ga-support-intake-normalization.ps1 -Zip
.\scripts\ga-environment-support-closeout.ps1 -Zip
```

Reference doc:
- `docs/phase20_environment_compatibility_support.md`

## Auditability, retention, and compliance-lite governance (phase_21)

Generate retention coverage, traceability index, incident/change ledger, and closeout package:

```powershell
.\scripts\ga-artifact-retention-coverage.ps1 -Zip
.\scripts\ga-audit-traceability-index.ps1 -Zip
.\scripts\ga-incident-change-ledger.ps1 -Zip
.\scripts\ga-auditability-closeout.ps1 -Zip
```

Reference doc:
- `docs/phase21_auditability_retention_governance.md`

## Steady-state commercial operations closure (phase_22)

Generate handbook package, cadence baseline, end-to-end evidence, and steady-state closeout:

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

Generate a deterministic remediation backlog from phase_20/21/22 closeout outcomes:

```powershell
.\scripts\ga-steady-state-improvement-backlog.ps1 -Zip
```

Reference doc:
- `docs/steady_state_improvement_backlog.md`

## Steady-state watch backlog burn-down

Track open steady-state backlog trend and closure pressure:

```powershell
.\scripts\ga-steady-state-burndown.ps1 -Zip
```

Reference doc:
- `docs/steady_state_burndown_tracking.md`

## Steady-state checkpoint refresh

Refresh monthly, quarterly, and release checkpoint evidence into a single steady-state package:

```powershell
.\scripts\ga-steady-state-checkpoint-refresh.ps1 -Zip
```

Reference doc:
- `docs/steady_state_checkpoint_refresh.md`

## Steady-state watchlist ownership routing

Route steady-state checkpoint `watch` / `escalate` items to deterministic owner tracking:

```powershell
.\scripts\ga-steady-state-escalation-watchlist-route.ps1 -Zip
```

Owner acknowledgment rule example:

```powershell
.\scripts\ga-steady-state-escalation-watchlist-route.ps1 -OwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

Reference doc:
- `docs/steady_state_watchlist_ownership_routing.md`
- `docs/steady_state_watchlist_owner_ack.json`

## Steady-state single-entry runtime loop

Run the full steady-state operational loop from one entrypoint:

```powershell
.\scripts\steady-state-run.ps1 -Mode daily -WatchlistOwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

Daily run with OpenClaw gateway evidence capture (timeout bounded):

```powershell
.\scripts\steady-state-run.ps1 `
  -Mode daily `
  -WatchlistOwnerAckPath .\docs\steady_state_watchlist_owner_ack.json `
  -RunOpenClawGatewayCheck `
  -OpenClawAgentId codex-orchestrator `
  -OpenClawTimeoutSec 30 `
  -OpenClawProbeTimeoutSec 15 `
  -Zip
```

Weekly heavier cycle:

```powershell
.\scripts\steady-state-run.ps1 -Mode weekly -WatchlistOwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

Runtime loop references:
- `docs/steady_state_runtime_loop.md`
- `docs/steady_state_runtime_state.json`

## API Endpoints

- `GET /health`
- `GET /status`
- `GET /monitor`
- `GET /signals`
- `GET /releases/upcoming`
- `GET /signals/recent`
- `GET /monitoring/status`
- `GET /monitoring/events/recent`
- `GET /monitoring/events/open`
- `POST /jobs/backfill` (requires `Authorization: Bearer <API_WRITE_TOKEN>`)
- `POST /jobs/replay` (requires `Authorization: Bearer <API_WRITE_TOKEN>`)

Read-only observability surfaces (internal beta contract):
- `GET /status`:
  - `latest_live_cycle_success_at_utc`
  - `release_calendar_count`, `release_actuals_count`, `market_catalog_count`, `market_snapshots_count`, `signals_count`
  - `open_monitor_events_count`, `resolved_monitor_events_count`
  - `monitoring_status`
- `GET /monitor`:
  - `monitor_type`, `status`, `severity`, `dedupe_key`, `updated_at_utc`, `resolved_at_utc`
  - default limit: 20
- `GET /signals`:
  - `signal_id`, `release_id`, `market_ticker`, `signal_type`, `score`, `severity`, `emitted_at_utc`
  - supports `limit` (default 20) and optional `severity`

## MVP Completion Criteria

### 1. Local MVP Pass

The local MVP gate is satisfied when all of the following pass:
- release seeding succeeds (`seed-releases`)
- actual seeding succeeds (`seed-actuals`)
- market seeding succeeds (`seed-markets`)
- snapshot seeding succeeds (`seed-snapshots`)
- `live --once --skip-remote-schedules` succeeds
- at least one signal is persisted in `signals`
- `monitor --once` reflects expected open/resolved transitions for active scenarios
- Telegram signal notifications succeed for high/critical signals
- readiness/docs/env contract tests pass

Manual seed roles in local BLS-free mode:
- releases: scheduled events to monitor
- actuals: official-value stand-in for actual-dependent logic
- markets: explicit release-linked market catalog rows
- snapshots: time-series price points required by signal windows

### 2. Internal Beta Pass

Internal beta readiness expects:
- repeatable runs via `.\scripts\macro_pulser\local-dev-smoke.ps1`
- deterministic smoke summary visibility (counts, latest signals, open/resolved monitor events)
- read-only observability checks in fixed order: `/status` -> `/monitor` -> `/signals`
- documented operator workflow and readiness runbook coverage
- Telegram notification paths validated in an internal non-production chat

Internal beta execution interpretation:
- `PASS`: smoke returns `LOCAL DEV SMOKE: PASS` and read-only checks are reachable with current scenario data.
- `REVIEW`: smoke returns `LOCAL DEV SMOKE: REVIEW` or open monitor criticals need triage.
- `STOP`: smoke command fails or required read-only surfaces are unreachable.

Local dev mode and internal beta are different gates:
- local dev mode validates deterministic seeded behavior (`seed-*`, `live --once --skip-remote-schedules`, `monitor --once`)
- internal beta validates repeatability and observability on top of local dev mode (smoke summary + `/status` + `/monitor` + `/signals`)

### 3. Production Readiness Remaining Gaps

Remaining gaps before production rollout include:
- full real-upstream schedule/actual resiliency validation (beyond local BLS-free mode)
- production secret handling and token rotation execution plan
- production database/availability validation beyond local SQLite/Postgres dev profiles
- deployment/monitoring SLO hardening and incident runbook finalization

## Telegram Operations

- Pulse is the MacroPulse Telegram notification interface for signal and monitoring events.
- Signal notifications and monitoring alerts share the existing notifier path, but monitoring can target `MONITORING_TELEGRAM_CHAT_ID` (falls back to `TELEGRAM_CHAT_ID`).
- In local runs, use `monitor --once` to validate alert/event transitions after each deterministic cycle.
- For watch mode, use `monitor --loop` and keep critical cooldown behavior enabled.
- Read-only observability surfaces are available via API endpoints: `/status`, `/monitor`, `/signals`.
- Internal beta quick path: run `.\scripts\macro_pulser\local-dev-smoke.ps1`, then verify `/status`, `/monitor`, and `/signals`.
- Before broader deployment, rotate bot token/chat settings, separate dev/prod tokens, and validate send path with a non-production chat target.

Read-only check commands (PowerShell, API server required):

```powershell
.\scripts\macro_pulser\run-api.ps1
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/status"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/monitor?limit=20"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/signals?limit=20"
```

## Testing

Run targeted MVP tests:

```bash
pytest tests/test_threshold_parser.py tests/test_market_mapping.py tests/test_signal_engine.py tests/test_scoring_engine.py tests/test_cooldown.py tests/test_evaluation.py tests/test_api_routes.py tests/test_replay_flow.py
```

## Assumptions

- Schedule ingestion uses deterministic HTML date extraction from official pages; official source page formats may evolve.
- Stored `source_url` values are release-content URLs (or deterministic URL templates), not schedule pages.
- For FOMC v1, statement time is fixed to 14:00 ET on the meeting decision date.
- `release_id` is deterministic (`<release_type>-<date>`).
- Kalshi public endpoint shapes can vary; adapter parsing handles common payload variants and degrades gracefully when fields are missing.
- In live mode, if official actual parsing fails, the error context is persisted in `release_actuals.parsed_payload_json`, and `DELAYED_REPRICING` will not trigger.
- Write job routes are denied when `API_WRITE_TOKEN` is unset.

## Known Limitations

- Official data parser regexes are deterministic but can be fragile to major upstream HTML/text template changes.
- Some release-content URL templates (especially GDP advance slug shapes) are deterministic heuristics and may require updates if publisher URL conventions change.
- No dashboard UI is included in v1.
- API endpoints are intentionally minimal and synchronous for management operations.
- Replay/backfill rely on already persisted snapshot history.
- In-app monitoring complements, but does not replace, external infrastructure monitoring/alerting.
- Fallback monitoring tick-failure alerts use in-memory cooldown state so they remain available when DB access itself is unavailable.
- Monitoring checks for missing actuals intentionally focus on a recent due window (last 30 days) to avoid stale historical gaps dominating current health status.
- Warning-level monitor events are persisted and queryable but are not auto-alerted to Telegram in v1.
- Official sources (including BLS) still depend on upstream site availability and normal outbound HTTPS access from the runtime environment.
- All three external HTTP adapters (BLS, Fed, BEA) use browser-like headers and `follow_redirects=True` to reduce 403 responses from upstream sites.
- `request_with_backoff` does not retry 4xx responses (client errors such as 403/404 are deterministic and retrying them would only add delay). 5xx server errors are still retried with exponential backoff.
