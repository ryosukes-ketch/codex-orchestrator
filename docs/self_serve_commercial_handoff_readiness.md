# Self-Serve Commercial Handoff Readiness

## Purpose
Define the self-serve handoff package required to deliver a customer-managed environment with deterministic startup/readiness/support evidence.

## Handoff package command

```powershell
.\scripts\self-serve-handoff-package.ps1 `
  -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json `
  -PreflightReportPath .\logs\operational-readiness\self-serve-preflight-<timestamp>.json `
  -UpdateGuardManifestPath .\logs\self-serve\update-guard-<timestamp>\update-guard.manifest.json `
  -Zip
```

## Acceptance status
- `ready_for_handoff`
  - source manifest present
  - support intake present
  - no blocking findings in support intake
  - required scripts present
- `review_required`
  - any acceptance check failed

## Required scripts
- `scripts/self-serve-preflight.ps1`
- `scripts/self-serve-update-guard.ps1`
- `scripts/self-serve-support-intake.ps1`
- `scripts/sqlite-backup.ps1`
- `scripts/sqlite-restore.ps1`
- `scripts/sqlite-verify.ps1`
- `scripts/sqlite-export.ps1`
- `scripts/ai_work_system/release-readiness.ps1`

## Required evidence paths
1. readiness (or bundle) manifest
2. support intake manifest
3. failure classification JSON
4. preflight report
5. update-guard manifest

## Recommended sequence
1. `self-serve-preflight.ps1`
2. `self-serve-update-guard.ps1`
3. strict `scripts/ai_work_system/release-readiness.ps1`
4. `self-serve-support-intake.ps1`
5. `self-serve-handoff-package.ps1`

## Phase 10 closeout expectation
At least one handoff package with `acceptance_status=ready_for_handoff` should be recorded in `docs/staging_execution_record.md`.
