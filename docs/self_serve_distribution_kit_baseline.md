# Self-Serve Distribution Kit Baseline

## Purpose
Define the phase_10 baseline package for customer-managed setup/startup without changing strict policy guarantees.

## Baseline package directories
- `scripts/` : operator, readiness, sqlite recovery, support bundle entrypoints
- `docs/` : startup/readiness/operator/support/commercial handoff guidance
- `examples/briefs/` : safe starter briefs
- `logs/` : runtime evidence output roots (generated)
- `data/` : sqlite runtime storage root (generated)

## Required pre-install checks
1. Windows + PowerShell runtime availability
2. Python virtual environment prepared (`.venv` expected)
3. OpenClaw gateway reachable for live profile use
4. Writable `data/` and `logs/` directories

## Minimal setup sequence
```powershell
Copy-Item .env.example .env
.\scripts\self-serve-preflight.ps1 -EnvPath .\.env
.\scripts\ai_work_system\start-server.ps1 -PrintEffectiveConfigOnly
.\scripts\ai_work_system\start-server.ps1
```

## Strict readiness sequence (recommended baseline)
```powershell
$env:OPERATOR_API_TIMEOUT_SECONDS='600'
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token" -RunOperatorSuite -OperatorAuthorizationOperator "Bearer dev-operator-token" -OperatorRequireStageTelemetry -OperatorMaxLlmTransportFallbacks 0 -OperatorRequirePolicyAssertions -OperatorPolicyMode strict -OperatorEnforceModelAllowlist -OperatorFailOnBackendOverrideMismatch -OperatorRequireAuthEvidence -OperatorExpectedAuthRoles "operator,approver" -OperatorAuthPolicyMode strict -OperatorMaxRevisionReplanAttempts 3
```

## Mandatory package evidence outputs
- `logs/operational-readiness/readiness-summary-<timestamp>.json`
- `logs/operational-readiness/readiness-manifest-<timestamp>.json`
- `logs/operational-readiness/operator-suite-<timestamp>/bundle-manifest.json`
- `logs/operational-readiness/operator-suite-<timestamp>/suite-stage-gate.json`
- `logs/self-serve/update-guard-<timestamp>/update-guard.manifest.json`
- `logs/self-serve/support-intake-<timestamp>/support-intake.manifest.json`
- `logs/self-serve/handoff-package-<timestamp>/handoff-package.manifest.json`

## Packaging constraints
- Preserve strict completed-only semantics.
- Do not weaken allowlist/auth evidence requirements.
- Keep sqlite recovery commands available before any update/rollback step.

## Self-serve package closure commands
```powershell
.\scripts\self-serve-update-guard.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\self-serve-support-intake.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\self-serve-handoff-package.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```
