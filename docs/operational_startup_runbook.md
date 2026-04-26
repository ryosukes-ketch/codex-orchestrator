# Operational Startup Runbook (Offline)

## Purpose
Provide a deterministic offline startup and manual-flow validation sequence before human merge/release decisions.

## Scope
- Offline-safe validation only.
- No live provider calls.
- No production credential validation.
- Local startup policy:
  - prefer SQLite for local persisted operation.
  - SQLite profile here is for local operation, not production-scale concurrency.

Runtime/storage split reference:
- `docs/runtime_storage_boundary.md`

## Required env keys
- `STATE_BACKEND`
- `STATE_BACKEND_STRICT`
- `SQLITE_DB_PATH` (when `STATE_BACKEND=sqlite`; optional default is `data/codex.db`)
- `SQLITE_BACKUP_DIR` (optional; backup output root, default `logs/sqlite-backups`)
- `DATABASE_URL` (only when `STATE_BACKEND=postgres`)
- `TREND_PROVIDER_STRICT`
- `AUTH_SERVICE_MODE` (`dev_token` or `commercial_token`)
- `AUTH_ENABLED` (when `AUTH_SERVICE_MODE=commercial_token`)
- `AUTH_TOKEN_SEED` (when `AUTH_SERVICE_MODE=commercial_token`)
- `AUTH_TOKEN_STORE_PATH` (when `AUTH_SERVICE_MODE=commercial_token`; default `logs/auth/commercial-token-store.json`)
- `DEV_AUTH_ENABLED`
- `DEV_AUTH_TOKEN_SEED` (when `AUTH_SERVICE_MODE=dev_token`)
- `OPENCLAW_BASE_URL` (when any department model uses `openclaw/<agent-id>`)
- `OPENCLAW_GATEWAY_TOKEN` (optional; if gateway auth is enabled)
- `OPENCLAW_TIMEOUT_SECONDS` (optional; gateway request timeout, default `60`)
- `OPENCLAW_MAX_RETRIES` (optional; retry count for transport/timeout failures, default `1`)
- `OPENCLAW_RETRY_BACKOFF_SECONDS` (optional; retry backoff seconds, default `0.75`)
- `OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS` (optional; cooldown to prefer `/v1/responses` after chat failures, default `120`)
- `OPENCLAW_GATEWAY_PROBE_TIMEOUT_SECONDS` (optional; `openclaw-gateway-check.ps1` probe timeout, default `10`)
- `OPENCLAW_CONFIG_PATH` (optional; token auto-load path, default `~/.openclaw/openclaw.json`)
- `OPERATOR_API_TIMEOUT_SECONDS` (optional; operator script HTTP timeout default, default `30`)

## Recommended local startup profile
- `STATE_BACKEND=sqlite`
- `SQLITE_DB_PATH=data/codex.db`
- `STATE_BACKEND_STRICT=true`
- `TREND_PROVIDER_STRICT=false`
- `AUTH_SERVICE_MODE=dev_token`
- `DEV_AUTH_ENABLED=true`

For phase_6 real-brief reruns that should route Research/Design/Build/Review
through OpenClaw, start the app with:

```powershell
.\scripts\ai_work_system\start-server.ps1 -UseOpenClawDefaultProfile
```

`-UseOpenClawDefaultProfile` now routes `research/design/build/review` through
`openclaw/codex-orchestrator`.

To confirm the exact process-level startup config before binding the port:

```powershell
.\scripts\ai_work_system\start-server.ps1 -UseOpenClawDefaultProfile -PrintEffectiveConfigOnly
```

That JSON-only dry run shows the effective department model env values and any
OpenClaw backend override that will apply to the server process.

Use memory backend only for ephemeral smoke/experiment runs where restart persistence is not required.

Self-serve onboarding preflight:

```powershell
.\scripts\self-serve-preflight.ps1 -EnvPath .\.env
```

Commercial auth env sample (copy/paste load):

```powershell
Get-Content .\examples\env\commercial_auth_minimal.env | ForEach-Object {
  if ($_ -and -not $_.StartsWith("#")) {
    $name, $value = $_ -split "=", 2
    Set-Item -Path ("Env:{0}" -f $name) -Value $value
  }
}
```

Commercial token lifecycle admin operations (commercial mode only):

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8001/auth/tokens" -Headers @{ Authorization = "Bearer <admin-token>" }
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/auth/tokens/issue" -Headers @{ Authorization = "Bearer <admin-token>" } -ContentType "application/json" -Body '{"actor_id":"apr-2","actor_role":"approver","actor_type":"human"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/auth/tokens/revoke" -Headers @{ Authorization = "Bearer <admin-token>" } -ContentType "application/json" -Body '{"token":"<issued-token>"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/auth/tokens/rotate" -Headers @{ Authorization = "Bearer <admin-token>" } -ContentType "application/json" -Body '{"token":"<issued-token>"}'
```

## MacroPulser local quick path (BLS-free)

When validating MacroPulser local behavior in the same repository, prefer split script entrypoints:

```powershell
.\scripts\macro_pulser\run-api.ps1
.\scripts\macro_pulser\local-dev-smoke.ps1 -CheckReadOnlyApi -ApiBaseUrl http://127.0.0.1:8000
```

Legacy compatibility aliases (still supported):
- `python -m app.main api`
- `.\scripts\local-dev-smoke.ps1`

## Startup matrix
1. Minimal valid startup
   - `STATE_BACKEND=memory`
   - `STATE_BACKEND_STRICT=false`
   - `TREND_PROVIDER_STRICT=false`
   - `DEV_AUTH_ENABLED=true`
   - Expected:
     - app boots
     - `GET /health` -> `200`
     - protected endpoints require bearer auth

2. Malformed strict backend (fail-fast)
   - `STATE_BACKEND=postgres`
   - `DATABASE_URL` unset
   - `STATE_BACKEND_STRICT` malformed (for example `not-a-bool`)
   - Expected:
     - startup fails with strict backend requirement error

3. Corrected backend/auth recovery
   - Correct to `STATE_BACKEND=memory`
   - set `DEV_AUTH_ENABLED=false`
   - Expected on fresh app init:
     - app boots
     - approval resume can complete without bearer auth

4. Provider strict matrix
   - malformed `TREND_PROVIDER_STRICT` + unknown provider -> `409`
   - corrected `TREND_PROVIDER_STRICT=false` + unknown provider -> mock fallback success

5. Non-strict postgres fallback
   - `STATE_BACKEND=postgres`
   - missing/unavailable DB
   - `STATE_BACKEND_STRICT=false`
   - Expected:
     - app boots via memory fallback
     - core manual approval workflow remains operable

6. SQLite persistence startup
   - `STATE_BACKEND=sqlite`
   - `SQLITE_DB_PATH=data/codex.db`
   - `STATE_BACKEND_STRICT=true`
   - Expected:
     - app boots and initializes SQLite schema
     - project audit remains available after fresh app initialization

## Concurrency and rollout note
- SQLite path here is intended for local deterministic operation with limited concurrency.
- Do not treat SQLite local profile as production database validation.
- Production-like concurrency, migration, and durability must be validated separately against production DB backend.

## Manual workflow smoke sequence
1. `POST /orchestrator/run` with external-provider alias (`gemini`) to enter `waiting_approval`.
2. `POST /orchestrator/resume/approval` under expected auth mode.
3. Verify `GET /projects/{project_id}/audit` event integrity:
   - actor resolution recorded
   - no duplicate approval/retry events on safe retries
   - conflict detail remains deterministic for rejected/non-pending retry branches

One-command equivalent for local operator smoke:

- `.\scripts\operator-full-cycle.ps1 -Mode approval`
- `.\scripts\operator-full-cycle.ps1 -Mode reject-replan`
- `.\scripts\operator-cycle-suite.ps1` (runs both modes + writes suite handoff envelope)
- `.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-summary.json` (machine-check suite gate policy)
- `.\scripts\operator-stage-gate.ps1 -BundleManifestPath .\logs\operator-suites\<stamp>\bundle-manifest.json` (manifest-first suite gate replay)
- `.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-summary.json -MaxLlmTransportFallbacks 0` (strict transport fallback budget)
- Optional strict post-check:
  - `.\scripts\operator-audit-assert.ps1 -ProjectId <id> -ExpectedStatus completed`
  - `.\scripts\operator-audit-assert.ps1 -ProjectId <id> -ExpectedStatus completed -MaxLlmTransportFallbacks 0`
  - `.\scripts\operator-audit-assert.ps1 -ProjectId <id> -AuditJsonPath .\logs\operator-cycles\<stamp>\approval\audit.json`
  - `.\scripts\operator-status.ps1 -ProjectId <id> -AuditJsonPath .\logs\operator-cycles\<stamp>\approval\audit.json -SummaryOutPath .\logs\operator-status-summary.json`
  - `.\scripts\operator-status.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json -SummaryOutPath .\logs\operator-status-summary.json`
  - `.\scripts\operator-audit.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json`
  - `.\scripts\operator-stage-report.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json`
  - `.\scripts\operator-audit-assert.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json -ExpectedStatus completed`

`operator-full-cycle.ps1` now writes `status-summary.json` inside each cycle
bundle, and `operator-cycle-suite.ps1` promotes those compact status artifacts
into `suite-summary.json` / `suite-handoff.json` / `suite-stage-gate.json`.
Both cycle and suite bundles also write `bundle-manifest.json`, which is the
stable replay entrypoint for operator menu / handoff / stage gate flows.

## Offline gates
- `.\scripts\refresh-openapi.ps1`
- `python -m pytest -q tests`
- `python -m ruff check app`
- `python -m ruff check tests`
- Optional integrated operator gate:
- `.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite`
  - strict fallback budget example:
  - `.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorMaxStageFallbacks 0`
  - `.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorMaxLlmTransportFallbacks 0`
  - strict telemetry proof example:
  - `.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorRequireStageTelemetry`
  - strict auth+policy proof example:
  - `.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorAuthorizationOperator "Bearer dev-operator-token" -OperatorRequirePolicyAssertions -OperatorPolicyMode strict -OperatorEnforceModelAllowlist -OperatorFailOnBackendOverrideMismatch -OperatorRequireAuthEvidence -OperatorExpectedAuthRoles "operator,approver" -OperatorAuthPolicyMode strict -OperatorMaxRevisionReplanAttempts 3`
  - breakglass evidence example:
  - `.\scripts\ai_work_system\release-readiness.ps1 -SkipLiveSmoke -SkipSmoke -SkipResilience -SkipVerify -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorAuthorizationOperator "Bearer dev-operator-token" -OperatorRequirePolicyAssertions -OperatorPolicyMode breakglass -OperatorBreakglass -OperatorBreakglassReason "temporary live remediation verification" -OperatorBreakglassActor "<operator-id>"`
  - include OpenClaw gateway proof in same run:
  - `.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOpenClawGatewayCheck`

Successful readiness runs now emit:
- `logs\operational-readiness\readiness-summary-<timestamp>.json`
- `logs\operational-readiness\readiness-manifest-<timestamp>.json`

Use the readiness manifest as the top-level replay root for offline evidence
inspection instead of reconstructing individual log file names by hand.

## OpenClaw local gateway note (optional)
- If department models use `openclaw/<agent-id>`, verify gateway connectivity:
  - `.\scripts\openclaw-gateway-check.ps1`
  - `.\scripts\openclaw-evidence-capture.ps1` (writes evidence JSON + staging record entry)
- Runtime token resolution order for department routing:
  1. `OPENCLAW_GATEWAY_TOKEN` (or `OPENCLAW_AUTH_TOKEN`)
  2. `OPENCLAW_CONFIG_PATH` / `~/.openclaw/openclaw.json` (`gateway.auth.token`)
- `404` from `/v1/chat/completions` usually means OpenClaw HTTP endpoints are disabled.
- `openclaw-gateway-check.ps1` now records `/v1/models` probe details in evidence
  (`models_probe_status_code`, `models_probe_content_type`, `models_probe_model_ids`).
- Enable in `~/.openclaw/openclaw.json` (JSON5):

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

## Stage telemetry compatibility note
- If `department_stage_totals` are missing in `/audit`, operator scripts derive
  telemetry from `department_stage_executed` events and mark source as
  `events_derived`.
- If older fallback-only stage events omit `stage_failure_reason`, operator
  scripts normalize them as `success + fallback` and expose the count through
  telemetry notes and cycle/suite evidence.
- Use `-NoEventDerivedTelemetry` on `operator-stage-report.ps1` /
  `operator-audit-assert.ps1` / `operator-status.ps1` to require payload-native telemetry only.

## SQLite backup / restore workflow (phase_8 pilot baseline)

Before risky changes or before running long live sessions:

```powershell
.\scripts\sqlite-verify.ps1
.\scripts\sqlite-backup.ps1 -Label pre-change
.\scripts\sqlite-export.ps1 -Label pre-change-handoff -Zip
```

Restore flow (server should be stopped while restoring):

```powershell
.\scripts\sqlite-restore.ps1 -BackupManifestPath .\logs\sqlite-backups\<backup>.manifest.json -Force
.\scripts\sqlite-verify.ps1
```

Post-restore operator sanity check:

```powershell
.\scripts\operator-run.ps1 -BriefPath .\examples\briefs\sample_brief.json -TrendProvider gemini-flash-lite-latest
.\scripts\operator-status.ps1 -ProjectId <project_id>
```

Replay evidence export (readiness or suite manifest roots):

```powershell
.\scripts\operator-replay-export.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\operator-replay-export.ps1 -BundleManifestPath .\logs\operator-suites\<timestamp>\bundle-manifest.json -Zip
.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```

Operational notes:
- `sqlite-backup.ps1` uses SQLite backup API snapshots (safe for WAL mode).
- `sqlite-restore.ps1` creates a pre-restore safety snapshot by default unless `-SkipPreRestoreBackup` is set.
- Use `-OutPath` on sqlite scripts to persist deterministic JSON evidence for support handoff.
- `operator-support-bundle.ps1` packages replay artifacts + failure classification in one handoff set.

Support classification quick map (`failure-classification.json`):
- `runtime`: timeout/endpoint/transport/runtime failures
- `provider_auth`: upstream rejection, credit/token/provider access
- `policy`: allowlist/auth evidence/override mismatch/breakglass violations
- `semantic_output`: non-JSON/missing-required-keys/review changes_requested stops
- `persistence_restore`: sqlite backup/restore/verify/export failures
- `operator_flow`: lifecycle status or transition mismatches

## Commercial pilot references (phase_9)

For customer-facing pilot onboarding and support handoff, also use:
- `docs/commercial_pilot_delivery_kit.md`
- `docs/commercial_pilot_support_runbook.md`
- `docs/commercial_pilot_scope_and_constraints.md`
- `docs/commercial_pilot_acceptance_checklist.md`
- `docs/commercial_pilot_handoff_checklist.md`
- `docs/commercial_pilot_inquiry_template.md`

## Self-serve productization references (phase_10)

- `docs/self_serve_distribution_kit_baseline.md`
- `docs/self_serve_onboarding_guardrails.md`
- `docs/self_serve_update_rollback_safety.md`
- `docs/self_serve_support_safe_packaging.md`
- `docs/self_serve_commercial_handoff_readiness.md`
- `docs/self_serve_product_acceptance_checklist.md`

Phase_10 operational commands:

```powershell
.\scripts\self-serve-preflight.ps1 -EnvPath .\.env
.\scripts\self-serve-update-guard.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\self-serve-support-intake.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\self-serve-handoff-package.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```

## Post-launch trend review references (phase_12)

- `docs/launch_week_support_trend_review.md`
- `docs/launch_week_runbook_delta_backlog.md`
- `docs/phase12_recurring_issue_hardening.md`
- `docs/post_launch_issue_triage.md`
- `docs/post_launch_priority_scoring.md`
- `docs/known_issue_routing.md`
- `docs/post_launch_release_backlog_flow.md`
- `.\scripts\launch-week-trend-review.ps1 -WindowDays 7`
- `.\scripts\support-recurring-hardening.ps1`
- `.\scripts\post-launch-triage.ps1`
- `.\scripts\post-launch-priority-score.ps1`
- `.\scripts\known-issue-route.ps1`
- `.\scripts\post-launch-backlog-export.ps1`

## Still requires live validation
- real provider credentialed execution
- production authn/authz rollout (JWT/OIDC)
- production database migration/rollback operations
- deployment/traffic/runtime SLO validation

## Release-train automation references (phase_14)

After post-launch feedback routing (`post-launch-backlog-export.ps1`), run release-train packaging:

```powershell
.\scripts\release-candidate-promote.ps1
.\scripts\release-decision-package.ps1
.\scripts\release-notes-assemble.ps1
.\scripts\known-issue-publication-route.ps1
.\scripts\release-train-evidence-export.ps1 -Zip
```

Phase_14 docs:
- `docs/release_candidate_promotion.md`
- `docs/release_go_hold_rollback_decision.md`
- `docs/release_note_publication_flow.md`
- `docs/release_train_evidence_flow.md`

## GA launch execution baseline (phase_15)

Run the integrated GA launch package command:

```powershell
.\scripts\ga-launch-package-execute.ps1 -Zip
.\scripts\early-ops-incident-loop.ps1 -WindowDays 7
.\scripts\hotfix-next-release-route.ps1
.\scripts\phase15-evidence-closeout.ps1 -Zip
```

Docs:
- `docs/ga_launch_execution_baseline.md`
- `docs/phase15_early_operations_stabilization.md`
- `docs/phase15_hotfix_next_release_routing.md`
- `docs/phase15_evidence_closure.md`

## GA adoption weekly reliability review (phase_16)

```powershell
.\scripts\ga-weekly-reliability-review.ps1 -WindowDays 7 -Zip
```

Doc:
- `docs/phase16_ga_weekly_reliability_review.md`

## Monthly reliability governance package (phase_17)

```powershell
.\scripts\ga-monthly-reliability-targets.ps1 -WindowDays 30 -Zip
.\scripts\ga-closure-sla-breach-route.ps1 -Zip
```

Doc:
- `docs/phase17_monthly_reliability_governance.md`
- `docs/phase17_closure_sla_routing.md`

## Quarterly governance package (phase_18)

```powershell
.\scripts\ga-quarterly-reliability-governance.ps1 -WindowDays 90 -Zip
.\scripts\ga-quarterly-closure-sla-ownership.ps1 -WindowDays 90 -Zip
.\scripts\ga-quarterly-review-package.ps1 -Zip
```

Doc:
- `docs/phase18_quarterly_governance.md`

## Upgrade and migration safety operations (phase_19)

```powershell
.\scripts\ga-upgrade-impact-matrix.ps1 -Zip
.\scripts\ga-migration-rehearsal-package.ps1 -Zip
.\scripts\ga-upgrade-rollback-safety.ps1 -Zip
.\scripts\ga-upgrade-evidence-closeout.ps1 -Zip
```

Doc:
- `docs/phase19_upgrade_migration_safety.md`

## Environment compatibility and support-at-scale baseline (phase_20)

```powershell
.\scripts\ga-supported-environment-matrix.ps1 -Zip
.\scripts\ga-compatibility-preflight.ps1 -Zip
.\scripts\ga-support-intake-normalization.ps1 -Zip
.\scripts\ga-environment-support-closeout.ps1 -Zip
```

Doc:
- `docs/phase20_environment_compatibility_support.md`

## Auditability, retention, and compliance-lite governance (phase_21)

```powershell
.\scripts\ga-artifact-retention-coverage.ps1 -Zip
.\scripts\ga-audit-traceability-index.ps1 -Zip
.\scripts\ga-incident-change-ledger.ps1 -Zip
.\scripts\ga-auditability-closeout.ps1 -Zip
```

Doc:
- `docs/phase21_auditability_retention_governance.md`

## Steady-state commercial operations closure (phase_22)

```powershell
.\scripts\ga-steady-state-operations-handbook.ps1 -Zip
.\scripts\ga-release-ops-cadence-baseline.ps1 -Zip
.\scripts\ga-end-to-end-operations-evidence.ps1 -Zip
.\scripts\ga-steady-state-closeout.ps1 -Zip
```

Docs:
- `docs/phase22_steady_state_operations_closure.md`
- `docs/steady_state_operations_handbook.md`
- `docs/release_ops_cadence_baseline.md`

## Steady-state bounded improvement backlog

```powershell
.\scripts\ga-steady-state-improvement-backlog.ps1 -Zip
```

Doc:
- `docs/steady_state_improvement_backlog.md`

## Steady-state watch backlog burn-down

```powershell
.\scripts\ga-steady-state-burndown.ps1 -Zip
```

Doc:
- `docs/steady_state_burndown_tracking.md`

## Steady-state checkpoint refresh

```powershell
.\scripts\ga-steady-state-checkpoint-refresh.ps1 -Zip
```

Doc:
- `docs/steady_state_checkpoint_refresh.md`

## Steady-state watchlist ownership routing

```powershell
.\scripts\ga-steady-state-escalation-watchlist-route.ps1 -Zip
```

Owner acknowledgment rule example:

```powershell
.\scripts\ga-steady-state-escalation-watchlist-route.ps1 -OwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

Doc:
- `docs/steady_state_watchlist_ownership_routing.md`
- `docs/steady_state_watchlist_owner_ack.json`

## Steady-state single-entry runtime loop

```powershell
.\scripts\steady-state-run.ps1 -Mode daily -Zip
```

Weekly heavier cycle:

```powershell
.\scripts\steady-state-run.ps1 -Mode weekly -Zip
```

Docs:
- `docs/steady_state_runtime_loop.md`
- `docs/steady_state_runtime_state.json`
