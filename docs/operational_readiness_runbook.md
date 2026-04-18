# Operational Readiness Runbook

## 1. Primary command

Use this command as the default operational gate before starting work or shipping changes.

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
.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token"
# Optional extended gate: include operator suite + stage gate
.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite
.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorMaxStageFallbacks 0
.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorMaxLlmTransportFallbacks 0
.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorRequireStageTelemetry
# phase_7 strict policy gate (allowlist + backend override mismatch deny)
.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorRequirePolicyAssertions -OperatorPolicyMode strict -OperatorEnforceModelAllowlist -OperatorFailOnBackendOverrideMismatch
# phase_7 strict auth boundary + policy gate
.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorAuthorizationOperator "Bearer dev-operator-token" -OperatorRequirePolicyAssertions -OperatorPolicyMode strict -OperatorEnforceModelAllowlist -OperatorFailOnBackendOverrideMismatch -OperatorRequireAuthEvidence -OperatorExpectedAuthRoles "operator,approver" -OperatorAuthPolicyMode strict
# phase_7 breakglass example (exception run must keep explicit reason/actor evidence)
.\scripts\release-readiness.ps1 -SkipLiveSmoke -SkipSmoke -SkipResilience -SkipVerify -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorAuthorizationOperator "Bearer dev-operator-token" -OperatorRequirePolicyAssertions -OperatorPolicyMode breakglass -OperatorBreakglass -OperatorBreakglassReason "temporary live remediation verification" -OperatorBreakglassActor "<operator-id>"
# Optional: include OpenClaw gateway proof in the same gate run
.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOpenClawGatewayCheck
```

If route/auth contract changes are made, regenerate `openapi.json` before running readiness.

## 7. Operational decision rule

Use this single rule:

- If `release-readiness.ps1 -AutoSeedFullFlow` passes, the environment is ready
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
- `.\scripts\operator-menu.ps1` now accepts `readiness-manifest-<timestamp>.json` as the replay root for status/audit/stage-report/assert/handoff/stage-gate flows

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

## 11. MacroPulse local BLS-free smoke

Use this deterministic local flow when validating MacroPulse MVP behavior without remote schedule ingestion:

```powershell
.\scripts\local-dev-smoke.ps1
```

The script runs manual seed steps for releases/actuals/markets/snapshots, then executes:
- `python -m app.main live --once --skip-remote-schedules`
- `python -m app.main monitor --once`

Use `python -m app.main monitor --loop` only when continuous watch mode is required.

## 12. Telegram token hygiene (pre-production)

- Keep development and production Telegram bot tokens separated.
- Do not reuse dev bot tokens for production channels.
- Rotate Telegram bot token and chat target before production cutover.
- Keep `MONITORING_TELEGRAM_CHAT_ID` distinct when monitoring alerts should be isolated from normal signal notifications.

## 13. Internal beta read-only checks

After `.\scripts\local-dev-smoke.ps1` succeeds, use these read-only surfaces for quick operational confirmation:

- `GET /status`
- `GET /monitor`
- `GET /signals`

These endpoints are observability-only and do not change signal or monitoring state.
