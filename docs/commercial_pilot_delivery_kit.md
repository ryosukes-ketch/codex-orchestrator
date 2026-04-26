# Commercial Pilot Delivery Kit

## Purpose
This document is the phase_9 entrypoint for assisted commercial pilot delivery.
It packages setup, operations, diagnostics, and support handoff into one deterministic flow.

## Audience
- Pilot operator (customer-side)
- Pilot approver (customer-side)
- Delivery owner (provider-side)

## Local profile baseline
Required baseline for pilot kits:
- `STATE_BACKEND=sqlite`
- `STATE_BACKEND_STRICT=true`
- `SQLITE_DB_PATH=data/codex.db`
- `SQLITE_BACKUP_DIR=logs/sqlite-backups`

Recommended runtime defaults:
- `OPERATOR_API_TIMEOUT_SECONDS=600` (OpenClaw live profile)
- `OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS=120`

## Delivery kit contents
1. Setup and startup
   - `docs/operational_startup_runbook.md`
2. Readiness gate and strict policy run
   - `docs/operational_readiness_runbook.md`
3. Operator workflow and lifecycle
   - `docs/operator_workflow_runbook.md`
4. Commercial support workflow
   - `docs/commercial_pilot_support_runbook.md`
5. Scope and known constraints
   - `docs/commercial_pilot_scope_and_constraints.md`
6. Acceptance checklist and signoff
   - `docs/commercial_pilot_acceptance_checklist.md`
7. Handoff checklist
   - `docs/commercial_pilot_handoff_checklist.md`
8. Customer inquiry template
   - `docs/commercial_pilot_inquiry_template.md`

## Standard command sequence (assisted pilot)
1. Startup profile:

```powershell
.\scripts\ai_work_system\start-server.ps1 -UseOpenClawDefaultProfile -OpenClawBackendModel openai-codex/gpt-5.2
```

2. Gateway proof:

```powershell
.\scripts\openclaw-gateway-check.ps1 -AgentId codex-orchestrator -BackendModel openai-codex/gpt-5.2
```

3. Strict readiness with operator suite:

```powershell
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorAuthorizationOperator "Bearer dev-operator-token" -OperatorRequireStageTelemetry -OperatorMaxLlmTransportFallbacks 0 -OperatorRequirePolicyAssertions -OperatorPolicyMode strict -OperatorEnforceModelAllowlist -OperatorFailOnBackendOverrideMismatch -OperatorRequireAuthEvidence -OperatorExpectedAuthRoles "operator,approver" -OperatorAuthPolicyMode strict -OperatorMaxRevisionReplanAttempts 3
```

4. Export replay/support artifacts from readiness root:

```powershell
.\scripts\operator-replay-export.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```

## Required artifacts to hand over
- `readiness-summary-<timestamp>.json`
- `readiness-manifest-<timestamp>.json`
- `operator-suite-<timestamp>\bundle-manifest.json`
- `operator-suite-<timestamp>\suite-stage-gate.json`
- `operator-suite-<timestamp>\suite-handoff.json`
- `support-bundle.manifest.json`
- `failure-classification.json`

## Completion note
A pilot delivery is considered package-complete when all documents listed above are present, linked, and aligned with script behavior.

Legacy compatibility aliases (still supported):
- `scripts\start-server.ps1`
- `scripts\release-readiness.ps1`
