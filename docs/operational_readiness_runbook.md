# Operational Readiness Runbook

## 1. Primary command

Use this command as the default operational gate before starting work or shipping changes.

```powershell
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token"
```

Legacy compatibility alias (still supported):

```powershell
.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token"
```

## 2. Pass criteria

All of the following must pass:

- Preflight
- Live smoke with automatic seeds
- Approval live flow
- Reject -> Revision -> Replanning live flow
- Smoke
- Resilience
- Full verification
- Final output ends with `All checks passed!`

## 3. When to run

- Before starting operational work
- After changes to orchestrator, API, auth, approval, revision, replanning, or readiness scripts
- Before merging significant changes to `master`
- After merging to `master` when extra safety is desired

Runtime/storage split reference:
- `docs/runtime_storage_boundary.md`

## 4. Fail handling

If any stage fails, treat the environment as not ready.

Check in this order:

1. `/health` returns `ok`
2. Local API server is running
3. Authorization value is correct
4. Which stage failed: Preflight / Live smoke / Smoke / Resilience / Full verification
5. What changed immediately before the failure

Do not continue with operational work until the same readiness command passes end-to-end.

## 5. Logs

Operational logs are written under `logs/operational-readiness/`.

- Treat them as generated runtime output
- Do not commit them to Git
- Check the newest seed log and live-smoke log first when investigating a failure
- Each successful readiness run now writes:
  - `readiness-summary-<timestamp>.json`
  - `readiness-manifest-<timestamp>.json`
- Prefer `readiness-manifest-<timestamp>.json` as the replay root; it points to:
  - seed/live-smoke evidence
  - operator suite manifest/summary (when `-RunOperatorSuite` is used)
  - optional OpenClaw evidence (when `-RunOpenClawGatewayCheck` is used)

## 6. Daily-use commands

```powershell
.\scripts\refresh-openapi.ps1
.\scripts\preflight.ps1
.\scripts\live-smoke.ps1
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token"
# Optional extended gate: include operator suite + stage gate
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorMaxStageFallbacks 0
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorMaxLlmTransportFallbacks 0
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorRequireStageTelemetry
# phase_7 strict policy gate (allowlist + backend override mismatch deny)
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorRequirePolicyAssertions -OperatorPolicyMode strict -OperatorEnforceModelAllowlist -OperatorFailOnBackendOverrideMismatch
# phase_7 strict auth boundary + policy gate
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorAuthorizationOperator "Bearer dev-operator-token" -OperatorRequirePolicyAssertions -OperatorPolicyMode strict -OperatorEnforceModelAllowlist -OperatorFailOnBackendOverrideMismatch -OperatorRequireAuthEvidence -OperatorExpectedAuthRoles "operator,approver" -OperatorAuthPolicyMode strict -OperatorMaxRevisionReplanAttempts 3
# phase_7 breakglass example (exception run must keep explicit reason/actor evidence)
.\scripts\ai_work_system\release-readiness.ps1 -SkipLiveSmoke -SkipSmoke -SkipResilience -SkipVerify -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorAuthorizationOperator "Bearer dev-operator-token" -OperatorRequirePolicyAssertions -OperatorPolicyMode breakglass -OperatorBreakglass -OperatorBreakglassReason "temporary live remediation verification" -OperatorBreakglassActor "<operator-id>"
# Optional: include OpenClaw gateway proof in the same gate run
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOpenClawGatewayCheck
```

Commercial auth profile example (`AUTH_SERVICE_MODE=commercial_token`):

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

Notes:
- In `commercial_token` mode, `AUTH_TOKEN_SEED` is authoritative.
- `AUTH_TOKEN_STORE_PATH` persists issued/revoked/rotated token state (default: `logs/auth/commercial-token-store.json`).
- `DEV_AUTH_*` values are ignored by the runtime resolver in this mode.
- Use `.\examples\env\commercial_auth_minimal.env` for a copy/paste-ready seed profile.

```powershell
Get-Content .\examples\env\commercial_auth_minimal.env | ForEach-Object {
  if ($_ -and -not $_.StartsWith("#")) {
    $name, $value = $_ -split "=", 2
    Set-Item -Path ("Env:{0}" -f $name) -Value $value
  }
}
```

Commercial token lifecycle admin API (admin role required, commercial mode only):

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8001/auth/tokens" -Headers @{ Authorization = "Bearer <admin-token>" }
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/auth/tokens/issue" -Headers @{ Authorization = "Bearer <admin-token>" } -ContentType "application/json" -Body '{"actor_id":"apr-2","actor_role":"approver","actor_type":"human"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/auth/tokens/revoke" -Headers @{ Authorization = "Bearer <admin-token>" } -ContentType "application/json" -Body '{"token":"<issued-token>"}'
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/auth/tokens/rotate" -Headers @{ Authorization = "Bearer <admin-token>" } -ContentType "application/json" -Body '{"token":"<issued-token>"}'
```

If route/auth contract changes are made, regenerate `openapi.json` before running readiness.

## 7. Operational decision rule

Use this single rule:

- If `.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow` passes, the environment is ready
- If it fails, the environment is not ready

Smoke/resilience targeted suites include operator contract + PowerShell script
E2E checks (`tests/test_operator_workflow_contract.py`,
`tests/test_operator_scripts_e2e.py`) to catch script-layer regressions.

## 8. Current baseline

- Branch baseline: `master`
- Logs are ignored in Git
- Readiness includes automatic seed creation for approval and reject/revision/replanning live paths

## 9. SQLite policy for local operation

- Recommended local backend settings before running readiness:
  - `STATE_BACKEND=sqlite`
  - `SQLITE_DB_PATH=data/codex.db`
  - `SQLITE_BACKUP_DIR=logs/sqlite-backups`
  - `STATE_BACKEND_STRICT=true`
- Positioning:
  - SQLite is the default local persistence choice for operator/day-to-day runs.
  - SQLite is not a substitute for production-grade high-concurrency database operation.
- Restart handling:
  - SQLite retains project/audit history across app restarts.
  - memory backend does not retain state across restarts.
- Execution expectation:
  - run readiness gate first, then operator scripts.
  - for high-concurrency or multi-instance scenarios, move to production database validation.

SQLite recovery commands:

```powershell
.\scripts\sqlite-verify.ps1
.\scripts\sqlite-backup.ps1 -Label pre-readiness
.\scripts\sqlite-restore.ps1 -BackupManifestPath .\logs\sqlite-backups\<backup>.manifest.json -Force
.\scripts\sqlite-verify.ps1
.\scripts\sqlite-export.ps1 -Label readiness-handoff -Zip
```

Restore checks:
- keep API server stopped during restore.
- run `sqlite-verify.ps1` immediately after restore.
- then run a minimal operator smoke (`operator-run` + `operator-status`) before full readiness.
- for handoff/replay packaging, export from readiness or suite manifest roots:
  - `.\scripts\operator-replay-export.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip`
  - `.\scripts\operator-replay-export.ps1 -BundleManifestPath .\logs\operator-suites\<timestamp>\bundle-manifest.json -Zip`

## 10. Operator workflow

For day-to-day project operations after readiness passes, use:

- `docs/operator_workflow_runbook.md`
- `.\scripts\operator-stage-report.ps1 -ProjectId <id>` for compact stage diagnostics
- `.\scripts\operator-audit-assert.ps1 -ProjectId <id> -ExpectedStatus completed` for machine-verifiable audit invariants
- `.\scripts\operator-stage-report.ps1 -ProjectId <id> -AuditJsonPath .\logs\operator-cycles\<stamp>\approval\audit.json` for offline replay
- `.\scripts\operator-audit-assert.ps1 -ProjectId <id> -AuditJsonPath .\logs\operator-cycles\<stamp>\approval\audit.json` for offline assertions
- `.\scripts\operator-status.ps1 -ProjectId <id> -AuditJsonPath .\logs\operator-cycles\<stamp>\approval\audit.json -SummaryOutPath .\logs\operator-status-summary.json` for quick offline status replay
- `.\scripts\operator-status.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json -SummaryOutPath .\logs\operator-status-summary.json` for manifest-first status replay
- `.\scripts\operator-audit.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json` for manifest-first audit replay
- `.\scripts\operator-stage-report.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json` for manifest-first stage diagnostics
- `.\scripts\operator-audit-assert.ps1 -BundleManifestPath .\logs\operator-cycles\<stamp>\approval\bundle-manifest.json -ExpectedStatus completed` for manifest-first assertions
- `.\scripts\operator-full-cycle.ps1 -Mode approval` for one-command operator bundle
- `.\scripts\operator-full-cycle.ps1 -Mode reject-replan` for rejection path bundle
- `.\scripts\operator-cycle-suite.ps1` for both operator paths + handoff envelope bundle
- `.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-summary.json` for suite-level pass/fail policy
- `.\scripts\operator-stage-gate.ps1 -BundleManifestPath .\logs\operator-suites\<stamp>\bundle-manifest.json` for manifest-first suite replay
- `.\scripts\operator-stage-gate.ps1 -SummaryPath .\logs\operator-suites\<stamp>\suite-summary.json -MaxLlmTransportFallbacks 0` for strict gateway transport fallback budget
- `.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip` for pilot incident handoff
- `.\scripts\ai_work_system\operator-menu.ps1` now accepts `readiness-manifest-<timestamp>.json` as the replay root for status/audit/stage-report/assert/handoff/stage-gate flows

Commercial pilot packaging references:
- `docs/commercial_pilot_delivery_kit.md`
- `docs/commercial_pilot_support_runbook.md`
- `docs/commercial_pilot_scope_and_constraints.md`
- `docs/commercial_pilot_acceptance_checklist.md`
- `docs/commercial_pilot_handoff_checklist.md`
- `docs/commercial_pilot_inquiry_template.md`

Self-serve productization references (phase_10):
- `docs/self_serve_distribution_kit_baseline.md`
- `docs/self_serve_onboarding_guardrails.md`
- `docs/self_serve_update_rollback_safety.md`
- `docs/self_serve_support_safe_packaging.md`
- `docs/self_serve_commercial_handoff_readiness.md`
- `docs/self_serve_product_acceptance_checklist.md`

Commercial launch governance references (phase_11):
- `docs/release_governance_baseline.md`
- `docs/release_notes_template.md`
- `docs/release_notes_phase11_example.md`
- `docs/known_issues_register.md`
- `docs/commercial_launch_support_boundary.md`
- `docs/commercial_launch_sla_lite.md`
- `docs/commercial_launch_go_no_go_checklist.md`

Post-launch trend review references (phase_12):
- `docs/launch_week_support_trend_review.md`
- `docs/launch_week_runbook_delta_backlog.md`
- `docs/phase12_recurring_issue_hardening.md`
- `docs/post_launch_issue_triage.md`
- `docs/post_launch_priority_scoring.md`
- `docs/known_issue_routing.md`
- `docs/post_launch_release_backlog_flow.md`

Post-launch trend review command:
- `.\scripts\launch-week-trend-review.ps1 -WindowDays 7`
- `.\scripts\support-recurring-hardening.ps1`
- `.\scripts\post-launch-triage.ps1`
- `.\scripts\post-launch-priority-score.ps1`
- `.\scripts\known-issue-route.ps1`
- `.\scripts\post-launch-backlog-export.ps1`

Self-serve packaging commands:
- `.\scripts\self-serve-preflight.ps1 -EnvPath .\.env`
- `.\scripts\self-serve-update-guard.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip`
- `.\scripts\self-serve-support-intake.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip`
- `.\scripts\self-serve-handoff-package.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip`

Commercial launch evidence commands:
- `.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json`
- `.\scripts\self-serve-support-intake.ps1 -SupportBundleManifestPath .\logs\self-serve\phase11-launch-evidence-<timestamp>\support-bundle.manifest.json`
- `.\scripts\self-serve-handoff-package.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -SupportIntakeManifestPath .\logs\self-serve\phase11-launch-evidence-<timestamp>\support-intake.manifest.json`

`operator-full-cycle.ps1` now emits `status-summary.json` alongside `status.json`,
and `operator-cycle-suite.ps1` carries those compact paths into
`suite-summary.json`, `suite-handoff.json`, and `suite-stage-gate.json` so
offline replay can stay on bundle artifacts instead of raw `/audit` fetches.
Each bundle also emits `bundle-manifest.json`, and readiness now prefers that
manifest when resolving suite artifacts after `-RunOperatorSuite`.

If using OpenClaw-routed models (`openclaw/*`), run:

- `.\scripts\openclaw-gateway-check.ps1`
- timeout tuning example:
  - `.\scripts\openclaw-gateway-check.ps1 -TimeoutSec 60 -ProbeTimeoutSec 20`
- evidence capture shortcut:
  - `.\scripts\openclaw-evidence-capture.ps1`

If it returns `404`, enable OpenClaw HTTP endpoints in `~/.openclaw/openclaw.json` and retry.

Full live-flow seed mismatch triage:
- when `full-live-flow.ps1` fails with `expected waiting_approval` vs `actual in_progress`, open the emitted `full-live-flow-seed-mismatch-*.json`.
- the diagnostic now includes `audit_snapshot` with:
  - `project_status`
  - `failing_stage_count`
  - top `failing_stages` (department/stage/failure_reason/model/endpoint)
- if deeper context is needed, run:
  - `.\scripts\operator-audit.ps1 -ProjectId <diagnostic project_id> -Full`

OpenClaw OAuth runtime triage (codex-orchestrator):
- run auth probe:
  - `openclaw models status --agent codex-orchestrator --probe`
- if probe reports `openai-codex` refresh failure (for example `refresh_token_reused`), re-authenticate from an interactive TTY:
  - `openclaw models auth login --provider openai-codex --set-default`
- after successful re-authentication, rerun:
  - `.\scripts\openclaw-gateway-check.ps1 -AgentId codex-orchestrator -BackendModel openai-codex/gpt-5.2`
  - strict `release-readiness` command for phase evidence closure
- note: `models status` can show `openai-codex:default ok expires in 0m` while still failing refresh on probe; treat probe failure as authoritative.

Stage telemetry compatibility note:
- If `department_stage_totals` are missing in `/audit`, operator scripts derive
  totals from `department_stage_executed` events and mark telemetry source as
  `events_derived`.
- If older fallback-only stage events omit `stage_failure_reason`, operator
  scripts normalize them as `success + fallback` and record the count in
  telemetry notes / cycle artifacts.
- Add `-NoEventDerivedTelemetry` when strict payload-only telemetry is required.
- `operator-status.ps1` surfaces the same compatibility state for quick triage
  without opening stage-report artifacts.

Operator script API timeout control:
- default: `OPERATOR_API_TIMEOUT_SECONDS` (env, seconds, default `30`)
- per-command override: `-TimeoutSec <seconds>`

Extended release-readiness options (optional):
- `-RunOperatorSuite`
- `-OperatorBriefPath <path>`
- `-OperatorRunTrendProvider <provider>`
- `-OperatorAuthorizationOperator <Bearer token>`
- `-OperatorOutputDir <path>`
- default when omitted: `logs\operational-readiness\operator-suite-<timestamp>`
- `-OperatorSkipApprovalMode`
- `-OperatorSkipRejectReplanMode`
- `-OperatorFailOnFallback`
- `-OperatorRequireStageTelemetry`
- `-OperatorMaxStageFailures <int>`
- `-OperatorMaxStageFallbacks <int>`
- `-OperatorMaxLlmTransportFallbacks <int>`
- `-OperatorMaxRevisionReplanAttempts <int>=1+` (bounded revise/replan retries per cycle)
- `-OperatorRequirePolicyAssertions`
- `-OperatorRequireAuthEvidence`
- `-OperatorExpectedAuthRoles <csv: operator,approver>`
- `-OperatorAuthPolicyMode <normal|strict|breakglass>`
- `-OperatorBreakglass`
- `-OperatorBreakglassReason <text>`
- `-OperatorBreakglassActor <id>`
- `-OperatorPolicyMode <normal|strict|breakglass>`
- `-OperatorEnforceModelAllowlist`
- `-OperatorAllowedEffectiveProviders <csv>`
- `-OperatorAllowedEffectiveModels <csv>`
- `-OperatorAllowedOpenClawAgents <csv>`
- `-OperatorFailOnBackendOverrideMismatch`
- `-RunOpenClawGatewayCheck`
- `-OpenClawGatewayBaseUrl <url>`
- `-OpenClawGatewayAgentId <agent-id>`
  - default: `codex-orchestrator`
- `-OpenClawBackendModel <provider/model>`
- `-OpenClawGatewayTimeoutSec <seconds>`
- `-OpenClawGatewayProbeTimeoutSec <seconds>`
- `-OpenClawEvidenceOutPath <path>`
- `-AppendOpenClawStagingRecord`
- `-OpenClawStagingRecordPath <path>`

Readiness replay artifacts:
- `readiness-summary-<timestamp>.json`
- `readiness-manifest-<timestamp>.json`

Strict policy failure triage:
- if strict run fails, inspect `operator_suite_stage_gate` from readiness manifest first
- then inspect each cycle `audit_assert` artifact from the suite/cycle bundle manifest
- confirm `deny_reasons` in stage-gate report and `errors` in audit-assert for:
  - effective provider/model/agent allowlist mismatch
  - backend override mismatch
  - auth evidence missing or operator/approver boundary violation
  - breakglass reason/actor evidence mismatch
- collect a deterministic support package:
  - `.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip`
- use `failure-classification.json` categories to route first response:
  - `runtime`: timeout/endpoint/transport/runtime failures
  - `provider_auth`: upstream rejection, credit/token/provider access
  - `policy`: allowlist/auth evidence/override mismatch/breakglass violations
  - `semantic_output`: non-JSON, missing keys, review changes_requested stops
  - `persistence_restore`: sqlite backup/restore/verify/export issues
  - `operator_flow`: status transition / lifecycle flow mismatches

## 11. MacroPulse local BLS-free smoke

Use this deterministic local flow when validating MacroPulse MVP behavior without remote schedule ingestion:

```powershell
.\scripts\macro_pulser\local-dev-smoke.ps1
```

Legacy compatibility alias (still supported):

```powershell
.\scripts\local-dev-smoke.ps1
```

The script runs manual seed steps for releases/actuals/markets/snapshots, then executes:
- `python -m app.macro_pulser.main live --once --skip-remote-schedules`
- `python -m app.macro_pulser.main monitor --once`

Use `python -m app.macro_pulser.main monitor --loop` only when continuous watch mode is required.

## 12. Telegram token hygiene (pre-production)

- Keep development and production Telegram bot tokens separated.
- Do not reuse dev bot tokens for production channels.
- Rotate Telegram bot token and chat target before production cutover.
- Keep `MONITORING_TELEGRAM_CHAT_ID` distinct when monitoring alerts should be isolated from normal signal notifications.

## 13. Internal beta read-only checks

After `.\scripts\macro_pulser\local-dev-smoke.ps1` succeeds, use these read-only surfaces for quick operational confirmation:

- `GET /status`
- `GET /monitor`
- `GET /signals`

These endpoints are observability-only and do not change signal or monitoring state.

Internal beta quick verification order:
1. Run `.\scripts\macro_pulser\local-dev-smoke.ps1`
2. Check `GET /status` for latest live success timestamp and aggregate counts
3. Check `GET /monitor` for current open monitor events
4. Check `GET /signals` for latest emitted signals

If the API process is not running, start it in a separate terminal first:

```powershell
.\scripts\macro_pulser\run-api.ps1
```

Copy/paste checks (PowerShell):

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/status"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/monitor?limit=20"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/signals?limit=20"
```

Internal beta decision rule:
- `PASS`:
  - `scripts/macro_pulser/local-dev-smoke.ps1` ends with `LOCAL DEV SMOKE: PASS`
  - `/status` returns a recent `latest_live_cycle_success_at_utc`
  - `/signals` returns non-empty recent items for the current seeded scenario
- `REVIEW`:
  - smoke ends with `LOCAL DEV SMOKE: REVIEW`, or
  - `/monitor` contains open critical events that are not explained by the current test scenario
- `STOP`:
  - smoke command fails, API read-only endpoints are unreachable, or
  - DB/external dependency failures block deterministic local verification

Local dev mode vs internal beta:
- Local dev mode proves deterministic behavior with seeded release/actual/market/snapshot data and `--skip-remote-schedules`.
- Internal beta is an operational repeatability gate: deterministic local flow plus read-only observability confirmation (`/status`, `/monitor`, `/signals`) and Telegram delivery path checks.

Production gap note:
- Internal beta checks above do not replace production readiness validation for real upstream dependency stability (BLS/BEA/Fed/Kalshi).

## 15. Release-train automation (phase_14)

Transform phase_13 backlog exports into release-train candidate/decision/notes/evidence artifacts:

```powershell
.\scripts\release-candidate-promote.ps1
.\scripts\release-decision-package.ps1
.\scripts\release-notes-assemble.ps1
.\scripts\known-issue-publication-route.ps1
.\scripts\release-train-evidence-export.ps1 -Zip
```

Review documents:
- `docs/release_candidate_promotion.md`
- `docs/release_go_hold_rollback_decision.md`
- `docs/release_note_publication_flow.md`
- `docs/release_train_evidence_flow.md`

When strict readiness succeeds, include release-train evidence in staging closure:
- `release-candidate.manifest.json`
- `release-decision-package.manifest.json`
- `release-notes.manifest.json`
- `known-issue-publication.manifest.json`
- `release-train-evidence.manifest.json`

## 16. GA launch execution baseline (phase_15)

Execute a full GA launch package from the current release-train baseline:

```powershell
.\scripts\ga-launch-package-execute.ps1 -Zip
.\scripts\early-ops-incident-loop.ps1 -WindowDays 7
.\scripts\hotfix-next-release-route.ps1
.\scripts\phase15-evidence-closeout.ps1 -Zip
```

Review:
- `docs/ga_launch_execution_baseline.md`
- `docs/phase15_early_operations_stabilization.md`
- `docs/phase15_hotfix_next_release_routing.md`
- `docs/phase15_evidence_closure.md`

## 17. GA adoption weekly reliability review (phase_16)

```powershell
.\scripts\ga-weekly-reliability-review.ps1 -WindowDays 7 -Zip
```

Review doc:
- `docs/phase16_ga_weekly_reliability_review.md`

## 18. Monthly reliability governance package (phase_17)

```powershell
.\scripts\ga-monthly-reliability-targets.ps1 -WindowDays 30 -Zip
.\scripts\ga-closure-sla-breach-route.ps1 -Zip
```

Review doc:
- `docs/phase17_monthly_reliability_governance.md`
- `docs/phase17_closure_sla_routing.md`

## 19. Quarterly governance package (phase_18)

```powershell
.\scripts\ga-quarterly-reliability-governance.ps1 -WindowDays 90 -Zip
.\scripts\ga-quarterly-closure-sla-ownership.ps1 -WindowDays 90 -Zip
.\scripts\ga-quarterly-review-package.ps1 -Zip
```

Review doc:
- `docs/phase18_quarterly_governance.md`

## 20. Upgrade and migration safety operations (phase_19)

```powershell
.\scripts\ga-upgrade-impact-matrix.ps1 -Zip
.\scripts\ga-migration-rehearsal-package.ps1 -Zip
.\scripts\ga-upgrade-rollback-safety.ps1 -Zip
.\scripts\ga-upgrade-evidence-closeout.ps1 -Zip
```

Review doc:
- `docs/phase19_upgrade_migration_safety.md`

## 21. Environment compatibility and support-at-scale baseline (phase_20)

```powershell
.\scripts\ga-supported-environment-matrix.ps1 -Zip
.\scripts\ga-compatibility-preflight.ps1 -Zip
.\scripts\ga-support-intake-normalization.ps1 -Zip
.\scripts\ga-environment-support-closeout.ps1 -Zip
```

Review docs:
- `docs/phase20_environment_compatibility_support.md`

## 22. Auditability, retention, and compliance-lite governance (phase_21)

```powershell
.\scripts\ga-artifact-retention-coverage.ps1 -Zip
.\scripts\ga-audit-traceability-index.ps1 -Zip
.\scripts\ga-incident-change-ledger.ps1 -Zip
.\scripts\ga-auditability-closeout.ps1 -Zip
```

Review docs:
- `docs/phase21_auditability_retention_governance.md`

## 23. Steady-state commercial operations closure (phase_22)

```powershell
.\scripts\ga-steady-state-operations-handbook.ps1 -Zip
.\scripts\ga-release-ops-cadence-baseline.ps1 -Zip
.\scripts\ga-end-to-end-operations-evidence.ps1 -Zip
.\scripts\ga-steady-state-closeout.ps1 -Zip
```

Review docs:
- `docs/phase22_steady_state_operations_closure.md`
- `docs/steady_state_operations_handbook.md`
- `docs/release_ops_cadence_baseline.md`

## 24. Steady-state bounded improvement backlog

```powershell
.\scripts\ga-steady-state-improvement-backlog.ps1 -Zip
```

Review doc:
- `docs/steady_state_improvement_backlog.md`

## 25. Steady-state watch backlog burn-down

```powershell
.\scripts\ga-steady-state-burndown.ps1 -Zip
```

Review doc:
- `docs/steady_state_burndown_tracking.md`

## 26. Steady-state checkpoint refresh

```powershell
.\scripts\ga-steady-state-checkpoint-refresh.ps1 -Zip
```

Review doc:
- `docs/steady_state_checkpoint_refresh.md`

## 27. Steady-state watchlist ownership routing

```powershell
.\scripts\ga-steady-state-escalation-watchlist-route.ps1 -OwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

Review doc:
- `docs/steady_state_watchlist_ownership_routing.md`
- `docs/steady_state_watchlist_owner_ack.json`

## 28. Steady-state single-entry runtime loop

```powershell
.\scripts\steady-state-run.ps1 -Mode daily -WatchlistOwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

Weekly heavier cycle:

```powershell
.\scripts\steady-state-run.ps1 -Mode weekly -WatchlistOwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

Review docs:
- `docs/steady_state_runtime_loop.md`
- `docs/steady_state_runtime_state.json`

## 14. Operational cadence (minimum)

Use this minimum cadence to keep internal beta operation stable:

- Per-session (start of work): run `.\scripts\macro_pulser\local-dev-smoke.ps1`, then verify `/status`, `/monitor`, `/signals`.
- Daily (shared branch health): run `.\scripts\macro_pulser\local-dev-smoke.ps1 -CheckReadOnlyApi` while API is running.
- Pre-demo / pre-handoff: rerun smoke and capture endpoint outputs for `/status`, `/monitor`, `/signals` in the handoff notes.

First read when monitor has open events:
1. `/monitor` to identify `monitor_type`, `severity`, and `dedupe_key`
2. `/status` to confirm latest live-cycle success and aggregate counts
3. `/signals` to check whether signal emission remains active for the current scenario
